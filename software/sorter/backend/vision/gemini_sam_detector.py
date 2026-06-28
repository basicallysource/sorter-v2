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
    "google/gemini-3.5-flash",
)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Gemini-3 flash typically returns in 3-6s; pro can spike past 15s on dense
# scenes. Budget for pro plus slow internet — the machine often runs on a poor
# connection where a tight timeout turns a slow call into a hard failure. Let the
# caller's rate-limit retry handle real hangs.
OPENROUTER_API_TIMEOUT_S = 60.0


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
    "classification_channel": (
        "The image comes from the machine's classification C-channel / C4 "
        "turntable. A top-down camera watches a rotating turntable and its "
        "transfer/drop area while parts move toward classification and ejection. "
        "The C4 turntable is the round disc in the center of the frame, surrounded "
        "by a bright white outer rim/ring. The feeder C-channel terminates at the "
        "upper-left corner of the frame and drops parts ONTO the C4 disc — pieces "
        "still queued inside that feeder channel can be visible at the very edge "
        "of the frame, but they are NOT in the C4 work zone and must be ignored.",
        "Ignore the turntable surface, fixed dark center/opening, exit chute, "
        "outlet slot, rails, screws, lips, fixed black wedges/openings, LED "
        "glare, specular reflections, and shadows. In this camera view there "
        "is a fixed lower-right opening/notch/cut-out where the exit path "
        "begins; ignore that opening, its rim, dark interior, straight edges, "
        "and shadows even if it looks like a rectangular or wedge-shaped "
        "object. The C4 rotor may show four or five evenly spaced radial "
        "divider walls/fins running from the dark center toward the outer rim; "
        "ignore those divider walls, their raised edges, and their linear "
        "shadows even when they look like long grey objects. These are machine "
        "geometry, not pieces. Only label loose physical items sitting on, "
        "beside, or moving over that geometry. "
        "Critically: ONLY detect pieces that sit on the C4 rotor disc itself "
        "(inside the round white outer ring). Any piece that is wholly or even "
        "partially outside that disc — pieces still parked in the feeder C-channel "
        "that's visible in the upper-left corner, pieces resting on the white rim, "
        "pieces hanging off the edge — must be skipped entirely. A piece whose "
        "bounding box would touch or cross the bright white rim/ring is OUT and "
        "must not be returned. Err on the side of skipping anything near the rim.",
    ),
    "c_channel": (
        "The image comes from one of the machine's feed channels. A top-down "
        "camera looks at a narrow C-shaped channel along which pieces slide "
        "toward the classification chamber.",
        "Ignore the channel surface, fixed side walls, rails, screws, slots, "
        "dark fixed openings, specular reflections, and shadows. These are "
        "machine geometry, not pieces. Only label loose physical items.",
    ),
}


_CLASSIFICATION_CHANNEL_PROMPT = (
    'You are detecting loose physical objects on a C4 classification turntable from a '
    'top-down {width}x{height} camera image.\n\n'
    'Task:\n'
    'Return one tight bounding box for each loose physical item that is fully inside the '
    'active C4 rotor disc. Detect LEGO/compatible plastic parts and foreign objects such '
    'as screws, coins, stones, tape, hair, wrappers, fragments, tools, or unknown debris.\n\n'
    'Active detection zone:\n'
    '- The C4 rotor disc is the round disc in the center, bounded by the bright white '
    'outer rim/ring.\n'
    '- Detect ONLY objects whose entire bounding box lies inside the rotor disc, not '
    'touching or crossing the bright white rim.\n'
    '- Skip anything on the rim, crossing the rim, hanging off the edge, or outside the disc.\n'
    '- Skip parts still queued in the feeder C-channel at the upper-left edge of the frame, '
    'even if visible.\n'
    '- Err on the side of skipping objects near the rim.\n'
    '- Pixels outside the active crop may be solid white from a polygon mask; treat this '
    'as out-of-frame, not background and not an object.\n\n'
    'Ignore fixed machine geometry:\n'
    'Do NOT detect the turntable surface, dark center/opening, outlet slot, exit chute, '
    'rails, screws, lips, fixed black wedges/openings, LED glare, specular reflections, '
    'shadows, or any fixed machine feature.\n\n'
    'C4-specific ignore rules:\n'
    '- Ignore the fixed lower-right exit opening/notch/cut-out, including its rim, dark '
    'interior, straight edges, and shadows.\n'
    '- Ignore the four or five evenly spaced radial divider walls/fins running from the '
    'dark center toward the outer rim.\n'
    '- Ignore the raised edges and long straight shadows of those divider walls/fins, even '
    'if they look like long grey objects.\n\n'
    'Detection rules:\n'
    '- Detect every distinct loose physical item exactly once.\n'
    '- Prefer splitting over grouping: if touching, overlapping, or stacked items are '
    'visually separable by silhouette, edge, color/material, studs, holes, or visible '
    'boundaries, return one box per item.\n'
    '- If a cluster is fused or visually inseparable, return one box around the cluster.\n'
    '- Include small, dark, shiny, transparent, translucent, low-contrast, partly occluded, '
    'or edge-cropped items if they are clearly physical objects inside the disc.\n'
    '- Ignore dust, scratches, stains, shadows, glare, and artifacts.\n'
    '- Ignore detections with object-confidence below 0.5.\n'
    '- Ignore objects whose bounding box is smaller than about 1% of image area unless they '
    'are clearly real physical objects.\n'
    '- Bounding boxes must be tight around the visible object extent, including glare that '
    'belongs to the object itself.\n\n'
    'Classification:\n'
    '- kind = "lego" only if the item is confidently a LEGO/compatible plastic part.\n'
    '- kind = "foreign" for screws, coins, stones, wrappers, debris, unknown objects, or '
    'anything uncertain.\n'
    '- confidence measures whether the item is a real object, not whether the class label '
    'is certain.\n\n'
    'Output JSON only:\n'
    '{{\n'
    '  "detections": [\n'
    '    {{\n'
    '      "kind": "lego|foreign",\n'
    '      "description": "<short label>",\n'
    '      "bbox": [y_min, x_min, y_max, x_max],\n'
    '      "confidence": 0.0\n'
    '    }}\n'
    '  ]\n'
    '}}\n\n'
    'bbox:\n'
    '- Normalized 0-1000 coordinates.\n'
    '- Order: [y_min, x_min, y_max, x_max].\n\n'
    'If no valid objects are visible, return:\n'
    '{{"detections":[]}}'
)


def _gemini_prompt(width: int, height: int, zone: str = "classification_chamber") -> str:
    # Compact, focused prompt for the C4 classification_channel zone. Keep in lock-step
    # with the Hive copy in software/hive/backend/app/services/teacher_detector.py.
    if zone == "classification_channel":
        return _CLASSIFICATION_CHANNEL_PROMPT.format(width=width, height=height)
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
        "- Strive for exhaustive recall: do not omit any real loose part that "
        "is visible enough to localize, including small, partly occluded, "
        "edge-cropped, low-contrast, dark, shiny, transparent, or translucent "
        "pieces. Scan the entire active crop before returning.\n"
        "- Prefer splitting over grouping: if multiple loose parts touch, "
        "overlap, stack, or partially cover each other but their visible "
        "bodies, edges, color/material changes, studs, holes, or silhouettes "
        "allow separation, return one tight box per part. Do not draw one "
        "large box around a pile of separable parts.\n"
        "- Do not detect fixed machine geometry, even if it is dark, high "
        "contrast, or shaped like a part. In particular, ignore outlet slots, "
        "exit chutes, turntable holes, fixed black shadows/openings, rails, "
        "and walls. For the C4 turntable specifically, ignore the lower-right "
        "exit opening/notch/cut-out and its rim, dark interior, straight edges, "
        "and shadows; also ignore the evenly spaced radial divider walls/fins "
        "and their long straight shadows. Do not draw boxes around these fixed "
        "features.\n"
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
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            salvaged = _salvage_detection_payload(raw)
            if salvaged is not None:
                logger.warning(
                    "Gemini response contained malformed JSON; salvaged %s detection objects.",
                    len(salvaged["detections"]),
                )
                return salvaged
            raise


def _iter_balanced_json_objects(text: str):
    """Yield balanced object substrings from a possibly malformed JSON response."""
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(text)):
            current = text[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : end + 1]
                    break


def _salvage_detection_payload(raw: str) -> dict[str, Any] | None:
    detections: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in _iter_balanced_json_objects(raw):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict) or "bbox" not in parsed:
            continue
        if _parse_normalized_bbox(parsed.get("bbox")) is None:
            continue
        key = json.dumps(parsed, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        detections.append(parsed)
    if not detections:
        return None
    return {"detections": detections}


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
        # Dense C-channel frames can contain many parts plus short descriptions.
        # Keep enough headroom so the teacher returns valid JSON instead of a
        # truncated object that later becomes a false "no detections" sample.
        max_tokens=2048,
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
        if not os.getenv("OPENROUTER_API_KEY"):
            raise RuntimeError("OPENROUTER_API_KEY is not set.")
        self._last_call_time: float = 0.0
        self._last_result: ClassificationDetectionResult | None = None
        self._last_error: str | None = None
        self._openrouter_model: str = normalize_openrouter_model(openrouter_model)
        self._zone: str = zone

    def setZone(self, zone: str) -> None:
        if zone == self._zone:
            return
        self._zone = zone
        self._last_result = None
        self._last_call_time = 0.0

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
