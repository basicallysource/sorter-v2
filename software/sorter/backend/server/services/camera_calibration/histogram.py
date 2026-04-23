"""Exposure calibration driven by mean-grayscale (luma) histogram.

Simplest of the three calibration strategies: capture a frame, measure
mean grayscale brightness, adjust the ``exposure`` device control
proportionally toward a target luma, settle, re-capture, repeat. No
colour profile, no LLM round-trip, no target plate — just "make the
scene middle-gray".

Converges in 4-8 iterations on typical classification-chamber scenes.
Uses a proportional controller with a per-step safety bound so a single
bad frame can't spike exposure off the control's range.

The flow needs two frame-IO primitives that today live on the router
(because they reach into the Android-camera HTTP helpers and the
``preview_camera_device_settings`` endpoint). They are injected as
callables rather than imported — the service stays decoupled from the
router and its tests can substitute trivial fakes.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List

import cv2
import numpy as np
from fastapi import HTTPException

from server.services.camera_calibration.common import (
    CALIBRATION_METHOD_EXPOSURE_HISTOGRAM,
)


EXPOSURE_HISTOGRAM_TARGET_LUMA = 128.0
EXPOSURE_HISTOGRAM_TOLERANCE_LUMA = 3.0
EXPOSURE_HISTOGRAM_MAX_ITERATIONS = 20
EXPOSURE_HISTOGRAM_P_GAIN = 1.4


AnalyzeFrame = Callable[
    [str, int | str | None, Dict[str, Any]],
    tuple[Dict[str, Any], Dict[str, Any] | None, np.ndarray | None],
]
CaptureFrame = Callable[..., np.ndarray | None]
ReportProgress = Callable[[str, float, str, Dict[str, Any] | None], None]


def calibrate_exposure_via_histogram(
    role: str,
    source: int | str | None,
    controls: List[Dict[str, Any]],
    current_settings: Dict[str, int | float | bool],
    *,
    analyze_frame: AnalyzeFrame,
    capture_frame: CaptureFrame,
    report_progress: ReportProgress | None = None,
    gallery_dir: Path | None = None,
    target_luma: float = EXPOSURE_HISTOGRAM_TARGET_LUMA,
    tolerance: float = EXPOSURE_HISTOGRAM_TOLERANCE_LUMA,
    max_iterations: int = EXPOSURE_HISTOGRAM_MAX_ITERATIONS,
) -> tuple[Dict[str, int | float | bool], Dict[str, Any]]:
    """Proportional-gain exposure calibration driven by frame-luma histogram.

    Captures a frame, measures mean grayscale brightness, adjusts the
    ``exposure`` device control proportionally toward ``target_luma``
    (default 128 = middle gray), settles, captures again, repeats.
    Returns the winning settings + an analysis dict for the calling task
    to attach to the progress report.
    """

    if not isinstance(controls, list):
        raise HTTPException(
            status_code=400,
            detail="Camera controls are not available for exposure calibration.",
        )

    exposure_spec: Dict[str, Any] | None = None
    for ctrl in controls:
        if isinstance(ctrl, dict) and ctrl.get("key") == "exposure":
            exposure_spec = ctrl
            break
    if exposure_spec is None:
        raise HTTPException(
            status_code=400,
            detail="This camera does not expose a manual exposure control we can drive.",
        )

    exposure_min = float(exposure_spec.get("min") or 1)
    exposure_max = float(exposure_spec.get("max") or 20000)
    exposure_step = max(1.0, float(exposure_spec.get("step") or 1))
    current_exposure = float(current_settings.get("exposure") or exposure_spec.get("value") or exposure_min)
    current_exposure = max(exposure_min, min(exposure_max, current_exposure))

    # Make sure auto_exposure is off before we start poking manual exposure,
    # otherwise the camera may override every write on the very next frame.
    settings = dict(current_settings)
    settings["auto_exposure"] = False
    settings["exposure"] = current_exposure

    if report_progress is not None:
        report_progress(
            "calibrating",
            0.1,
            f"Starting exposure-histogram calibration (target luma ≈ {int(target_luma)}).",
            None,
        )

    trace: list[Dict[str, float]] = []
    best_delta = float("inf")
    best_settings = dict(settings)
    best_luma = 0.0

    for iteration in range(1, max_iterations + 1):
        before = time.time()
        applied, _, frame = analyze_frame(role, source, settings)
        frame_to_use = frame
        if frame_to_use is None:
            frame_to_use = capture_frame(
                role, source, fallback_settings=settings, after_timestamp=before,
            )
        if frame_to_use is None:
            raise HTTPException(
                status_code=500,
                detail="Could not capture a frame for histogram calibration.",
            )

        gray = cv2.cvtColor(frame_to_use, cv2.COLOR_BGR2GRAY) if frame_to_use.ndim == 3 else frame_to_use
        mean_luma = float(np.mean(gray))
        delta = target_luma - mean_luma
        trace.append({
            "iteration": iteration,
            "exposure": float(settings["exposure"]),
            "mean_luma": round(mean_luma, 2),
            "delta": round(delta, 2),
        })

        if gallery_dir is not None:
            try:
                stamp = f"hist_{iteration:02d}_exp{int(settings['exposure'])}_l{int(mean_luma)}.jpg"
                cv2.imwrite(str(gallery_dir / stamp), frame_to_use)
            except Exception:
                pass

        if abs(delta) < best_delta:
            best_delta = abs(delta)
            best_settings = dict(applied) if isinstance(applied, dict) else dict(settings)
            best_settings.setdefault("auto_exposure", False)
            best_luma = mean_luma

        if report_progress is not None:
            progress = 0.1 + 0.78 * (iteration / max_iterations)
            report_progress(
                "calibrating",
                min(0.9, progress),
                (
                    f"Iter {iteration}/{max_iterations}: "
                    f"exposure={int(settings['exposure'])} → luma={mean_luma:.0f} "
                    f"(target {int(target_luma)}, Δ={delta:+.1f})."
                ),
                {"iteration": iteration, "mean_luma": mean_luma, "exposure": settings["exposure"]},
            )

        if abs(delta) <= tolerance:
            break

        # Proportional gain — exposure scales roughly linearly with light
        # at moderate values, so a gain just above 1 gets us to target in
        # a handful of steps without overshoot. Clamped to the control's
        # advertised range.
        ratio = target_luma / max(mean_luma, 1.0)
        ratio = max(0.3, min(3.0, ratio))  # per-step safety bound
        new_exposure = float(settings["exposure"]) * (1.0 + (ratio - 1.0) * EXPOSURE_HISTOGRAM_P_GAIN)
        new_exposure = max(exposure_min, min(exposure_max, new_exposure))
        new_exposure = round(new_exposure / exposure_step) * exposure_step
        if abs(new_exposure - settings["exposure"]) < exposure_step:
            # P-controller wants a move smaller than the control resolution
            # — no further progress possible at this setting.
            break
        settings["exposure"] = int(new_exposure) if float(int(new_exposure)) == new_exposure else new_exposure

    analysis = {
        "method": CALIBRATION_METHOD_EXPOSURE_HISTOGRAM,
        "target_luma": target_luma,
        "final_luma": best_luma,
        "final_delta": best_delta,
        "final_exposure": best_settings.get("exposure"),
        "iterations": len(trace),
        "converged": best_delta <= tolerance,
        "trace": trace,
    }

    if report_progress is not None:
        report_progress(
            "saving",
            0.9,
            (
                f"Converged at exposure={best_settings.get('exposure')} "
                f"(luma {best_luma:.0f}, target {int(target_luma)})."
                if best_delta <= tolerance
                else f"Stopped at exposure={best_settings.get('exposure')} "
                f"(luma {best_luma:.0f}, target {int(target_luma)} — not fully converged)."
            ),
            analysis,
        )

    return best_settings, analysis


__all__ = [
    "EXPOSURE_HISTOGRAM_MAX_ITERATIONS",
    "EXPOSURE_HISTOGRAM_P_GAIN",
    "EXPOSURE_HISTOGRAM_TARGET_LUMA",
    "EXPOSURE_HISTOGRAM_TOLERANCE_LUMA",
    "calibrate_exposure_via_histogram",
]
