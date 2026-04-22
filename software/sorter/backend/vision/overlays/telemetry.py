"""Bottom-right telemetry overlay — resolution / fps / exposure / gain
for each camera feed. Purely informational; the operator glances at it
to see what the camera is actually doing right now.

Exposure values are shown both as the raw UVC control value and as the
human-readable shutter speed using the UVC 100-µs convention
(exposure_absolute × 100 µs = shutter time in seconds). This also covers
the Insta360 Link 2 Extension-Unit exposure, which empirically uses the
same 100-µs scale.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

import cv2
import numpy as np


# Bottom-right layout — baseline values calibrated for 1280x720 frames.
# Scale up proportionally at higher resolutions so the overlay stays legible
# on a 4K feed without blowing up on the 1280x720 feeds.
_BASELINE_WIDTH = 1280
_PAD_PX = 8
_LINE_HEIGHT_PX = 18
_FONT = cv2.FONT_HERSHEY_SIMPLEX
_FONT_SCALE = 0.45
_FONT_THICKNESS = 1
_BG_COLOR = (0, 0, 0)         # BGR
_BG_ALPHA = 0.55
_TEXT_COLOR = (230, 230, 230)  # near-white
_KEY_COLOR = (170, 170, 170)   # dimmer for labels


def _format_shutter(exposure_value: float | int | None) -> str | None:
    """Render a UVC 100-µs exposure value as 1/N s (or X s for long).

    Returns None when the value is missing or non-positive.
    """
    if exposure_value is None:
        return None
    try:
        val = float(exposure_value)
    except Exception:
        return None
    if val <= 0:
        return None
    seconds = val * 100e-6
    if seconds <= 0:
        return None
    if seconds < 1.0:
        denom = int(round(1.0 / seconds))
        if denom <= 0:
            return None
        return f"1/{denom}s"
    return f"{seconds:.2f}s"


class TelemetryOverlay:
    """Render camera runtime stats in the bottom-right corner.

    Stats come from a caller-supplied ``get_stats`` closure that returns a
    mapping with any subset of the keys below. Missing keys are simply
    omitted from the output — the overlay shrinks to fit.

      resolution      e.g. "1920x1080"       (tuple or string)
      fps             e.g. 25                 (numeric)
      exposure        raw exposure_absolute  (numeric, 100-µs units)
      gain            raw gain               (numeric)
      focus           raw focus_absolute     (numeric)
      wb              raw white_balance_temp (numeric, Kelvin)
      auto_exposure   bool
      auto_wb         bool
    """

    category = "telemetry"

    def __init__(self, get_stats: Callable[[], Mapping[str, Any] | None]) -> None:
        self._get_stats = get_stats

    def annotate(self, frame: np.ndarray) -> np.ndarray:
        stats = self._get_stats() or {}
        lines = list(self._render_lines(stats))
        if not lines:
            return frame
        self._draw(frame, lines)
        return frame

    @staticmethod
    def _render_lines(stats: Mapping[str, Any]) -> list[tuple[str, str]]:
        rendered: list[tuple[str, str]] = []

        res = stats.get("resolution")
        if isinstance(res, (tuple, list)) and len(res) == 2:
            rendered.append(("res", f"{int(res[0])}x{int(res[1])}"))
        elif isinstance(res, str) and res:
            rendered.append(("res", res))

        fps = stats.get("fps")
        if isinstance(fps, (int, float)) and fps > 0:
            rendered.append(("fps", f"{float(fps):.0f}"))

        exposure = stats.get("exposure")
        if exposure is not None:
            shutter = _format_shutter(exposure)
            if shutter:
                rendered.append(("exp", f"{int(float(exposure))}  ({shutter})"))
            else:
                rendered.append(("exp", f"{int(float(exposure))}"))

        gain = stats.get("gain")
        if isinstance(gain, (int, float)) and gain > 0:
            rendered.append(("gain", f"{int(gain)}"))

        wb = stats.get("wb")
        if isinstance(wb, (int, float)) and wb > 0:
            rendered.append(("wb", f"{int(wb)}K"))

        focus = stats.get("focus")
        if isinstance(focus, (int, float)) and focus >= 0:
            rendered.append(("focus", f"{int(focus)}"))

        ae = stats.get("auto_exposure")
        awb = stats.get("auto_wb")
        flags: list[str] = []
        if isinstance(ae, bool):
            flags.append("AE" if ae else "m-exp")
        if isinstance(awb, bool):
            flags.append("AWB" if awb else "m-wb")
        if flags:
            rendered.append(("mode", " · ".join(flags)))

        return rendered

    @staticmethod
    def _draw(frame: np.ndarray, lines: list[tuple[str, str]]) -> None:
        h, w = frame.shape[:2]

        scale = max(1.0, float(w) / float(_BASELINE_WIDTH))
        pad_px = max(1, int(round(_PAD_PX * scale)))
        line_height_px = max(1, int(round(_LINE_HEIGHT_PX * scale)))
        font_scale = _FONT_SCALE * scale
        font_thickness = max(1, int(round(_FONT_THICKNESS * scale)))

        # Measure widest line first to size the background plate.
        widths: list[int] = []
        for key, val in lines:
            text = f"{key}: {val}"
            (tw, _), _ = cv2.getTextSize(text, _FONT, font_scale, font_thickness)
            widths.append(tw)
        text_w = max(widths) if widths else 0
        text_h = len(lines) * line_height_px

        box_x2 = w - pad_px
        box_y2 = h - pad_px
        box_x1 = box_x2 - text_w - 2 * pad_px
        box_y1 = box_y2 - text_h - pad_px
        if box_x1 < 0 or box_y1 < 0:
            return

        # Translucent background: blend a filled rectangle over a copy.
        overlay = frame.copy()
        cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), _BG_COLOR, thickness=-1)
        cv2.addWeighted(overlay, _BG_ALPHA, frame, 1.0 - _BG_ALPHA, 0, frame)

        # Lines, drawn bottom-up from baseline.
        baseline_drop = max(2, int(round(5 * scale)))
        for i, (key, val) in enumerate(lines):
            y = box_y1 + pad_px // 2 + (i + 1) * line_height_px - baseline_drop
            x = box_x1 + pad_px
            cv2.putText(
                frame, f"{key}:", (x, y), _FONT, font_scale, _KEY_COLOR,
                font_thickness, cv2.LINE_AA,
            )
            (kw, _), _ = cv2.getTextSize(f"{key}: ", _FONT, font_scale, font_thickness)
            cv2.putText(
                frame, val, (x + kw, y), _FONT, font_scale, _TEXT_COLOR,
                font_thickness, cv2.LINE_AA,
            )
