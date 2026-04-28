"""Gemini-backed sample collector for the C4 5-wall platter.

The 2026-04-27 C4 platter has **five physical walls** rising from the
disc surface that divide it into five fixed angular sectors. The
runtime SectorCarousel uses those walls as the physical slot
boundaries, so we want a YOLO model that detects them in every C4
camera frame.

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
import numpy as np

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
# At most one wall can be hidden behind the output guide, so any
# correctly labeled frame returns either 4 or 5 walls. Anything
# below this floor is treated as a low-quality label and flagged
# in the metadata so the operator can spot it during review.
MIN_EXPECTED_WALL_COUNT = 4


@dataclass(frozen=True, slots=True)
class WallDetection:
    """One wall instance as labeled by the teacher.

    Coordinates are in *image pixels* — origin top-left, x to the
    right, y down. The wall is described by a centerline from the
    visible inner wall end to the visible outer wall end. Older raw
    responses may still include three grouped bboxes:

    * ``wall_full_xyxy`` — tight AABB enclosing the entire wall.
    * ``wall_start_inner_xyxy`` — small AABB at the inner end of the
      wall, where it meets the central black hub circle.
    * ``wall_end_outer_xyxy`` — small AABB at the outer end of the
      wall, where it meets the white outer rim.

    From these we derive:

    * ``hub_xy`` / ``rim_xy`` — segment endpoints, taken as the
      centers of the inner and outer marker bboxes.
    * ``thickness_px`` — wall thickness, taken as the smaller side of
      the inner marker bbox (clamped to a sane minimum).
    * ``bbox_xyxy`` — the AABB enclosing the derived thin wall OBB;
      this is what the YOLO-AABB loader and Hive review overlay use.
    * ``polygon_xy`` — 4-corner OBB rectangle inflated around the
      hub→rim segment; used for tight visualization and YOLO-OBB
      training.
    """

    wall_full_xyxy: tuple[float, float, float, float]
    wall_start_inner_xyxy: tuple[float, float, float, float]
    wall_end_outer_xyxy: tuple[float, float, float, float]
    hub_xy: tuple[float, float]
    rim_xy: tuple[float, float]
    thickness_px: float
    bbox_xyxy: tuple[float, float, float, float]
    polygon_xy: tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
    ]
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

    def to_yolo_obb_line(self, *, image_width: int, image_height: int) -> str:
        """YOLO-OBB format: ``class x1 y1 x2 y2 x3 y3 x4 y4`` (normalized)."""
        parts: list[str] = [str(WALL_DETECTOR_CLASS_ID)]
        for x, y in self.polygon_xy:
            nx = max(0.0, min(1.0, float(x) / float(image_width)))
            ny = max(0.0, min(1.0, float(y) / float(image_height)))
            parts.append(f"{nx:.6f}")
            parts.append(f"{ny:.6f}")
        return " ".join(parts)

    def to_record(self) -> dict[str, Any]:
        return {
            "wall_full_xyxy": list(self.wall_full_xyxy),
            "wall_start_inner_xyxy": list(self.wall_start_inner_xyxy),
            "wall_end_outer_xyxy": list(self.wall_end_outer_xyxy),
            "hub_xy": list(self.hub_xy),
            "rim_xy": list(self.rim_xy),
            "thickness_px": self.thickness_px,
            "bbox_xyxy": list(self.bbox_xyxy),
            "polygon_xy": [list(p) for p in self.polygon_xy],
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
        wall_count = len(self.walls)
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
            "wall_count": wall_count,
            "expected_wall_count": EXPECTED_WALL_COUNT,
            "min_expected_wall_count": MIN_EXPECTED_WALL_COUNT,
            "low_quality_label": wall_count < MIN_EXPECTED_WALL_COUNT,
            "walls": [wall.to_record() for wall in self.walls],
            "raw_response": self.raw_response,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def wall_detector_system_prompt() -> str:
    return (
        "You are a high-precision visual annotator for industrial "
        "machine parts. Your job is to find specific features on a "
        "round, gray rotating turntable and return their exact "
        "positions as bounding boxes. Return one valid JSON object "
        "only — no markdown, no commentary, no code fences."
    )


def wall_detector_prompt(*, image_width: int, image_height: int) -> str:
    return (
        "Task: identify thin straight radial dividers (walls) on a "
        "round gray rotating turntable and return their precise "
        "visible centerline geometry.\n"
        "\n"
        "Scene description:\n"
        "* The image is a top-down view of the C4 turntable in a "
        "  LEGO sorting machine, already cropped to the disc zone.\n"
        "* The disc surface is a flat MEDIUM-GRAY ring around a "
        "  central BLACK hub circle.\n"
        "* On the surface there are exactly "
        f"{EXPECTED_WALL_COUNT} physical radial walls — short rigid "
        "  dividers rising a few mm from the disc, running from "
        "  the central hub outward to the disc edge like the spokes "
        "  of a wheel. Each wall appears as a THIN GRAY LINE with a "
        "  bright highlight on one edge and a slight shadow on the "
        "  other (small but reliable visual cue).\n"
        "* The walls are evenly spaced around the disc center "
        f"(360 / {EXPECTED_WALL_COUNT} = 72° apart) but the turntable "
        "  rotates, so absolute angles vary frame to frame. Because "
        "  it rotates, **4 OR 5 walls** can be visible at any given "
        "  moment — at most one wall may be hidden under a black "
        "  drop-chute mask. Find every visible wall, do NOT invent "
        "  hidden ones, do NOT skip visible ones.\n"
        "* Solid BLACK regions are out-of-frame machine geometry "
        "  (outside the active polygon, the drop hole, the drop "
        "  chute, the central hub circle) — they are NOT walls.\n"
        "* The WHITE outer ring around the disc is the physical "
        "  outer rim of the platter, NOT a wall.\n"
        "\n"
        "For each visible wall, return ONE wall object with:\n"
        "1. ``inner_point`` — the center of the visible inner end of "
        "   the wall body, just outside the central black hub. Do NOT "
        "   place this point inside the black hub circle.\n"
        "2. ``outer_point`` — the center of the visible outer end of "
        "   the wall body, just inside the white outer rim. Do NOT "
        "   place this point on the white rim itself.\n"
        "3. ``thickness`` — the apparent wall thickness in normalized "
        "   pixels on the 0..1000 coordinate scale.\n"
        "4. ``wall_bbox`` — an optional tight axis-aligned bbox around "
        "   the visible wall body only. It is used for debugging; the "
        "   centerline is the source of truth.\n"
        "\n"
        "Coordinates: use Gemini's standard 0..1000 normalized scale. "
        "Points use [y, x] order. Bboxes use [y_min, x_min, y_max, x_max] "
        f"order. We will rescale to the {image_width}x{image_height} "
        "pixel image ourselves.\n"
        "\n"
        "Output JSON schema:\n"
        "{\n"
        '  "detected_walls_count": 0,\n'
        '  "walls": [\n'
        "    {\n"
        '      "wall_id": 1,\n'
        '      "inner_point": [y, x],\n'
        '      "outer_point": [y, x],\n'
        '      "thickness": 12,\n'
        '      "wall_bbox": [y_min, x_min, y_max, x_max],\n'
        '      "confidence": 0.0,\n'
        '      "angular_hint_deg": null,\n'
        '      "note": null\n'
        "    }\n"
        "  ],\n"
        '  "notes": null\n'
        "}\n"
        "\n"
        "Rules:\n"
        f"- ``walls`` MUST contain {EXPECTED_WALL_COUNT - 1} or "
        f"{EXPECTED_WALL_COUNT} entries (4 or 5).\n"
        "- ``inner_point`` and ``outer_point`` must lie on the visible "
        "  gray wall ridge, centered across the wall thickness.\n"
        "- ``thickness`` should normally be 8..30 normalized units. "
        "  Use the visible ridge thickness, not the sector width.\n"
        "- ``wall_bbox`` covers the WHOLE visible wall body, but not "
        "  the gray sector area between walls.\n"
        "- ``confidence`` is 0..1 for the whole wall annotation.\n"
        "- ``angular_hint_deg`` is optional: the wall's angle around "
        "  the disc center (0° = +x / right, 90° = up, CCW positive) "
        "  measured from inner→outer.\n"
        "- ``note`` is only for occlusion or ambiguity callouts.\n"
        "- Do NOT label: the central hub, the white outer rim, the "
        "  gray sector area between walls, LEGO pieces, shadows, "
        "  reflections, or any solid black region.\n"
        "- Returning fewer than 4 walls means you missed visible "
        "  ones — re-look. Do not invent walls."
    )


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


_GEMINI_NORMALIZED_SCALE = 1000.0
_MIN_WALL_THICKNESS_PX = 4.0


def _coerce_yxyx_bbox(
    raw: Any,
    *,
    image_width: int,
    image_height: int,
) -> tuple[float, float, float, float] | None:
    """Convert a Gemini ``[y_min, x_min, y_max, x_max]`` 0..1000 bbox to
    pixel ``(x_min, y_min, x_max, y_max)``. Returns ``None`` for invalid or
    degenerate boxes after clamping."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        y_min, x_min, y_max, x_max = (float(v) for v in raw)
    except (TypeError, ValueError):
        return None
    for v in (y_min, x_min, y_max, x_max):
        if math.isnan(v) or math.isinf(v):
            return None
    # Order-normalize — Gemini occasionally swaps min/max.
    y_lo, y_hi = (y_min, y_max) if y_min <= y_max else (y_max, y_min)
    x_lo, x_hi = (x_min, x_max) if x_min <= x_max else (x_max, x_min)
    sx = float(image_width) / _GEMINI_NORMALIZED_SCALE
    sy = float(image_height) / _GEMINI_NORMALIZED_SCALE
    px_x_lo = max(0.0, min(float(image_width), x_lo * sx))
    px_x_hi = max(0.0, min(float(image_width), x_hi * sx))
    px_y_lo = max(0.0, min(float(image_height), y_lo * sy))
    px_y_hi = max(0.0, min(float(image_height), y_hi * sy))
    if px_x_hi <= px_x_lo or px_y_hi <= px_y_lo:
        return None
    return (px_x_lo, px_y_lo, px_x_hi, px_y_hi)


def _coerce_yx_point(
    raw: Any,
    *,
    image_width: int,
    image_height: int,
) -> tuple[float, float] | None:
    """Convert a Gemini ``[y, x]`` 0..1000 point to pixel ``(x, y)``."""
    if not isinstance(raw, (list, tuple)) or len(raw) < 2:
        return None
    try:
        y, x = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isnan(y) or math.isinf(x) or math.isinf(y):
        return None
    sx = float(image_width) / _GEMINI_NORMALIZED_SCALE
    sy = float(image_height) / _GEMINI_NORMALIZED_SCALE
    px = max(0.0, min(float(image_width), x * sx))
    py = max(0.0, min(float(image_height), y * sy))
    return (px, py)


def _coerce_normalized_thickness(raw: Any, *, image_width: int, image_height: int) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v) or v <= 0:
        return None
    # A normalized wall thickness is not tied to a single axis; use the
    # smaller pixel scale so diagonal walls do not become over-inflated.
    scale = min(float(image_width), float(image_height)) / _GEMINI_NORMALIZED_SCALE
    return max(_MIN_WALL_THICKNESS_PX, v * scale)


def _bbox_center(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _bbox_short_side(bbox: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = bbox
    return min(x2 - x1, y2 - y1)


def _segment_to_obb_polygon(
    hub_xy: tuple[float, float],
    rim_xy: tuple[float, float],
    thickness_px: float,
    *,
    image_width: int,
    image_height: int,
) -> tuple[
    tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
    tuple[float, float, float, float],
] | None:
    """Inflate a hub→rim segment to an OBB polygon (4 corners, CCW from hub-left).

    Returns ``(polygon, aabb)`` where ``polygon`` is a 4-tuple of
    ``(x, y)`` corners and ``aabb`` is ``(x1, y1, x2, y2)`` enclosing
    the polygon, both in pixel coordinates clipped to the image.
    """
    hx, hy = hub_xy
    rx, ry = rim_xy
    dx = rx - hx
    dy = ry - hy
    length = math.hypot(dx, dy)
    if length <= 1.0:
        return None
    nx = -dy / length
    ny = dx / length
    half = max(_MIN_WALL_THICKNESS_PX, thickness_px) / 2.0
    corners = (
        (hx + nx * half, hy + ny * half),
        (hx - nx * half, hy - ny * half),
        (rx - nx * half, ry - ny * half),
        (rx + nx * half, ry + ny * half),
    )
    clamped: list[tuple[float, float]] = []
    for cx, cy in corners:
        cx = max(0.0, min(float(image_width), cx))
        cy = max(0.0, min(float(image_height), cy))
        clamped.append((cx, cy))
    xs = [c[0] for c in clamped]
    ys = [c[1] for c in clamped]
    aabb = (min(xs), min(ys), max(xs), max(ys))
    if aabb[2] - aabb[0] <= 0 or aabb[3] - aabb[1] <= 0:
        return None
    polygon = (clamped[0], clamped[1], clamped[2], clamped[3])
    return polygon, aabb


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
    """Convert a raw Gemini wall-detector response into typed walls.

    Preferred entries carry ``inner_point`` and ``outer_point`` 0..1000
    normalized ``[y, x]`` coordinates plus an optional ``thickness`` and
    ``wall_bbox``. Legacy entries with ``wall_start_inner`` /
    ``wall_end_outer`` marker bboxes are still accepted; endpoints are
    derived from marker centers. The OBB polygon is inflated from the
    centerline, and ``bbox_xyxy`` is the AABB around that OBB.
    """
    walls_raw = payload.get("walls")
    if not isinstance(walls_raw, list):
        return [], _coerce_optional_str(payload.get("notes"))

    walls: list[WallDetection] = []
    for entry in walls_raw[: EXPECTED_WALL_COUNT]:
        if not isinstance(entry, dict):
            continue
        raw_full = entry.get("wall_bbox", entry.get("wall_full"))
        full = _coerce_yxyx_bbox(
            raw_full,
            image_width=image_width,
            image_height=image_height,
        )
        inner_point = _coerce_yx_point(
            entry.get("inner_point"),
            image_width=image_width,
            image_height=image_height,
        )
        outer_point = _coerce_yx_point(
            entry.get("outer_point"),
            image_width=image_width,
            image_height=image_height,
        )
        inner = _coerce_yxyx_bbox(
            entry.get("wall_start_inner"),
            image_width=image_width,
            image_height=image_height,
        )
        outer = _coerce_yxyx_bbox(
            entry.get("wall_end_outer"),
            image_width=image_width,
            image_height=image_height,
        )
        if inner_point is None and inner is not None:
            inner_point = _bbox_center(inner)
        if outer_point is None and outer is not None:
            outer_point = _bbox_center(outer)
        if inner_point is None or outer_point is None:
            continue
        hub = inner_point
        rim = outer_point
        # Thickness: prefer the explicit point-schema value. Fall back to the
        # legacy marker/full bboxes when reading older 3-bbox samples.
        explicit_thickness = _coerce_normalized_thickness(
            entry.get("thickness"),
            image_width=image_width,
            image_height=image_height,
        )
        thickness_px = max(
            _MIN_WALL_THICKNESS_PX,
            explicit_thickness
            or min(
                _bbox_short_side(inner) if inner is not None else 0.0,
                _bbox_short_side(full) if full is not None else 0.0,
            )
            or _MIN_WALL_THICKNESS_PX,
        )
        obb = _segment_to_obb_polygon(
            hub,
            rim,
            thickness_px,
            image_width=image_width,
            image_height=image_height,
        )
        if obb is None:
            continue
        polygon, aabb = obb
        if full is None:
            full = aabb
        marker_half = max(_MIN_WALL_THICKNESS_PX * 1.5, thickness_px * 1.5)
        if inner is None:
            inner = (
                max(0.0, hub[0] - marker_half),
                max(0.0, hub[1] - marker_half),
                min(float(image_width), hub[0] + marker_half),
                min(float(image_height), hub[1] + marker_half),
            )
        if outer is None:
            outer = (
                max(0.0, rim[0] - marker_half),
                max(0.0, rim[1] - marker_half),
                min(float(image_width), rim[0] + marker_half),
                min(float(image_height), rim[1] + marker_half),
            )
        walls.append(
            WallDetection(
                wall_full_xyxy=full,
                wall_start_inner_xyxy=inner,
                wall_end_outer_xyxy=outer,
                hub_xy=hub,
                rim_xy=rim,
                thickness_px=thickness_px,
                bbox_xyxy=aabb,
                polygon_xy=polygon,
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


def _encode_array_for_llm(image: np.ndarray) -> tuple[str, int, int]:
    if image is None or getattr(image, "size", 0) <= 0:
        raise ValueError("Wall-teacher image array is empty")
    height, width = image.shape[:2]
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("Wall-teacher image array could not be encoded")
    return base64.b64encode(encoded.tobytes()).decode("ascii"), int(width), int(height)


def _encode_image_for_llm(path: Path) -> tuple[str, int, int]:
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) <= 0:
        raise ValueError(f"Wall-teacher image could not be decoded: {path}")
    return _encode_array_for_llm(image)


# ---------------------------------------------------------------------------
# Teacher
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WallTeacherCall:
    """In-memory result of one Gemini wall-detection call.

    Used by callers (e.g. the live teacher_samples pipeline) that hold
    the image as ``np.ndarray`` and don't need the file-on-disk
    framing of :class:`WallTeacherResult`.
    """

    walls: list[WallDetection]
    image_width: int
    image_height: int
    model: str
    raw_response: dict[str, Any]
    notes: str | None = None


class GeminiWallTeacher:
    """OpenRouter/Gemini wall-detection annotator for one C4 frame."""

    def label_array(
        self,
        image: np.ndarray,
        *,
        model: str | None = None,
    ) -> WallTeacherCall:
        from server.services.llm_client import (
            chat_completion,
            extract_json_object,
            message_text,
            normalize_openrouter_model,
        )

        normalized_model = normalize_openrouter_model(
            model or DEFAULT_WALL_TEACHER_OPENROUTER_MODEL
        )
        image_b64, width, height = _encode_array_for_llm(image)
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
        return WallTeacherCall(
            walls=walls,
            image_width=width,
            image_height=height,
            model=normalized_model,
            raw_response=payload,
            notes=notes,
        )

    def label_image(
        self,
        image_path: Path,
        *,
        model: str | None = None,
    ) -> WallTeacherResult:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None or getattr(image, "size", 0) <= 0:
            raise ValueError(
                f"Wall-teacher image could not be decoded: {image_path}"
            )
        call = self.label_array(image, model=model)
        return WallTeacherResult(
            image_path=image_path,
            image_width=call.image_width,
            image_height=call.image_height,
            walls=call.walls,
            model=call.model,
            raw_response=call.raw_response,
            notes=call.notes,
        )


__all__ = [
    "DEFAULT_WALL_TEACHER_OPENROUTER_MODEL",
    "EXPECTED_WALL_COUNT",
    "GeminiWallTeacher",
    "MIN_EXPECTED_WALL_COUNT",
    "WALL_DETECTOR_CLASS_ID",
    "WALL_DETECTOR_CLASS_NAME",
    "WALL_DETECTOR_PROVIDER",
    "WALL_DETECTOR_SCHEMA_VERSION",
    "WALL_DETECTOR_SOURCE",
    "WALL_DETECTOR_STAGE",
    "WALL_TEACHER_MAX_TOKENS",
    "WALL_TEACHER_TIMEOUT_S",
    "WallDetection",
    "WallTeacherCall",
    "WallTeacherResult",
    "parse_wall_response",
    "wall_detector_prompt",
    "wall_detector_system_prompt",
]
