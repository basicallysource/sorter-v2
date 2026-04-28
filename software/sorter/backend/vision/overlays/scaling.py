"""Shared sizing helpers for stream overlays.

The dashboard already scales the bottom-right telemetry by output width so
4K feeds stay readable. Reuse the same baseline for detection/track labels
and box strokes so all stream annotations grow together.
"""

from __future__ import annotations

import numpy as np

_BASELINE_WIDTH = 1280


def overlay_scale_for_width(width: int | float) -> float:
    try:
        resolved = float(width)
    except Exception:
        return 1.0
    if resolved <= 0.0:
        return 1.0
    return max(1.0, resolved / float(_BASELINE_WIDTH))


def overlay_scale_for_frame(frame: np.ndarray) -> float:
    try:
        _h, width = frame.shape[:2]
    except Exception:
        return 1.0
    return overlay_scale_for_width(width)


def scaled_px(value: int | float, scale: float, *, minimum: int = 1) -> int:
    return max(int(minimum), int(round(float(value) * float(scale))))
