"""Pure geometry helpers shared by tracker adapters.

Factored out of `polar.py` and `roboflow.py` so
three copies of the same angle/bbox math don't drift apart.

No state, no imports from rt — safe to reuse anywhere in the perception layer.
"""

from __future__ import annotations

import math
from typing import Iterable


def wrap_angle(angle: float) -> float:
    """Wrap an angle in radians into ``(-pi, pi]``."""

    return (float(angle) + math.pi) % (2.0 * math.pi) - math.pi


def circular_diff(a: float, b: float) -> float:
    """Return the shortest signed circular difference ``a - b`` in radians."""

    return wrap_angle(float(a) - float(b))


def bbox_center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0


def bbox_iou(
    a: tuple[int, int, int, int],
    b: tuple[int, int, int, int],
) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = float(iw * ih)
    if inter <= 0.0:
        return 0.0
    area_a = float(max(0, ax2 - ax1) * max(0, ay2 - ay1))
    area_b = float(max(0, bx2 - bx1) * max(0, by2 - by1))
    denom = area_a + area_b - inter
    return inter / denom if denom > 0.0 else 0.0


def clip_bbox(values: Iterable[float]) -> tuple[int, int, int, int]:
    raw = [float(v) for v in values]
    if len(raw) != 4:
        return (0, 0, 0, 0)
    x1, y1, x2, y2 = raw
    if not all(math.isfinite(v) for v in raw):
        return (0, 0, 0, 0)
    x1_i = int(round(min(x1, x2)))
    y1_i = int(round(min(y1, y2)))
    x2_i = int(round(max(x1, x2)))
    y2_i = int(round(max(y1, y2)))
    return (x1_i, y1_i, x2_i, y2_i)


__all__ = [
    "bbox_center",
    "bbox_iou",
    "circular_diff",
    "clip_bbox",
    "wrap_angle",
]
