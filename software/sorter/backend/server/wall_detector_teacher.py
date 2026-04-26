"""Gemini-backed sample collector for the C4 5-wall platter.

The 2026-04-27 C4 platter has **five physical walls** rising from the
disc surface that divide it into five fixed angular sectors. To
calibrate ``CarouselC4Handler.sector_offset_deg`` reliably (and to
keep the offset live as the platter rotates) we want a YOLO model
that detects those walls in every C4 camera frame.

This module bootstraps the YOLO training set: it takes a captured C4
frame, asks Gemini (via the project's ``llm_client`` facade) to
locate the five walls visible from above, and emits

* one **YOLO label file** per image (one bbox per detected wall,
  single class ``wall``);
* a **JSON sample record** with the raw model output, image
  dimensions, model id, and the parsed walls — useful for review and
  for re-training without re-running the LLM.

It deliberately does not participate in the runtime piece flow.
Inference and runtime use will go through a trained YOLO model; this
module is the *teacher* that produces the initial training labels.
"""

from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2

WALL_DETECTOR_SCHEMA_VERSION = "wall_detector_v1"
WALL_DETECTOR_SOURCE = "wall_detector_teacher_capture"
WALL_DETECTOR_PROVIDER = "gemini_wall_detector"
WALL_DETECTOR_STAGE = "c4_wall_geometry"
WALL_DETECTOR_CLASS_ID = 0
WALL_DETECTOR_CLASS_NAME = "wall"

DEFAULT_WALL_TEACHER_OPENROUTER_MODEL = "google/gemini-3.1-flash-lite-preview"

WALL_TEACHER_TIMEOUT_S = 25.0
WALL_TEACHER_MAX_TOKENS = 1600

EXPECTED_WALL_COUNT = 5


@dataclass(frozen=True, slots=True)
class WallDetection:
    """One wall instance as labeled by the teacher.

    Coordinates are in *image pixels* — origin top-left, x to the
    right, y down. The bounding box is always axis-aligned (YOLO's
    native format); the teacher still records ``angular_hint_deg``
    when it can be derived from the platter geometry, but the
    bounding box is the authoritative training signal.
    """

    bbox_xyxy: tuple[float, float, float, float]
    confidence: float
    angular_hint_deg: float | None = None
    note: str | None = None

    def to_yolo_line(self, *, image_width: int, image_height: int) -> str:
        x1, y1, x2, y2 = self.bbox_xyxy
        cx = (x1 + x2) / 2.0 / float(image_width)
        cy = (y1 + y2) / 2.0 / float(image_height)
        w = (x2 - x1) / float(image_width)
        h = (y2 - y1) / float(image_height)
        cx = max(0.0, min(1.0, cx))
        cy = max(0.0, min(1.0, cy))
        w = max(0.0, min(1.0, w))
        h = max(0.0, min(1.0, h))
        return (
            f"{WALL_DETECTOR_CLASS_ID} "
            f"{cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "bbox_xyxy": list(self.bbox_xyxy),
            "confidence": self.confidence,
            "angular_hint_deg": self.angular_hint_deg,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class WallTeacherResult:
    """Full teacher output for one image."""

    image_path: Path
    image_width: int
    image_height: int
    walls: list[WallDetection]
    model: str
    raw_response: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None

    def to_yolo_labels(self) -> str:
        """Return the YOLO label-file body for this image."""
        return "\n".join(
            wall.to_yolo_line(
                image_width=self.image_width,
                image_height=self.image_height,
            )
            for wall in self.walls
        )

    def to_metadata(self) -> dict[str, Any]:
        return {
            "schema_version": WALL_DETECTOR_SCHEMA_VERSION,
            "source": WALL_DETECTOR_SOURCE,
            "provider": WALL_DETECTOR_PROVIDER,
            "stage": WALL_DETECTOR_STAGE,
            "model": self.model,
            "image_path": str(self.image_path),
            "image_size": {
                "width": self.image_width,
                "height": self.image_height,
            },
            "wall_count": len(self.walls),
            "expected_wall_count": EXPECTED_WALL_COUNT,
            "walls": [wall.to_record() for wall in self.walls],
            "raw_response": self.raw_response,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def wall_detector_system_prompt() -> str:
    return (
        "You are an annotation assistant for a LEGO sorting machine. "
        "Your only task is to locate the visible walls on the C4 "
        "rotating disc. Return only one valid JSON object — no "
        "markdown, no commentary, no code fences."
    )


def wall_detector_prompt(*, image_width: int, image_height: int) -> str:
    return (
        "The image is a top-down view of one rotating disc (the C4 "
        "platter) in a LEGO sorting machine. The disc has exactly "
        f"{EXPECTED_WALL_COUNT} radial walls — short rigid dividers "
        "rising from the disc surface — that split the disc into "
        f"{EXPECTED_WALL_COUNT} sectors. Each wall runs from somewhere "
        "near the center of the disc outward toward the rim, like a "
        "spoke. The walls' angular spacing is roughly equal "
        f"(360 / {EXPECTED_WALL_COUNT} = 72 degrees apart) but the "
        "platter sits at an arbitrary rotation, so the absolute "
        "angles are unknown.\n"
        "\n"
        "Return one JSON object describing every wall you can see. "
        "Partial detections are EXPECTED and correct: at most one "
        "wall can be hidden behind the output guide at any time, "
        "so frames with only 3-4 visible walls are normal — return "
        "what you can see, do NOT invent or guess walls that are "
        "occluded. Other occluders (a hand, a LEGO piece, deep "
        "shadow) similarly drop walls from the count; only label "
        "walls you are confident about.\n"
        "\n"
        "Coordinates are image pixels with the origin at the top-left, "
        "x increasing to the right, and y increasing downward. The "
        f"image is {image_width}x{image_height}px.\n"
        "\n"
        "Each wall must be returned as an axis-aligned bounding box "
        "that tightly contains the visible portion of the wall. Use "
        "the smallest box that still covers the wall on both sides. "
        "Do not include the disc surface, the central hub, the rim, "
        "the LEGO pieces, or any structural geometry outside the wall "
        "itself.\n"
        "\n"
        "Do NOT label:\n"
        "* the central hub or the disc rim\n"
        "* LEGO pieces sitting between walls\n"
        "* shadows, glare, or reflections\n"
        "* the chute, distributor, or other machine geometry that "
        "  happens to enter the frame\n"
        "* the output guide — a fixed rail/ramp/chute structure that "
        "  sits near the disc edge to direct pieces toward the "
        "  distributor. It is part of the machine frame, not part "
        "  of the rotating disc, and it does NOT move with the "
        "  platter. Even if it looks bar-shaped or wall-like, "
        "  ignore it. Note that one of the rotating walls can pass "
        "  underneath the output guide and become invisible from "
        "  this angle — when that happens, just return the 3-4 "
        "  walls you CAN see; do not draw a bbox where you only "
        "  guess a wall might be.\n"
        "* lines, cables, ArUco markers, or stickers\n"
        "\n"
        "Output JSON schema:\n"
        "{\n"
        '  "walls": [\n'
        '    {\n'
        '      "bbox_xyxy": [x1, y1, x2, y2],\n'
        '      "confidence": 0.0,\n'
        '      "angular_hint_deg": null,\n'
        '      "note": null\n'
        "    }\n"
        "  ],\n"
        '  "visible_evidence": "one short sentence",\n'
        '  "notes": null\n'
        "}\n"
        "\n"
        "Rules:\n"
        f"- ``walls`` is a list with at most {EXPECTED_WALL_COUNT} entries.\n"
        "- ``bbox_xyxy`` are integer pixel coordinates inside the image.\n"
        "- ``confidence`` is 0..1. Use lower values when the wall is "
        "  partially occluded or far from the camera.\n"
        "- ``angular_hint_deg`` is optional. Fill it with the wall's "
        "  approximate angle around the disc center (0° = right, 90° = "
        "  up, counter-clockwise) only if you can estimate it; "
        "  otherwise leave null.\n"
        "- Use ``note`` only to call out occlusion or ambiguity for "
        "  the operator.\n"
        "- Return an empty ``walls`` list if no wall is visible. Do "
        "  not invent walls."
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _coerce_bbox(
    raw: Any,
    *,
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float] | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    # Order-normalize — Gemini sometimes emits (x_min, y_min, x_max, y_max),
    # sometimes (x_min, y_max, x_max, y_min), depending on prompt phrasing.
    x_lo, x_hi = (x1, x2) if x1 <= x2 else (x2, x1)
    y_lo, y_hi = (y1, y2) if y1 <= y2 else (y2, y1)
    # Clamp to image extents so YOLO normalisation lands in [0, 1].
    x_lo = max(0.0, min(float(image_width), x_lo))
    x_hi = max(0.0, min(float(image_width), x_hi))
    y_lo = max(0.0, min(float(image_height), y_lo))
    y_hi = max(0.0, min(float(image_height), y_hi))
    if x_hi <= x_lo or y_hi <= y_lo:
        return None
    return (x_lo, y_lo, x_hi, y_hi)


def _coerce_confidence(raw: Any) -> float:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(v) or math.isinf(v):
        return 0.0
    return max(0.0, min(1.0, v))


def _coerce_optional_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _coerce_optional_str(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raw = str(raw)
    cleaned = raw.strip()
    return cleaned or None


def parse_wall_response(
    payload: dict[str, Any],
    *,
    image_width: int,
    image_height: int,
) -> tuple[list[WallDetection], str | None]:
    """Convert a raw Gemini wall-detector response into typed walls."""
    walls_raw = payload.get("walls")
    if not isinstance(walls_raw, list):
        return [], _coerce_optional_str(payload.get("notes"))

    walls: list[WallDetection] = []
    for entry in walls_raw[: EXPECTED_WALL_COUNT]:
        if not isinstance(entry, dict):
            continue
        bbox = _coerce_bbox(
            entry.get("bbox_xyxy"),
            image_width=image_width,
            image_height=image_height,
        )
        if bbox is None:
            continue
        walls.append(
            WallDetection(
                bbox_xyxy=bbox,
                confidence=_coerce_confidence(entry.get("confidence")),
                angular_hint_deg=_coerce_optional_float(
                    entry.get("angular_hint_deg")
                ),
                note=_coerce_optional_str(entry.get("note")),
            )
        )
    return walls, _coerce_optional_str(payload.get("notes"))


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------


def _encode_image_for_llm(path: Path) -> tuple[str, int, int]:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) <= 0:
        raise ValueError(f"Wall-teacher image could not be decoded: {path}")
    height, width = image.shape[:2]
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError(f"Wall-teacher image could not be encoded: {path}")
    return base64.b64encode(encoded.tobytes()).decode("ascii"), int(width), int(height)


# ---------------------------------------------------------------------------
# Teacher
# ---------------------------------------------------------------------------


class GeminiWallTeacher:
    """OpenRouter/Gemini wall-detection annotator for one C4 frame."""

    def label_image(
        self,
        image_path: Path,
        *,
        model: str | None = None,
    ) -> WallTeacherResult:
        from server.services.llm_client import (
            chat_completion,
            extract_json_object,
            message_text,
            normalize_openrouter_model,
        )

        normalized_model = normalize_openrouter_model(
            model or DEFAULT_WALL_TEACHER_OPENROUTER_MODEL
        )
        image_b64, width, height = _encode_image_for_llm(image_path)
        messages = [
            {"role": "system", "content": wall_detector_system_prompt()},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": wall_detector_prompt(
                            image_width=width, image_height=height
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_b64}"
                        },
                    },
                ],
            },
        ]

        try:
            response = chat_completion(
                messages,
                model=normalized_model,
                response_format={"type": "json_object"},
                max_tokens=WALL_TEACHER_MAX_TOKENS,
                timeout=WALL_TEACHER_TIMEOUT_S,
            )
        except Exception:
            response = chat_completion(
                messages,
                model=normalized_model,
                max_tokens=WALL_TEACHER_MAX_TOKENS,
                timeout=WALL_TEACHER_TIMEOUT_S,
            )

        try:
            payload = extract_json_object(
                message_text(response.choices[0].message.content)
            )
        except Exception as exc:
            raise RuntimeError(
                "Gemini wall teacher returned invalid JSON"
            ) from exc

        walls, notes = parse_wall_response(
            payload, image_width=width, image_height=height
        )
        return WallTeacherResult(
            image_path=image_path,
            image_width=width,
            image_height=height,
            walls=walls,
            model=normalized_model,
            raw_response=payload,
            notes=notes,
        )


__all__ = [
    "DEFAULT_WALL_TEACHER_OPENROUTER_MODEL",
    "EXPECTED_WALL_COUNT",
    "GeminiWallTeacher",
    "WALL_DETECTOR_CLASS_ID",
    "WALL_DETECTOR_CLASS_NAME",
    "WALL_DETECTOR_PROVIDER",
    "WALL_DETECTOR_SCHEMA_VERSION",
    "WALL_DETECTOR_SOURCE",
    "WALL_DETECTOR_STAGE",
    "WALL_TEACHER_MAX_TOKENS",
    "WALL_TEACHER_TIMEOUT_S",
    "WallDetection",
    "WallTeacherResult",
    "parse_wall_response",
    "wall_detector_prompt",
    "wall_detector_system_prompt",
]
