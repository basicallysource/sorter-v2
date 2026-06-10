"""One-click picture calibration against the live (empty) scene.

Locks auto exposure / auto white balance, then drives the camera's manual
controls until the actual scene statistics hit a stable target:

* exposure (then gain, then gamma when the camera lacks gain) until the mean
  luma of the center ROI lands in the target band without highlight clipping;
* white balance temperature until the red and blue channel means match over
  the same ROI (gray-world — assumes the channel/tray is empty so the
  background is the neutral reference; no calibration target required).

Hard-won field lessons baked in:

* every sample waits for a frame captured AFTER the settings change — at low
  frame rates ``latest_frame`` otherwise still shows the old exposure and the
  search chases ghosts;
* UVC exposure is silently capped by the fixed frame interval (30 fps caps
  ``exposure`` at ~1/30 s no matter how large the control range is) — the
  search detects the ceiling instead of bisecting into dead range;
* a failed run restores the controls it touched, so calibration can never
  leave the camera darker/weirder than it found it.

The routine is dependency-injected (control specs, a settings setter and a
frame getter) so it is unit-testable without hardware.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

# The sorter scenes are dark-background with small bright content (pieces,
# tray highlights) — mean-luma metering is meaningless there. Expose for the
# highlights instead: drive the 99th-percentile luma of the ROI into a high,
# unclipped band.
LUMA_TARGET = 210.0
LUMA_TOLERANCE = 20.0
# Accept band for the final verdict (slightly wider than the search band).
LUMA_ACCEPT_TOLERANCE = LUMA_TOLERANCE * 1.5
CLIP_LEVEL = 250
CLIP_MAX_FRACTION = 0.015
WB_TOLERANCE = 0.05
# Below this highlight level a WB measurement is sensor noise — skip WB
# instead of steering it with garbage.
WB_MIN_LUMA = 80.0

_EXPOSURE_KEYS = ("exposure_time_absolute", "exposure_absolute", "exposure")
_GAIN_KEYS = ("gain",)
_GAMMA_KEYS = ("gamma",)
_WB_TEMP_KEYS = ("white_balance_temperature",)
_AUTO_EXPOSURE_KEYS = ("auto_exposure",)
_AUTO_WB_KEYS = ("white_balance_automatic", "white_balance_temperature_auto", "auto_white_balance")

_MAX_EXPOSURE_STEPS = 12
_MAX_WB_STEPS = 8
_FRESH_FRAME_TIMEOUT_S = 3.0
# Luma must move at least this much when the control value jumps >=1.5x,
# otherwise the control has hit its effective ceiling (frame-rate cap).
_CEILING_LUMA_EPSILON = 3.0

FrameSample = Tuple[np.ndarray, float]  # (BGR frame, wall-clock timestamp)


@dataclass
class CalibrationReport:
    ok: bool
    reason: Optional[str] = None
    luma: Optional[float] = None
    clip_fraction: Optional[float] = None
    wb_delta: Optional[float] = None
    exposure_steps: int = 0
    wb_steps: int = 0
    restored: bool = False
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
            "restored": self.restored,
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
    """Return (highlight_luma, clip_fraction, bright-pixel (r, g, b) means)
    over the center ROI (central 60%, BGR input).

    highlight_luma is the 99th-percentile luma — the exposure target for
    dark-background scenes. The RGB means are computed over the brightest
    ~20% of pixels only, so white balance is steered by the visible content
    instead of the noise floor of the black background."""
    h, w = frame.shape[:2]
    y0, y1 = int(h * 0.2), int(h * 0.8)
    x0, x1 = int(w * 0.2), int(w * 0.8)
    roi = frame[y0:y1, x0:x1].astype(np.float32)
    luma_plane = 0.114 * roi[..., 0] + 0.587 * roi[..., 1] + 0.299 * roi[..., 2]
    highlight = float(np.percentile(luma_plane, 99.0))
    clip_fraction = float((luma_plane >= CLIP_LEVEL).mean())
    bright_cut = float(np.percentile(luma_plane, 80.0))
    mask = luma_plane >= max(bright_cut, 1.0)
    if not mask.any():
        mask = np.ones_like(luma_plane, dtype=bool)
    b = float(roi[..., 0][mask].mean())
    g = float(roi[..., 1][mask].mean())
    r = float(roi[..., 2][mask].mean())
    return highlight, clip_fraction, (r, g, b)


class _Session:
    """Mutable calibration state shared by the search phases."""

    def __init__(
        self,
        controls: List[Dict[str, Any]],
        apply_settings: Callable[[Dict[str, int | float | bool]], Any],
        get_frame: Callable[[], Optional[FrameSample]],
        sleep: Callable[[float], None],
        now: Callable[[], float],
    ) -> None:
        self.controls = controls
        self._apply = apply_settings
        self._get_frame = get_frame
        self._sleep = sleep
        self._now = now
        self.accumulated: Dict[str, int | float | bool] = {}
        self._original: Dict[str, int | float | bool] = {}
        self._last_push_at = 0.0

    def push(self, settings: Dict[str, int | float | bool]) -> None:
        for key in settings:
            if key not in self._original:
                control = _control_by_key(self.controls, (key,))
                value = control.get("value") if isinstance(control, dict) else None
                if isinstance(value, (int, float, bool)):
                    self._original[key] = value
        self.accumulated.update(settings)
        self._apply(settings)
        self._last_push_at = self._now()

    def restore_touched(self) -> bool:
        if not self._original:
            return False
        try:
            self._apply(dict(self._original))
            return True
        except Exception:
            return False

    def sample(self) -> Optional[tuple[float, float, tuple[float, float, float]]]:
        """Measure a frame captured AFTER the last settings push."""
        deadline = self._now() + _FRESH_FRAME_TIMEOUT_S
        while True:
            got = self._get_frame()
            if got is not None:
                frame, ts = got
                if frame is not None and getattr(frame, "size", 0) and ts > self._last_push_at:
                    return measure_roi(frame)
            if self._now() >= deadline:
                return None
            self._sleep(0.1)


def _bounds(control: Dict[str, Any]) -> tuple[float, float]:
    lo = float(control.get("min", 0))
    hi = float(control.get("max", lo))
    return lo, max(lo, hi)


def _search_brightness_control(
    session: _Session,
    control: Dict[str, Any],
    report: CalibrationReport,
    *,
    max_steps: int,
) -> Optional[tuple[float, float, tuple[float, float, float]]]:
    """Walk one numeric control toward the luma target.

    Expand-then-bisect with ceiling detection: grow the value while too dark;
    when a >=1.5x jump moves luma by less than epsilon the control has hit its
    effective ceiling (e.g. exposure capped by the frame interval) and the
    search stops there. Applies the best-seen value at the end.
    """
    key = str(control["key"])
    lo, hi = _bounds(control)
    step_res = max(1.0, float(control.get("step", 1) or 1))

    current = session.accumulated.get(key, control.get("value"))
    value = float(current) if isinstance(current, (int, float)) and not isinstance(current, bool) else (lo + hi) / 2
    value = min(max(value, lo), hi)

    best: tuple[float, float, float, tuple[float, float, float]] | None = None  # (distance, value, luma, rgb)
    prev: tuple[float, float] | None = None  # (value, luma)
    dark_floor, bright_ceil = lo, hi

    measured = None
    for _ in range(max_steps):
        report.exposure_steps += 1
        session.push({key: value})
        measured = session.sample()
        if measured is None:
            report.reason = "Camera stopped delivering frames during calibration."
            return None
        luma, clip, rgb = measured
        report.luma, report.clip_fraction = luma, clip

        too_bright = clip > CLIP_MAX_FRACTION or luma > LUMA_TARGET + LUMA_TOLERANCE
        distance = abs(luma - LUMA_TARGET) + (1000.0 if clip > CLIP_MAX_FRACTION else 0.0)
        if best is None or distance < best[0]:
            best = (distance, value, luma, rgb)

        if not too_bright and luma >= LUMA_TARGET - LUMA_TOLERANCE:
            return measured  # in band

        if too_bright:
            bright_ceil = value
        else:
            # Ceiling detection: a meaningful value jump with no luma response
            # means the control is saturated (e.g. exposure capped by the
            # frame interval) — stop pushing into dead range.
            jump = value - prev[0] if prev is not None else 0.0
            if (
                prev is not None
                and jump >= max(step_res * 4, prev[0] * 0.5)
                and abs(luma - prev[1]) < _CEILING_LUMA_EPSILON
            ):
                break
            dark_floor = value

        prev = (value, luma)
        if bright_ceil < hi:
            next_value = (dark_floor + bright_ceil) / 2  # bisect once bracketed
        else:
            # Expand aggressively; the range-based floor keeps a start at 0
            # from crawling in +1 steps.
            next_value = min(hi, max(value * 3.0, value + (hi - lo) * 0.1, value + step_res))
        if abs(next_value - value) < step_res:
            break
        value = next_value

    if best is not None and abs(best[1] - value) >= step_res:
        session.push({key: best[1]})
        confirmed = session.sample()
        if confirmed is not None:
            measured = confirmed
            report.luma, report.clip_fraction = confirmed[0], confirmed[1]
    return measured


def calibrate_picture(
    *,
    controls: List[Dict[str, Any]],
    apply_settings: Callable[[Dict[str, int | float | bool]], Any],
    get_frame: Callable[[], Optional[FrameSample]],
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.time,
) -> CalibrationReport:
    """Run the calibration. ``get_frame`` must return ``(bgr_frame, wall_ts)``
    of the newest frame, or None. ``apply_settings`` pushes values to the live
    device. A run that does not reach the target restores every control it
    touched."""
    report = CalibrationReport(ok=False)
    session = _Session(controls, apply_settings, get_frame, sleep, now)

    exposure = _control_by_key(controls, _EXPOSURE_KEYS)
    if exposure is None:
        report.reason = "Camera exposes no manual exposure control."
        return report

    # 1. Lock the automatics first — drivers ignore manual exposure writes
    #    while auto is active.
    lock: Dict[str, int | float | bool] = {}
    auto_exposure = _control_by_key(controls, _AUTO_EXPOSURE_KEYS)
    auto_wb = _control_by_key(controls, _AUTO_WB_KEYS)
    if auto_exposure is not None:
        lock[str(auto_exposure["key"])] = False
    if auto_wb is not None:
        lock[str(auto_wb["key"])] = False
    if lock:
        session.push(lock)
    if session.sample() is None:
        report.reason = "No frames available from the camera."
        return report

    # 2. Brightness: exposure → gain → gamma until the target band is hit or
    #    every lever is exhausted. The fallbacks work in BOTH directions —
    #    e.g. a sensitive camera can still be too bright at minimum exposure
    #    and needs its gain walked down (the search bisects downward when the
    #    first measurement is too bright).
    def _in_band(m: tuple[float, float, tuple[float, float, float]]) -> bool:
        luma, clip, _ = m
        return (
            LUMA_TARGET - LUMA_TOLERANCE <= luma <= LUMA_TARGET + LUMA_TOLERANCE
            and clip <= CLIP_MAX_FRACTION
        )

    measured = _search_brightness_control(session, exposure, report, max_steps=_MAX_EXPOSURE_STEPS)
    for fallback_keys in (_GAIN_KEYS, _GAMMA_KEYS):
        if measured is None or _in_band(measured):
            break
        fallback = _control_by_key(controls, fallback_keys)
        if fallback is None:
            continue
        measured = _search_brightness_control(session, fallback, report, max_steps=6)

    if measured is None:
        report.restored = session.restore_touched()
        if report.reason is None:
            report.reason = "Calibration did not converge."
        return report

    # 3. White balance via gray-world, only on a usably bright image.
    wb_temp = _control_by_key(controls, _WB_TEMP_KEYS)
    if wb_temp is not None and measured[0] >= WB_MIN_LUMA:
        wb_key = str(wb_temp["key"])
        w_lo, w_hi = _bounds(wb_temp)
        wb_step = max(1.0, float(wb_temp.get("step", 1) or 1))
        current_temp = session.accumulated.get(wb_key, wb_temp.get("value"))
        temp = (
            float(current_temp)
            if isinstance(current_temp, (int, float)) and not isinstance(current_temp, bool)
            else (w_lo + w_hi) / 2
        )
        for step in range(1, _MAX_WB_STEPS + 1):
            _, _, (r, g, b) = measured
            if g <= 1.0:
                break
            delta = (r - b) / g
            report.wb_delta = delta
            if abs(delta) <= WB_TOLERANCE:
                break
            report.wb_steps = step
            # Higher UVC temperature renders warmer (more red): too red → cooler.
            if delta > 0:
                w_hi = temp
            else:
                w_lo = temp
            next_temp = (w_lo + w_hi) / 2
            if abs(next_temp - temp) < wb_step:
                break
            temp = next_temp
            session.push({wb_key: temp})
            next_measure = session.sample()
            if next_measure is None:
                break
            measured = next_measure
            report.luma, report.clip_fraction = measured[0], measured[1]

    luma, clip, (r, g, b) = measured
    report.luma, report.clip_fraction = luma, clip
    if g > 1.0:
        report.wb_delta = (r - b) / g

    report.ok = (
        abs(luma - LUMA_TARGET) <= LUMA_ACCEPT_TOLERANCE and clip <= CLIP_MAX_FRACTION * 1.5
    )
    if report.ok:
        report.settings = dict(session.accumulated)
    else:
        report.restored = session.restore_touched()
        report.reason = (
            f"Could not reach the target brightness (luma={luma:.0f}, target "
            f"{LUMA_TARGET:.0f}±{LUMA_TOLERANCE:.0f}) — exposure/gain/gamma exhausted. "
            "More light on the scene is needed. Camera settings were restored."
        )
    return report
