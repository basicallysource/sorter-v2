"""How the dashboard crops a camera to its channel's zone.

The crop is the zone's bounding box with everything outside the zone painted
light gray, turned so the drop zone starts in the same place for every channel
(see vision/channel_alignment.py). The camera feeds send this shape with each
camera's layout; the page cuts the picture to it.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

from local_state import get_channel_polygons
from vision.channel_alignment import (
    alignmentRotationDeg,
    angleKeyForPolygonKey,
    dropStartAngleForRole,
    polygonKeyForRole,
)

def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _dashboard_polygon_resolution(saved: Dict[str, Any] | None) -> tuple[float, float]:
    if not isinstance(saved, dict):
        return (1920.0, 1080.0)
    return _dashboard_saved_resolution(saved.get("resolution"), (1920.0, 1080.0))


def _dashboard_saved_resolution(
    resolution: Any,
    fallback: tuple[float, float],
) -> tuple[float, float]:
    if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
        width = _as_number(resolution[0])
        height = _as_number(resolution[1])
        if width and width > 0 and height and height > 0:
            return (width, height)
    return fallback


def _dashboard_channel_resolution(
    saved: Dict[str, Any],
    polygon_key: str,
) -> tuple[float, float]:
    fallback = _dashboard_polygon_resolution(saved)
    angle_key = angleKeyForPolygonKey(polygon_key)
    arc_params = saved.get("arc_params") if isinstance(saved.get("arc_params"), dict) else {}
    if angle_key is not None:
        raw_arc = arc_params.get(angle_key)
        if isinstance(raw_arc, dict):
            return _dashboard_saved_resolution(raw_arc.get("resolution"), fallback)
    quad_params = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
    raw_quad = quad_params.get(polygon_key)
    if isinstance(raw_quad, dict):
        return _dashboard_saved_resolution(raw_quad.get("resolution"), fallback)
    return fallback


def _dashboard_points(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, (list, tuple)):
        return []
    points: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x = _as_number(point[0])
        y = _as_number(point[1])
        if x is None or y is None:
            continue
        points.append((float(x), float(y)))
    return points


def _scale_dashboard_points(
    points: list[tuple[float, float]],
    source_resolution: tuple[float, float],
    frame_w: int,
    frame_h: int,
) -> np.ndarray | None:
    if len(points) < 3:
        return None
    src_w, src_h = source_resolution
    if src_w <= 0 or src_h <= 0 or frame_w <= 0 or frame_h <= 0:
        return None
    scaled = np.array(points, dtype=np.float32)
    scaled[:, 0] *= float(frame_w) / float(src_w)
    scaled[:, 1] *= float(frame_h) / float(src_h)
    return scaled


def _dashboard_channel_crop_polygon(
    saved: Dict[str, Any],
    polygon_key: str,
    polygons_table: Dict[str, Any],
    frame_w: int,
    frame_h: int,
) -> np.ndarray | None:
    angle_key = angleKeyForPolygonKey(polygon_key)
    if angle_key is not None:
        try:
            from subsystems.feeder.analysis import channelArcCropPolygon, parseSavedChannelArcZones

            arc = parseSavedChannelArcZones(
                angle_key,
                saved.get("channel_angles") if isinstance(saved.get("channel_angles"), dict) else {},
                saved.get("arc_params") if isinstance(saved.get("arc_params"), dict) else {},
            )
            if arc is not None and arc.outer_radius > arc.inner_radius > 0:
                # Match what the live region overlay does (handdrawn_region_provider
                # ._scaledChannelMask): scale the center separately for x/y so it
                # tracks the frame, but apply a *uniform* radius_scale so the arc
                # stays a true circle. Building the polygon and then squashing
                # x/y independently produces an oval crop that doesn't match the
                # zone the operator drew.
                src_w, src_h = _dashboard_channel_resolution(saved, polygon_key)
                if src_w > 0 and src_h > 0 and frame_w > 0 and frame_h > 0:
                    sx = float(frame_w) / float(src_w)
                    sy = float(frame_h) / float(src_h)
                    cx = arc.center[0] * sx
                    cy = arc.center[1] * sy
                    r_scale = (sx + sy) / 2.0
                    polygon = channelArcCropPolygon(
                        arc, center=(cx, cy), radius_scale=r_scale
                    )
                    return polygon.astype(np.float32)
        except Exception:
            pass
    # Fallback: scale a manually drawn polygon from saved resolution to frame.
    points = _dashboard_points(polygons_table.get(polygon_key))
    return _scale_dashboard_points(
        points,
        _dashboard_channel_resolution(saved, polygon_key),
        frame_w,
        frame_h,
    )


def dashboard_crop_spec(role: str, frame_w: int, frame_h: int) -> Dict[str, Any] | None:
    """How to crop a ``frame_w`` x ``frame_h`` frame of ``role``'s camera, or
    None when the role has no channel zone."""
    polygon_key = polygonKeyForRole(role)
    if polygon_key is None:
        return None
    saved = get_channel_polygons() or {}
    polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
    scaled_polygon = _dashboard_channel_crop_polygon(saved, polygon_key, polygons_table, frame_w, frame_h)
    if scaled_polygon is None:
        return None
    return {
        "kind": "bbox_masked",
        "polygons": [scaled_polygon],
        "rotation_deg": alignmentRotationDeg(dropStartAngleForRole(role, saved)),
    }
