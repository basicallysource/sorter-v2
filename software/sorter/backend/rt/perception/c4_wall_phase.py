"""OpenCV wall-axis detector for the 5-wall C4 rotor.

The detector is intended for optical homing/calibration, not continuous
piece detection. It looks for long radial edges in the empty carousel image,
groups them into wall axes, and estimates the 5-sector phase from those axes.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np


DEFAULT_SECTOR_COUNT = 5


@dataclass(frozen=True, slots=True)
class WallLine:
    x1: float
    y1: float
    x2: float
    y2: float
    angle_deg: float
    score: float
    distance_to_center_px: float
    radius_min_px: float
    radius_max_px: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "line_xyxy": [self.x1, self.y1, self.x2, self.y2],
            "angle_deg": self.angle_deg,
            "score": self.score,
            "distance_to_center_px": self.distance_to_center_px,
            "radius_min_px": self.radius_min_px,
            "radius_max_px": self.radius_max_px,
        }


@dataclass(frozen=True, slots=True)
class C4WallPhaseResult:
    ok: bool
    width: int
    height: int
    center_x: float | None
    center_y: float | None
    radius_px: float | None
    sector_count: int
    sector_size_deg: float
    sector_offset_deg: float | None
    wall_angles_deg: tuple[float, ...]
    raw_line_count: int
    elapsed_ms: float
    message: str
    lines: tuple[WallLine, ...] = ()

    def as_dict(self, *, include_lines: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "frame_resolution": [self.width, self.height],
            "center_xy": (
                [self.center_x, self.center_y]
                if self.center_x is not None and self.center_y is not None
                else None
            ),
            "radius_px": self.radius_px,
            "sector_count": self.sector_count,
            "sector_size_deg": self.sector_size_deg,
            "sector_offset_deg": self.sector_offset_deg,
            "wall_angles_deg": list(self.wall_angles_deg),
            "wall_count": len(self.wall_angles_deg),
            "raw_line_count": self.raw_line_count,
            "elapsed_ms": self.elapsed_ms,
            "message": self.message,
        }
        if include_lines:
            payload["lines"] = [line.as_dict() for line in self.lines]
        return payload


def wrap_deg(value: float) -> float:
    return float(value) % 360.0


def shortest_angle_delta_deg(target_deg: float, current_deg: float) -> float:
    """Return signed shortest delta that moves ``current`` to ``target``."""
    return (float(target_deg) - float(current_deg) + 540.0) % 360.0 - 180.0


def phase_delta_deg(
    *,
    current_offset_deg: float,
    target_wall_angle_deg: float,
    sector_count: int = DEFAULT_SECTOR_COUNT,
) -> float:
    """Return the shortest tray delta to align any wall to ``target``.

    The wall phase repeats every sector, so the target is reduced modulo the
    sector width before comparing it with the measured wall offset.
    """
    if sector_count <= 0:
        raise ValueError("sector_count must be > 0")
    sector_size = 360.0 / float(sector_count)
    current = float(current_offset_deg) % sector_size
    target = float(target_wall_angle_deg) % sector_size
    delta = (target - current + sector_size / 2.0) % sector_size - sector_size / 2.0
    return float(delta)


def fit_disc_circle(image_bgr: np.ndarray) -> tuple[float, float, float]:
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    mask = (gray > 25).astype(np.uint8) * 255
    mask = cv2.morphologyEx(
        mask,
        cv2.MORPH_CLOSE,
        np.ones((9, 9), np.uint8),
        iterations=2,
    )
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("no non-black carousel contour found")
    contour = max(contours, key=cv2.contourArea)
    (x, y), radius = cv2.minEnclosingCircle(contour)
    if radius <= 0.0:
        raise ValueError("invalid carousel radius")
    return float(x), float(y), float(radius)


def _line_distance_to_point(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cx: float,
    cy: float,
) -> float:
    dx = x2 - x1
    dy = y2 - y1
    den = math.hypot(dx, dy)
    if den < 1.0:
        return 999999.0
    return abs(dy * cx - dx * cy + x2 * y1 - y2 * x1) / den


def _radius_range(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cx: float,
    cy: float,
) -> tuple[float, float]:
    values = [math.hypot(x1 - cx, y1 - cy), math.hypot(x2 - cx, y2 - cy)]
    return min(values), max(values)


def _line_orientation_180(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) % 180.0


def _midpoint_angle_360(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    cx: float,
    cy: float,
) -> float:
    mx = (x1 + x2) / 2.0
    my = (y1 + y2) / 2.0
    return math.degrees(math.atan2(my - cy, mx - cx)) % 360.0


def _angle_diff_180(a: float, b: float) -> float:
    return abs(((float(a) - float(b) + 90.0) % 180.0) - 90.0)


def _circular_mean_deg(values: list[float]) -> float:
    sin_sum = sum(math.sin(math.radians(v)) for v in values)
    cos_sum = sum(math.cos(math.radians(v)) for v in values)
    return math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0


def _phase_from_wall_angles(wall_angles_deg: list[float], sector_count: int) -> float | None:
    if sector_count <= 0 or not wall_angles_deg:
        return None
    sector_size = 360.0 / float(sector_count)
    sin_sum = 0.0
    cos_sum = 0.0
    for angle in wall_angles_deg:
        rel = float(angle) % sector_size
        theta = (rel / sector_size) * 2.0 * math.pi
        sin_sum += math.sin(theta)
        cos_sum += math.cos(theta)
    if sin_sum == 0.0 and cos_sum == 0.0:
        return None
    mean = math.atan2(sin_sum, cos_sum)
    if mean < 0.0:
        mean += 2.0 * math.pi
    return float((mean / (2.0 * math.pi)) * sector_size % sector_size)


def _angle_diff_360(a: float, b: float) -> float:
    return abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0)


def _nearest_phase_axis_distance(angle_deg: float, phase_deg: float, sector_count: int) -> float:
    sector_size = 360.0 / float(sector_count)
    rel = (float(angle_deg) - float(phase_deg)) % sector_size
    return min(rel, sector_size - rel)


def _fit_sector_phase(
    candidates: list[WallLine],
    *,
    sector_count: int,
    step_deg: float = 0.25,
    bandwidth_deg: float = 8.0,
) -> float | None:
    if sector_count <= 0 or not candidates:
        return None
    sector_size = 360.0 / float(sector_count)
    best_phase: float | None = None
    best_score = -float("inf")
    steps = max(1, int(round(sector_size / step_deg)))
    for idx in range(steps):
        phase = idx * sector_size / float(steps)
        score = 0.0
        for line in candidates:
            dist = _nearest_phase_axis_distance(
                line.angle_deg,
                phase,
                sector_count,
            )
            if dist > bandwidth_deg * 2.0:
                continue
            weight = math.exp(-0.5 * (dist / bandwidth_deg) ** 2)
            score += max(1.0, line.score) * weight
        if score > best_score:
            best_score = score
            best_phase = phase
    return best_phase


def _select_axes_for_phase(
    candidates: list[WallLine],
    *,
    phase_deg: float,
    sector_count: int,
    max_distance_deg: float = 14.0,
) -> list[WallLine]:
    if sector_count <= 0:
        return []
    sector_size = 360.0 / float(sector_count)
    selected: list[WallLine] = []
    used: set[int] = set()
    for slot in range(sector_count):
        target = (float(phase_deg) + float(slot) * sector_size) % 360.0
        best_idx: int | None = None
        best_value = -float("inf")
        for idx, line in enumerate(candidates):
            if idx in used:
                continue
            dist = _angle_diff_360(line.angle_deg, target)
            if dist > max_distance_deg:
                continue
            value = line.score - dist * 25.0
            if value > best_value:
                best_value = value
                best_idx = idx
        if best_idx is None:
            continue
        used.add(best_idx)
        selected.append(candidates[best_idx])
    return sorted(selected, key=lambda item: item.angle_deg)


def _group_wall_axes(
    candidates: list[WallLine],
    *,
    max_axes: int,
    min_separation_deg: float = 10.0,
) -> list[WallLine]:
    kept: list[WallLine] = []
    for line in sorted(candidates, key=lambda item: item.score, reverse=True):
        duplicate = False
        for existing in kept:
            diff = abs(((line.angle_deg - existing.angle_deg + 180.0) % 360.0) - 180.0)
            if diff < min_separation_deg:
                duplicate = True
                break
        if duplicate:
            continue
        kept.append(line)
        if len(kept) >= max_axes:
            break
    return sorted(kept, key=lambda item: item.angle_deg)


def detect_c4_wall_phase(
    image_bgr: np.ndarray,
    *,
    sector_count: int = DEFAULT_SECTOR_COUNT,
    downscale: float = 0.4,
    max_axes: int | None = None,
) -> C4WallPhaseResult:
    started = time.perf_counter()
    if image_bgr is None or not hasattr(image_bgr, "shape"):
        raise ValueError("image_bgr must be an OpenCV image")
    height, width = int(image_bgr.shape[0]), int(image_bgr.shape[1])
    sector_count = int(sector_count)
    sector_size = 360.0 / float(sector_count) if sector_count > 0 else 0.0
    max_axes = int(max_axes if max_axes is not None else max(1, sector_count))
    scale = float(downscale)
    if not math.isfinite(scale) or scale <= 0.0:
        scale = 1.0
    if scale < 0.999:
        work = cv2.resize(
            image_bgr,
            (0, 0),
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    else:
        work = image_bgr
        scale = 1.0

    try:
        cx, cy, radius = fit_disc_circle(work)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        return C4WallPhaseResult(
            ok=False,
            width=width,
            height=height,
            center_x=None,
            center_y=None,
            radius_px=None,
            sector_count=sector_count,
            sector_size_deg=sector_size,
            sector_offset_deg=None,
            wall_angles_deg=(),
            raw_line_count=0,
            elapsed_ms=elapsed_ms,
            message=f"disc fit failed: {exc}",
        )

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    h, w = int(work.shape[0]), int(work.shape[1])
    yy, xx = np.mgrid[:h, :w]
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    annulus = ((rr > radius * 0.20) & (rr < radius * 0.83) & (gray > 35)).astype(np.uint8) * 255
    equalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    blur = cv2.GaussianBlur(equalized, (3, 3), 0)
    edges = cv2.Canny(blur, 45, 115)
    edges = cv2.bitwise_and(edges, annulus)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)

    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 720.0,
        threshold=max(18, int(round(45 * scale))),
        minLineLength=max(20, int(round(radius * 0.16))),
        maxLineGap=max(6, int(round(18 * scale))),
    )
    candidates: list[WallLine] = []
    raw_line_count = 0 if lines is None else int(len(lines))
    if lines is not None:
        for raw in lines[:, 0, :]:
            x1, y1, x2, y2 = (float(v) for v in raw)
            length = math.hypot(x2 - x1, y2 - y1)
            if length < radius * 0.14:
                continue
            distance = _line_distance_to_point(x1, y1, x2, y2, cx, cy)
            if distance > radius * 0.075:
                continue
            r_min, r_max = _radius_range(x1, y1, x2, y2, cx, cy)
            if r_max < radius * 0.38 or r_min > radius * 0.78:
                continue
            line_orientation = _line_orientation_180(x1, y1, x2, y2)
            radial_angle = _midpoint_angle_360(x1, y1, x2, y2, cx, cy)
            if _angle_diff_180(line_orientation, radial_angle % 180.0) > 14.0:
                continue
            score = length - distance * 2.0 + (r_max - r_min) * 0.3
            candidates.append(
                WallLine(
                    x1=x1 / scale,
                    y1=y1 / scale,
                    x2=x2 / scale,
                    y2=y2 / scale,
                    angle_deg=radial_angle,
                    score=score / scale,
                    distance_to_center_px=distance / scale,
                    radius_min_px=r_min / scale,
                    radius_max_px=r_max / scale,
                )
            )

    fitted_phase = _fit_sector_phase(candidates, sector_count=sector_count)
    if fitted_phase is None:
        axes = _group_wall_axes(candidates, max_axes=max_axes)
    else:
        axes = _select_axes_for_phase(
            candidates,
            phase_deg=fitted_phase,
            sector_count=sector_count,
        )
        if not axes:
            axes = _group_wall_axes(candidates, max_axes=max_axes)
    angles = [line.angle_deg for line in axes]
    phase = fitted_phase if fitted_phase is not None else _phase_from_wall_angles(angles, sector_count)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    ok = phase is not None and len(axes) >= max(2, min(sector_count, 3))
    message = (
        f"detected {len(axes)} wall axis candidate(s)"
        if ok
        else f"insufficient wall axes: {len(axes)}"
    )
    return C4WallPhaseResult(
        ok=ok,
        width=width,
        height=height,
        center_x=cx / scale,
        center_y=cy / scale,
        radius_px=radius / scale,
        sector_count=sector_count,
        sector_size_deg=sector_size,
        sector_offset_deg=phase,
        wall_angles_deg=tuple(angles),
        raw_line_count=raw_line_count,
        elapsed_ms=elapsed_ms,
        message=message,
        lines=tuple(axes),
    )


__all__ = [
    "C4WallPhaseResult",
    "WallLine",
    "detect_c4_wall_phase",
    "fit_disc_circle",
    "phase_delta_deg",
    "shortest_angle_delta_deg",
    "wrap_deg",
]
