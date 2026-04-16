"""OpenRouter-backed detector for chamber, feeder, and carousel piece detection."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from typing import Any

import cv2
import numpy as np

from .classification_detection import ClassificationDetectionResult

logger = logging.getLogger(__name__)

DEFAULT_OPENROUTER_MODEL = "google/gemini-3-flash-preview"
# Detection is Gemini-only: other vision models produced inconsistent bounding
# boxes (wrong coordinate order, hallucinated objects on the masked-out white
# border). Keep this tight. Calibration consumes the same list — gemini-pro
# handles the multi-turn exposure reasoning well.
SUPPORTED_OPENROUTER_MODELS = (
    DEFAULT_OPENROUTER_MODEL,
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-3.1-pro-preview",
)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Gemini-3 flash typically returns in 3-6s; pro can spike past 15s on dense
# scenes. Budget for pro and let the caller's rate-limit retry handle real hangs.
OPENROUTER_API_TIMEOUT_S = 25.0


def normalize_openrouter_model(model: str | None) -> str:
    if isinstance(model, str):
        normalized = model.strip()
        if normalized in SUPPORTED_OPENROUTER_MODELS:
            return normalized
    return DEFAULT_OPENROUTER_MODEL


SYSTEM_PROMPT = (
    "You are a precise object detector for a LEGO sorting machine. The machine "
    "is expected to process LEGO pieces but it also needs to notice anything "
    "else that ended up in the workflow — screws, coins, pebbles, plastic "
    "fragments, tape, hair, wrappers, any foreign object. Detect LEGO pieces "
    "AND non-LEGO items with equal attention. "
    "Respond with valid JSON only — no markdown, no prose, no explanations."
)


ZONE_PROMPTS: dict[str, tuple[str, str]] = {
    "classification_chamber": (
        "The image comes from the machine's classification chamber. A top-down "
        "camera looks at a small flat tray where one LEGO piece at a time is "
        "delivered for identification. The tray is lit by a bright LED ring "
        "around its edge.",
        "Ignore the tray surface, the LED ring and its bright halo, specular "
        "reflections on the tray, and shadows cast by the piece. Do NOT shrink "
        "a piece's bounding box to exclude glare or highlights on the piece "
        "itself — glare is part of the piece.",
    ),
    "carousel": (
        "The image comes from the machine's carousel drop zone. A top-down "
        "camera looks at a rotating turntable with a black center disc where "
        "sorted pieces land.",
        "Ignore the turntable surface, the black center disc, specular "
        "reflections on the turntable, and shadows that are not part of a "
        "piece. Do NOT treat the black disc as a piece.",
    ),
    "c_channel": (
        "The image comes from one of the machine's feed channels. A top-down "
        "camera looks at a narrow C-shaped channel along which pieces slide "
        "toward the classification chamber.",
        "Ignore the channel surface, specular reflections, and shadows that "
        "are not part of a piece.",
    ),
}


def _gemini_prompt(width: int, height: int, zone: str = "classification_chamber") -> str:
    context, ignore_rules = ZONE_PROMPTS.get(zone, ZONE_PROMPTS["classification_chamber"])
    return (
        f"{context}\n\n"
        f"{ignore_rules}\n\n"
        "Pixels outside the active region may appear as solid white "
        "(255,255,255) where the polygon mask was applied. Treat this white "
        "border as out-of-frame — it is NOT background and NOT an object.\n\n"
        "Detection rules:\n"
        "- Detect every distinct physical item exactly once: LEGO parts AND "
        "any foreign object (screws, coins, pebbles, plastic fragments, tape, "
        "hair, wrappers, tools, etc.). Non-LEGO matters — it is how the "
        "machine catches contamination.\n"
        "- Return a tight bounding box covering each item's full extent, "
        "including any glare on the item itself.\n"
        "- Ignore objects whose bounding box is smaller than ~1% of the image "
        "area unless they are clearly a physical object (not dust/scratch).\n"
        "- If two items are touching or stacked and visually separable, "
        "return one box per item; if fused into one indistinct cluster, "
        "return a single box covering the cluster.\n"
        "- Omit detections with confidence below 0.5.\n"
        "- If no items are visible, return an empty detections array.\n\n"
        "Output format (JSON only, no markdown):\n"
        '{"detections":[{"kind":"lego|foreign","description":"<short label>",'
        '"bbox":[y_min,x_min,y_max,x_max],"confidence":0.0-1.0}]}\n\n'
        "Field semantics:\n"
        "- bbox: Gemini's normalized 0-1000 scale, order "
        f"[y_min, x_min, y_max, x_max], for this {width}x{height} image.\n"
        "- kind: 'lego' if you are confident it is a LEGO/compatible plastic "
        "part; 'foreign' for anything else (screw, coin, stone, wrapper, "
        "unknown). When unsure, prefer 'foreign' — the machine must flag it "
        "for human review either way.\n"
        "- description: short lowercase string. For lego kind, use "
        "'<color> <shape>' where shape ∈ "
        "{brick, plate, tile, slope, round, axle, gear, minifig, other}. "
        "For foreign kind, describe what you see (e.g. 'metal screw', "
        "'brown pebble', 'crumpled paper').\n"
        "- confidence: 0.9+ you are certain the item exists (regardless of "
        "kind); 0.5-0.7 uncertain whether it is an item at all vs. artifact. "
        "Confidence is about 'is this an object', NOT 'is this LEGO'."
    )


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError("Model response did not contain JSON.")
    raw = match.group()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try fixing common issues: trailing commas before ] or }
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        return json.loads(cleaned)


def _call_openrouter(prompt: str, image_b64: str, *, model: str) -> dict[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not set.")
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package not installed — required for OpenRouter fallback.")
    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    response = client.chat.completions.create(
        model=normalize_openrouter_model(model),
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            },
        ],
        temperature=0.1,
        # Detection JSON is ~30-80 tokens per piece. 512 covers ~40 pieces —
        # well above any realistic tray — and surfaces truncation bugs fast.
        max_tokens=512,
        timeout=OPENROUTER_API_TIMEOUT_S,
    )
    return _extract_json(response.choices[0].message.content.strip())


def _parse_normalized_bbox(bbox: Any) -> tuple[float, float, float, float] | None:
    if isinstance(bbox, (list, tuple)):
        if len(bbox) < 4:
            return None
        try:
            v0, v1, v2, v3 = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            return None
        return v0, v1, v2, v3

    if isinstance(bbox, str):
        text = bbox.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return _parse_normalized_bbox(parsed)

    if isinstance(bbox, dict):
        key_variants = (
            ("y_min", "x_min", "y_max", "x_max"),
            ("ymin", "xmin", "ymax", "xmax"),
            ("top", "left", "bottom", "right"),
            ("y1", "x1", "y2", "x2"),
            ("min_y", "min_x", "max_y", "max_x"),
        )
        for keys in key_variants:
            if not all(key in bbox for key in keys):
                continue
            try:
                return tuple(float(bbox[key]) for key in keys)  # type: ignore[return-value]
            except (TypeError, ValueError):
                return None

    return None


def _get_detections(
    width: int,
    height: int,
    image_b64: str,
    *,
    openrouter_model: str,
    zone: str = "classification_chamber",
) -> list[dict[str, Any]]:
    """Call the configured OpenRouter vision model and parse pixel-coordinate bboxes."""
    prompt = _gemini_prompt(width, height, zone=zone)

    payload = _call_openrouter(prompt, image_b64, model=openrouter_model)

    sx = width / 1000.0
    sy = height / 1000.0

    raw_detections = payload.get("detections", [])
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Gemini raw detections image=%sx%s model=%s count=%s bboxes=%s",
            width,
            height,
            normalize_openrouter_model(openrouter_model),
            len(raw_detections),
            [det.get("bbox") for det in raw_detections if isinstance(det, dict)],
        )

    result: list[dict[str, Any]] = []
    for det in raw_detections:
        bbox = det.get("bbox", [0, 0, 0, 0])
        normalized_bbox = _parse_normalized_bbox(bbox)
        if normalized_bbox is None:
            continue
        v0, v1, v2, v3 = normalized_bbox
        # Gemini uses [y_min, x_min, y_max, x_max] in 0-1000 scale, even via OpenRouter.
        y1 = int(max(0.0, min(1000.0, v0)) * sy)
        x1 = int(max(0.0, min(1000.0, v1)) * sx)
        y2 = int(max(0.0, min(1000.0, v2)) * sy)
        x2 = int(max(0.0, min(1000.0, v3)) * sx)
        if x2 <= x1 or y2 <= y1:
            continue
        try:
            confidence = float(det.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        # Drop low-confidence detections here rather than downstream: the
        # prompt instructs the model to omit <0.5 but models sometimes leak
        # "maybe a smudge" entries with 0.3 anyway.
        if confidence < 0.5:
            continue
        kind_raw = str(det.get("kind", "lego")).strip().lower()
        kind = kind_raw if kind_raw in {"lego", "foreign"} else "lego"
        result.append({
            "kind": kind,
            "description": str(det.get("description", "piece")).strip() or "piece",
            "bbox": (x1, y1, x2, y2),
            "confidence": confidence,
        })
    return result


MIN_API_INTERVAL_S = 1.0  # minimum seconds between Gemini API calls


class GeminiSamDetector:
    """Detects objects in scoped frames using an OpenRouter vision model."""

    def __init__(self, openrouter_model: str = DEFAULT_OPENROUTER_MODEL, zone: str = "classification_chamber") -> None:
        self._last_call_time: float = 0.0
        self._last_result: ClassificationDetectionResult | None = None
        self._last_error: str | None = None
        self._openrouter_model: str = normalize_openrouter_model(openrouter_model)
        self._zone: str = zone

    def setOpenRouterModel(self, model: str) -> None:
        normalized = normalize_openrouter_model(model)
        if normalized == self._openrouter_model:
            return
        self._openrouter_model = normalized
        self._last_result = None
        self._last_call_time = 0.0

    def getOpenRouterModel(self) -> str:
        return self._openrouter_model

    def detect(self, frame: np.ndarray, force: bool = False) -> ClassificationDetectionResult | None:
        """Detect pieces in a BGR frame. Returns cached result if called too frequently.
        Set force=True to bypass rate limiting (used for snapping and debug test).
        """
        now = time.time()
        if not force and (now - self._last_call_time) < MIN_API_INTERVAL_S:
            return self._last_result

        h, w = frame.shape[:2]
        if h == 0 or w == 0:
            return None

        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
        image_b64 = base64.b64encode(buf).decode("utf-8")

        self._last_error = None
        start = time.time()
        try:
            detections = _get_detections(
                w,
                h,
                image_b64,
                openrouter_model=self._openrouter_model,
                zone=self._zone,
            )
        except Exception as exc:
            self._last_error = str(exc)
            logger.error(f"Gemini detection failed: {exc}")
            self._last_result = None
            return None
        finished_at = time.time()
        self._last_call_time = finished_at
        elapsed_ms = (finished_at - start) * 1000
        logger.info(f"Gemini detection: {len(detections)} pieces in {elapsed_ms:.0f}ms")

        if not detections:
            result = ClassificationDetectionResult(
                bbox=None, bboxes=(), score=0.0, algorithm="gemini_sam",
            )
            self._last_result = result
            return result

        detections.sort(key=lambda d: d["confidence"], reverse=True)
        best = detections[0]
        all_bboxes = tuple(d["bbox"] for d in detections)

        result = ClassificationDetectionResult(
            bbox=best["bbox"],
            bboxes=all_bboxes,
            score=best["confidence"],
            algorithm="gemini_sam",
        )
        self._last_result = result
        return result
