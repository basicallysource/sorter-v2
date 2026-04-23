"""Shared polygon-crop helper.

Given a frame and a list of polygon vertices, return the bounding-box crop
of the frame with pixels outside the polygon zeroed out. Both the runtime
perception detector (rt/perception/detectors/hive_onnx.py) and the
dashboard stream preview (server/routers/cameras.py) call this so the
"cropped" stream view is pixel-identical to what the detector sees.
"""

from __future__ import annotations

from typing import Sequence

import cv2
import numpy as np


def polygon_bbox(
    vertices: Sequence[tuple[float, float]],
    frame_w: int,
    frame_h: int,
) -> tuple[int, int, int, int] | None:
    """Return ``(x1, y1, x2, y2)`` bbox clipped to the frame, or ``None``."""
    if not vertices:
        return None
    xs = [int(v[0]) for v in vertices]
    ys = [int(v[1]) for v in vertices]
    x1 = max(0, min(xs))
    y1 = max(0, min(ys))
    x2 = min(int(frame_w), max(xs))
    y2 = min(int(frame_h), max(ys))
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def apply_polygon_crop(
    frame: np.ndarray,
    vertices: Sequence[tuple[float, float]],
) -> tuple[np.ndarray | None, tuple[int, int]]:
    """Crop ``frame`` to the polygon's bbox and zero out pixels outside it.

    Returns ``(masked_crop, (offset_x, offset_y))``. ``masked_crop`` is
    ``None`` when the polygon has fewer than 3 vertices or the clipped
    bbox is empty.
    """
    if len(vertices) < 3:
        return None, (0, 0)
    h, w = frame.shape[:2]
    bbox = polygon_bbox(vertices, w, h)
    if bbox is None:
        return None, (0, 0)
    x1, y1, x2, y2 = bbox
    crop = np.ascontiguousarray(frame[y1:y2, x1:x2])
    points = np.array(
        [[int(px) - x1, int(py) - y1] for (px, py) in vertices],
        dtype=np.int32,
    )
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    cv2.fillPoly(mask, [points], 255)
    masked = cv2.bitwise_and(crop, crop, mask=mask)
    return np.ascontiguousarray(masked), (x1, y1)


def apply_polygons_crop(
    frame: np.ndarray,
    polygons: Sequence[Sequence[tuple[float, float]]],
) -> tuple[np.ndarray | None, tuple[int, int]]:
    """Same as :func:`apply_polygon_crop` but for multiple polygons.

    Each polygon masks in its own pixels; everything outside all polygons
    is zeroed. Bounding box is the union of all polygons. Used by the
    combined feeder dashboard stream that overlays c2/c3/carousel
    polygons in one view.
    """
    valid = [p for p in polygons if len(p) >= 3]
    if not valid:
        return None, (0, 0)
    h, w = frame.shape[:2]
    xs: list[int] = []
    ys: list[int] = []
    for poly in valid:
        for v in poly:
            xs.append(int(v[0]))
            ys.append(int(v[1]))
    if not xs or not ys:
        return None, (0, 0)
    x1 = max(0, min(xs))
    y1 = max(0, min(ys))
    x2 = min(int(w), max(xs))
    y2 = min(int(h), max(ys))
    if x2 <= x1 or y2 <= y1:
        return None, (0, 0)
    crop = np.ascontiguousarray(frame[y1:y2, x1:x2])
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    for poly in valid:
        points = np.array(
            [[int(px) - x1, int(py) - y1] for (px, py) in poly],
            dtype=np.int32,
        )
        cv2.fillPoly(mask, [points], 255)
    masked = cv2.bitwise_and(crop, crop, mask=mask)
    return np.ascontiguousarray(masked), (x1, y1)


__all__ = ["polygon_bbox", "apply_polygon_crop", "apply_polygons_crop"]
