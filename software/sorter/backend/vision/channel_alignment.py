"""Channel-aligned rotation utilities.

Rotates per-channel views so the drop-zone start always sits at 12 o'clock
(straight up). This gives us a common "clock face" language across C2, C3,
and C4 — and removes rotational variance from training samples that head to
the Hive.

Angle convention
----------------
``ChannelArcZones`` stores angles in image-coordinate convention:
``[cx + r*cos(a), cy + r*sin(a)]`` with ``y`` pointing down, so angles
*increase visually clockwise*:

    0°   = 3 o'clock (right)
    90°  = 6 o'clock (down)
    180° = 9 o'clock (left)
    270° = 12 o'clock (up)        ← our alignment target

``cv2.getRotationMatrix2D``'s ``angle`` argument is "positive = visually
counter-clockwise" in the same image-coordinate frame. To put a point
currently at ``drop_start_angle`` onto 12 o'clock we need to rotate by
``drop_start_angle - 270`` degrees (normalized to ``[-180, 180]``).
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import cv2
import numpy as np


_POLYGON_KEY_TO_ANGLE_KEY: dict[str, str] = {
    "second_channel": "second",
    "third_channel": "third",
    "classification_channel": "classification_channel",
}


_ROLE_TO_POLYGON_KEY: dict[str, str] = {
    "c_channel_2": "second_channel",
    "c_channel_3": "third_channel",
    "carousel": "classification_channel",
    "classification_channel": "classification_channel",
}


def polygonKeyForRole(role: str) -> str | None:
    return _ROLE_TO_POLYGON_KEY.get(role)


def angleKeyForPolygonKey(polygon_key: str) -> str | None:
    return _POLYGON_KEY_TO_ANGLE_KEY.get(polygon_key)


def dropStartAngleFromArcParams(
    arc_params: Dict[str, Any] | None,
    angle_key: str,
) -> float | None:
    """Read the drop-zone start angle directly from a saved ``arc_params``
    block. Supports both the modern nested ``drop_zone`` schema and the
    legacy flat ``drop_start_angle`` shorthand."""
    if not isinstance(arc_params, dict):
        return None
    raw = arc_params.get(angle_key)
    if not isinstance(raw, dict):
        return None
    drop_zone = raw.get("drop_zone")
    if isinstance(drop_zone, dict):
        for key in ("start_outer_angle", "start_angle"):
            value = drop_zone.get(key)
            if isinstance(value, (int, float)):
                return float(value)
    flat = raw.get("drop_start_angle")
    if isinstance(flat, (int, float)):
        return float(flat)
    return None


def dropStartAngleForRole(
    role: str,
    saved_channel_polygons: Dict[str, Any] | None,
) -> float | None:
    """Look up the drop-zone start angle for a camera role.

    Falls back through ``parseSavedChannelArcZones`` so that operators who
    only configured the legacy section-based drop zone still get rotation.
    Returns ``None`` when no arc-zone configuration exists.
    """
    polygon_key = polygonKeyForRole(role)
    if polygon_key is None:
        return None
    angle_key = angleKeyForPolygonKey(polygon_key)
    if angle_key is None or not isinstance(saved_channel_polygons, dict):
        return None
    arc_params = saved_channel_polygons.get("arc_params")
    direct = dropStartAngleFromArcParams(arc_params, angle_key)
    if direct is not None:
        return direct

    try:
        from subsystems.feeder.analysis import parseSavedChannelArcZones
    except Exception:
        return None
    channel_angles = saved_channel_polygons.get("channel_angles") or {}
    arc_params_dict = arc_params if isinstance(arc_params, dict) else {}
    zones = parseSavedChannelArcZones(angle_key, channel_angles, arc_params_dict)
    if zones is None:
        return None
    return float(zones.drop_start_angle)


def alignmentRotationDeg(drop_start_angle: float | None) -> float:
    """Rotation angle (CCW positive, OpenCV convention) that lands
    ``drop_start_angle`` on 12 o'clock.

    Returns 0.0 when no drop-start angle is available.
    """
    if drop_start_angle is None:
        return 0.0
    rotation = float(drop_start_angle) - 270.0
    rotation = ((rotation + 180.0) % 360.0) - 180.0
    return rotation


def rotationMatrixForImage(
    width: int,
    height: int,
    rotation_deg: float,
) -> tuple[np.ndarray, tuple[int, int]]:
    """Build an affine matrix that rotates an ``(width, height)`` image
    around its center, expanding the canvas so no pixels are clipped.

    Returns ``(matrix, (new_width, new_height))``.
    """
    cx, cy = width / 2.0, height / 2.0
    matrix = cv2.getRotationMatrix2D((cx, cy), rotation_deg, 1.0)
    cos_a = abs(matrix[0, 0])
    sin_a = abs(matrix[0, 1])
    new_w = max(1, int(np.ceil(height * sin_a + width * cos_a)))
    new_h = max(1, int(np.ceil(height * cos_a + width * sin_a)))
    matrix[0, 2] += (new_w / 2.0) - cx
    matrix[1, 2] += (new_h / 2.0) - cy
    return matrix, (new_w, new_h)


def rotateImageBgr(
    image: np.ndarray,
    rotation_deg: float,
    *,
    fill: Tuple[int, int, int] = (230, 230, 230),
) -> np.ndarray:
    """Rotate a BGR (or grayscale) image and return the expanded canvas.

    A rotation magnitude below ~0.01° is returned unchanged so we don't pay
    an interpolation pass for the common "no calibration yet" case.
    """
    if image is None or image.size == 0:
        return image
    if abs(rotation_deg) < 1e-2:
        return image

    h, w = image.shape[:2]
    matrix, (new_w, new_h) = rotationMatrixForImage(w, h, rotation_deg)
    return cv2.warpAffine(
        image,
        matrix,
        (new_w, new_h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=fill,
    )


__all__ = [
    "polygonKeyForRole",
    "angleKeyForPolygonKey",
    "dropStartAngleFromArcParams",
    "dropStartAngleForRole",
    "alignmentRotationDeg",
    "rotationMatrixForImage",
    "rotateImageBgr",
]
