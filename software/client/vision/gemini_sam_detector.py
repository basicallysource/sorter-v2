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
SUPPORTED_OPENROUTER_MODELS = (
    DEFAULT_OPENROUTER_MODEL,
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-3.1-pro-preview",
    "reka/reka-edge",
    "anthropic/claude-sonnet-4.6",
    "xiaomi/mimo-v2-omni",
    "moonshotai/kimi-k2.5",
    "openai/gpt-5.4",
    "openai/gpt-5.4-nano",
    "qwen/qwen3.5-flash-02-23",
)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def normalize_openrouter_model(model: str | None) -> str:
    if isinstance(model, str):
        normalized = model.strip()
        if normalized in SUPPORTED_OPENROUTER_MODELS:
            return normalized
    return DEFAULT_OPENROUTER_MODEL


def _gemini_prompt(width: int, height: int) -> str:
    return (
        "You are annotating a cropped tray image from a LEGO sorter classification chamber.\n\n"
        "Detect every distinct loose LEGO piece visible in the tray crop.\n\n"
        "Rules:\n"
        "- Detect each separate LEGO piece exactly once.\n"
        "- Ignore tray walls, tray floor, reflections, highlights, screws, printed markers, and static hardware.\n"
        "- Ignore shadows unless they are part of the piece body.\n"
        "- Return tight boxes around the actual piece extents.\n"
        "- If no pieces are visible, return an empty detections array.\n\n"
        "Return ONLY valid JSON, no markdown:\n"
        '{"detections":[{"description":"brief piece description",'
        '"bbox":[y_min,x_min,y_max,x_max],"confidence":0.0-1.0}]}\n\n'
        f"Coordinates must use a 0-1000 normalized scale for this {width}x{height} image."
    )


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise RuntimeError("Model response did not contain JSON.")
    return json.loads(match.group())


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
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }
        ],
        temperature=0.1,
        max_tokens=3000,
    )
    return _extract_json(response.choices[0].message.content.strip())


def _get_detections(
    width: int,
    height: int,
    image_b64: str,
    *,
    openrouter_model: str,
) -> list[dict[str, Any]]:
    """Call Gemini API and return parsed detections with pixel-coordinate bboxes."""
    prompt = _gemini_prompt(width, height)

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
        try:
            v0, v1, v2, v3 = [float(v) for v in bbox[:4]]
        except (TypeError, ValueError):
            continue
        # Gemini uses [y_min, x_min, y_max, x_max] in 0-1000 scale, even via OpenRouter.
        y1 = int(max(0.0, min(1000.0, v0)) * sy)
        x1 = int(max(0.0, min(1000.0, v1)) * sx)
        y2 = int(max(0.0, min(1000.0, v2)) * sy)
        x2 = int(max(0.0, min(1000.0, v3)) * sx)
        if x2 <= x1 or y2 <= y1:
            continue
        result.append({
            "description": str(det.get("description", "piece")).strip() or "piece",
            "bbox": (x1, y1, x2, y2),
            "confidence": float(det.get("confidence", 0.5)),
        })
    return result


MIN_API_INTERVAL_S = 5.0  # minimum seconds between Gemini API calls


class GeminiSamDetector:
    """Detects LEGO pieces in scoped frames using an OpenRouter vision model."""

    def __init__(self, openrouter_model: str = DEFAULT_OPENROUTER_MODEL) -> None:
        self._last_call_time: float = 0.0
        self._last_result: ClassificationDetectionResult | None = None
        self._last_error: str | None = None
        self._openrouter_model: str = normalize_openrouter_model(openrouter_model)

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
