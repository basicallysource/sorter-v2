"""One-click picture calibration against the live (empty) scene.

Locks auto exposure / auto white balance, then drives the camera's manual
controls until the actual scene statistics hit a stable target:

* exposure (plus gain when exposure alone is not enough) via binary search
  until the mean luma of the center ROI lands in the target band without
  highlight clipping;
* white balance temperature until the red and blue channel means match over
  the same ROI (gray-world — assumes the channel/tray is empty so the
  background is the neutral reference; no calibration target required).

The routine is dependency-injected (control specs, a settings setter and a
frame getter) so it is unit-testable without hardware and reusable for every
capture backend that exposes V4L2-style controls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np

# Target band for the mean luma of the ROI (8-bit). The band is intentionally
# wide-ish: convergence beats pixel-perfect, and detection only needs a stable,
# unclipped image.
LUMA_TARGET = 120.0
LUMA_TOLERANCE = 8.0
# Fraction of near-white pixels above which the image counts as clipped even
# when the mean is inside the band (specular highlights on the tray).
CLIP_LEVEL = 250
CLIP_MAX_FRACTION = 0.015
# White balance: stop once |R-B| mean difference (relative to G) drops below
# this.
WB_TOLERANCE = 0.04

_EXPOSURE_KEYS = ("exposure_time_absolute", "exposure_absolute", "exposure")
_GAIN_KEYS = ("gain",)
_WB_TEMP_KEYS = ("white_balance_temperature",)
_AUTO_EXPOSURE_KEYS = ("auto_exposure",)
_AUTO_WB_KEYS = ("white_balance_automatic", "white_balance_temperature_auto", "auto_white_balance")

_MAX_EXPOSURE_STEPS = 10
_MAX_WB_STEPS = 8


@dataclass
class CalibrationReport:
    ok: bool
    reason: Optional[str] = None
    luma: Optional[float] = None
    clip_fraction: Optional[float] = None
    wb_delta: Optional[float] = None
    exposure_steps: int = 0
    wb_steps: int = 0
    settings: Dict[str, int | float | bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "reason": self.reason,
            "luma": round(self.luma, 1) if self.luma is not None else None,
            "clip_fraction": round(self.clip_fraction, 4) if self.clip_fraction is not None else None,
            "wb_delta": round(self.wb_delta, 4) if self.wb_delta is not None else None,
            "exposure_steps": self.exposure_steps,
            "wb_steps": self.wb_steps,
            "settings": dict(self.settings),
        }


def _control_by_key(controls: List[Dict[str, Any]], keys: tuple[str, ...]) -> Optional[Dict[str, Any]]:
    by_key = {c.get("key"): c for c in controls if isinstance(c, dict)}
    for key in keys:
        control = by_key.get(key)
        if control is not None:
            return control
    return None


def measure_roi(frame: np.ndarray) -> tuple[float, float, tuple[float, float, float]]:
    """Return (mean_luma, clip_fraction, (r_mean, g_mean, b_mean)) of the
    center ROI (central 60% of the frame, BGR input)."""
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.2), int(h * 0.8)
    x0, x1 = int(w * 0.2), int(w * 0.8)
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    b = float(roi[..., 0].mean())
    g = float(roi[..., 1].mean())
    r = float(roi[..., 2].mean())
    luma = 0.114 * b + 0.587 * g + 0.299 * r
    luma_plane = 0.114 * roi[..., 0] + 0.587 * roi[..., 1] + 0.299 * roi[..., 2]
    clip_fraction = float((luma_plane >= CLIP_LEVEL).mean())
    return luma, clip_fraction, (r, g, b)


def calibrate_picture(
    *,
    controls: List[Dict[str, Any]],
    apply_settings: Callable[[Dict[str, int | float | bool]], Dict[str, int | float | bool]],
    get_frame: Callable[[], Optional[np.ndarray]],
    settle_s: float = 0.45,
    sleep: Callable[[float], None] = time.sleep,
) -> CalibrationReport:
    """Run the calibration loop. ``apply_settings`` must push the values to the
    live device (V4L2) and return the applied dict; ``get_frame`` must return
    the newest BGR frame or None."""
    report = CalibrationReport(ok=False)
    accumulated: Dict[str, int | float | bool] = {}

    def push(settings: Dict[str, int | float | bool]) -> None:
        accumulated.update(settings)
        apply_settings(settings)
        sleep(settle_s)

    def sample() -> Optional[tuple[float, float, tuple[float, float, float]]]:
        for _ in range(3):
            frame = get_frame()
            if frame is not None and frame.size:
                return measure_roi(frame)
            sleep(0.2)
        return None

    exposure = _control_by_key(controls, _EXPOSURE_KEYS)
    gain = _control_by_key(controls, _GAIN_KEYS)
    wb_temp = _control_by_key(controls, _WB_TEMP_KEYS)
    auto_exposure = _control_by_key(controls, _AUTO_EXPOSURE_KEYS)
    auto_wb = _control_by_key(controls, _AUTO_WB_KEYS)

    if exposure is None:
        report.reason = "Camera exposes no manual exposure control."
        return report

    # 1. Lock the automatics. Order matters: manual exposure first, then the
    #    absolute value — drivers ignore exposure writes while auto is active.
    lock: Dict[str, int | float | bool] = {}
    if auto_exposure is not None:
        lock[str(auto_exposure["key"])] = False
    if auto_wb is not None:
        lock[str(auto_wb["key"])] = False
    if lock:
        push(lock)

    def _bounds(control: Dict[str, Any]) -> tuple[float, float]:
        lo = float(control.get("min", 0))
        hi = float(control.get("max", lo))
        return lo, max(lo, hi)

    # 2. Exposure binary search on the control range; luma responds roughly
    #    monotonically, which is all bisection needs.
    exp_key = str(exposure["key"])
    lo, hi = _bounds(exposure)
    measured = sample()
    if measured is None:
        report.reason = "No frames available from the camera."
        return report

    value = float(accumulated.get(exp_key, exposure.get("value", (lo + hi) / 2) or (lo + hi) / 2))
    for step in range(1, _MAX_EXPOSURE_STEPS + 1):
        report.exposure_steps = step
        push({exp_key: value})
        measured = sample()
        if measured is None:
            report.reason = "Camera stopped delivering frames during calibration."
            return report
        luma, clip, _ = measured
        report.luma, report.clip_fraction = luma, clip
        too_bright = clip > CLIP_MAX_FRACTION or luma > LUMA_TARGET + LUMA_TOLERANCE
        too_dark = not too_bright and luma < LUMA_TARGET - LUMA_TOLERANCE
        if not too_bright and not too_dark:
            break
        if too_bright:
            hi = value
        else:
            lo = value
        next_value = (lo + hi) / 2
        if abs(next_value - value) < max(1.0, float(exposure.get("step", 1) or 1)):
            break  # converged within control resolution
        value = next_value

    luma, clip, _ = measured
    if luma < LUMA_TARGET - LUMA_TOLERANCE and gain is not None:
        # Exposure range exhausted and still dark — raise gain in quarter steps.
        g_key = str(gain["key"])
        g_lo, g_hi = _bounds(gain)
        g_value = float(accumulated.get(g_key, gain.get("value", g_lo) or g_lo))
        for _ in range(4):
            if luma >= LUMA_TARGET - LUMA_TOLERANCE:
                break
            g_value = min(g_hi, g_value + (g_hi - g_lo) * 0.25)
            push({g_key: g_value})
            measured = sample()
            if measured is None:
                break
            luma, clip, _ = measured
            report.luma, report.clip_fraction = luma, clip
            if g_value >= g_hi:
                break

    # 3. White balance: bisect the temperature until R and B means match.
    if wb_temp is not None:
        wb_key = str(wb_temp["key"])
        w_lo, w_hi = _bounds(wb_temp)
        measured = sample()
        if measured is not None:
            for step in range(1, _MAX_WB_STEPS + 1):
                _, _, (r, g, b) = measured
                if g <= 1.0:
                    break
                delta = (r - b) / g
                report.wb_delta = delta
                report.wb_steps = step - 1
                if abs(delta) <= WB_TOLERANCE:
                    break
                # Higher UVC temperature renders warmer (more red): too red →
                # go cooler, too blue → go warmer.
                if delta > 0:
                    w_hi = float(accumulated.get(wb_key, (w_lo + w_hi) / 2))
                else:
                    w_lo = float(accumulated.get(wb_key, (w_lo + w_hi) / 2))
                value = (w_lo + w_hi) / 2
                report.wb_steps = step
                push({wb_key: value})
                measured = sample()
                if measured is None:
                    break

    final = sample()
    if final is not None:
        report.luma, report.clip_fraction, (r, g, b) = final
        if g > 1.0:
            report.wb_delta = (r - b) / g

    in_band = (
        report.luma is not None
        and abs(report.luma - LUMA_TARGET) <= LUMA_TOLERANCE * 1.5
        and (report.clip_fraction or 0.0) <= CLIP_MAX_FRACTION * 1.5
    )
    report.ok = bool(in_band)
    if not report.ok and report.reason is None:
        report.reason = (
            f"Could not reach the target brightness (luma={report.luma:.0f}, "
            f"target {LUMA_TARGET:.0f}±{LUMA_TOLERANCE:.0f}). Check lighting."
            if report.luma is not None
            else "Calibration did not converge."
        )
    report.settings = accumulated
    return report
