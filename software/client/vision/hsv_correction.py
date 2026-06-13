"""Optional post-capture HSV correction shared by the classification baseline
calibration script and the runtime detection pipeline.

Both the envelope captured at calibration time and the frames compared against
it at runtime must go through the *same* transform, so the load/apply helpers
live here and are imported by both sides. If no correction file exists the
helpers are strict no-ops, which makes adding a correction pass later purely
additive: nothing breaks if the file is absent.

Correction form (operates on an OpenCV 8-bit HSV image, H in 0-179, S/V 0-255):

    h = (h + h_offset) % 180          # hue wraps
    s = clip(s * s_scale + s_offset, 0, 255)
    v = clip(v * v_scale + v_offset, 0, 255)

The JSON file (calibration/hsv_correction.json) may specify any subset of the
keys below; missing keys default to the identity (offset 0, scale 1).
"""

import json
from pathlib import Path
from typing import Optional

import numpy as np

# The classification background (magenta floor) sits near OpenCV's 8-bit hue
# 0/180 wrap (~H160-178). Naive min/max envelopes AND INTER_AREA downscaling
# both break across that seam (a pixel oscillating 178<->1 stores a [0,178]
# envelope that swallows everything). We rotate all hue by this constant so the
# background lands mid-range (~H90), far from the wrap, making the entire linear
# pipeline -- min/max envelope, 0.25 downscale, arc distance -- correct with no
# special wrap handling. Applied identically in calibration and at runtime, so
# the stored envelope and live frames share the rotated hue space. Detection is
# unaffected: hue *distances* are rotation-invariant. If the background color
# ever changes substantially, re-center it (target ~H90) and re-baseline.
HUE_ROTATION = 105  # H165 + 105 = 270 % 180 = 90


def rotateHue(hsv: np.ndarray) -> np.ndarray:
    """Rotate the hue channel of an 8-bit HSV image by HUE_ROTATION (mod 180) so
    the magenta background moves off the 0/180 wrap. Returns a new array."""
    out = hsv.copy()
    out[:, :, 0] = ((hsv[:, :, 0].astype(np.int16) + HUE_ROTATION) % 180).astype(np.uint8)
    return out

# calibration/hsv_correction.json, alongside the other calibration artifacts.
HSV_CORRECTION_PATH = (
    Path(__file__).resolve().parent.parent / "calibration" / "hsv_correction.json"
)

_IDENTITY = {
    "h_offset": 0.0,
    "s_offset": 0.0,
    "s_scale": 1.0,
    "v_offset": 0.0,
    "v_scale": 1.0,
}


def loadHsvCorrection(path: Optional[Path] = None) -> Optional[dict]:
    """Load HSV correction parameters, or None if no file exists / it is empty.

    A None return means "no correction" and callers should treat the transform
    as a no-op. A dict return is fully populated with identity defaults for any
    keys the file omitted.
    """
    p = path or HSV_CORRECTION_PATH
    if not p.exists():
        return None
    try:
        with open(p) as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(raw, dict) or not raw:
        return None
    corr = dict(_IDENTITY)
    for k in _IDENTITY:
        if k in raw:
            try:
                corr[k] = float(raw[k])
            except (TypeError, ValueError):
                pass
    return corr


def isNoop(corr: Optional[dict]) -> bool:
    """True if the correction is absent or equal to the identity transform."""
    if corr is None:
        return True
    return (
        corr["h_offset"] == 0.0
        and corr["s_offset"] == 0.0
        and corr["s_scale"] == 1.0
        and corr["v_offset"] == 0.0
        and corr["v_scale"] == 1.0
    )


def applyHsvCorrection(hsv: np.ndarray, corr: Optional[dict]) -> np.ndarray:
    """Apply the correction to an 8-bit HSV image. No-op (returns input) when
    corr is None or the identity. Hue wraps mod 180; S/V are scaled+offset then
    clipped to 0-255. Computation is done in float to avoid uint8 overflow."""
    if isNoop(corr):
        return hsv

    h = hsv[:, :, 0].astype(np.float32)
    s = hsv[:, :, 1].astype(np.float32)
    v = hsv[:, :, 2].astype(np.float32)

    h = np.mod(h + corr["h_offset"], 180.0)
    s = np.clip(s * corr["s_scale"] + corr["s_offset"], 0, 255)
    v = np.clip(v * corr["v_scale"] + corr["v_offset"], 0, 255)

    out = hsv.copy()
    out[:, :, 0] = h.astype(np.uint8)
    out[:, :, 1] = s.astype(np.uint8)
    out[:, :, 2] = v.astype(np.uint8)
    return out
