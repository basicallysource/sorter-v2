"""Target-plate smart camera calibration (USB + Android variants).

This is the original "target_plate" strategy — no LLM, no histogram
loop. The two provider-specific entry points share a goal: capture
multiple frames at different exposures, score each by 6-colour target
detection, and return the best-scoring settings plus a color-plate
analysis dict that the caller turns into a CCM.

**USB path** (``calibrate_usb_camera_device_settings``) uses OpenCV's
Debevec calibration to estimate the camera response curve from a
7-frame exposure bracket, solves for the optimal exposure directly, and
then neutralises the firmware color controls before running the target
detector. Falls back to a coarse binary search on p99 luma if Debevec
fails.

**Android path** (``calibrate_android_camera_device_settings``) has no
direct sensor control — it grid-searches ``exposure_compensation`` and
``white_balance_mode`` through the camera-app JSON bridge and picks the
best-scoring candidate, then optionally polishes with AE/AWB locks.

Both flows depend on router-local helpers (live preview push, frame
capture, candidate analysis) because those still need the
``preview_camera_device_settings`` endpoint and the Android HTTP
bridge. They are injected as keyword-only ``Callable`` parameters; the
service stays router-agnostic.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List

import cv2
import numpy as np
from fastapi import HTTPException

from server.camera_calibration import analyze_color_plate_target
from server.services.camera_calibration.common import (
    as_number,
    calibration_selection_value,
    capture_raw_frame,
    clamp_control,
)


PreviewSettings = Callable[[str, Dict[str, Any]], Any]
CaptureFrameForCalibration = Callable[..., np.ndarray | None]
AnalyzeFrame = Callable[
    [str, int | str | None, Dict[str, Any]],
    tuple[Dict[str, Any], Dict[str, Any] | None, np.ndarray | None],
]
ReportProgress = Callable[[str, float, str, Dict[str, Any] | None], None]


def _usb_control_defaults(
    controls: List[Dict[str, Any]],
    current_settings: Dict[str, int | float | bool],
) -> Dict[str, int | float | bool]:
    defaults: Dict[str, int | float | bool] = {}
    for control in controls:
        key = control.get("key")
        if not isinstance(key, str):
            continue
        default = control.get("default")
        if isinstance(default, (int, float, bool)) and not isinstance(default, bool):
            defaults[key] = float(default) if isinstance(default, float) or isinstance(default, int) else default
            continue
        if isinstance(default, bool):
            defaults[key] = default
            continue
        if key in {"auto_exposure", "auto_white_balance", "autofocus"} and isinstance(control.get("kind"), str):
            defaults[key] = True
            continue
        if key in current_settings:
            defaults[key] = current_settings[key]
            continue
        value = control.get("value")
        if isinstance(value, bool):
            defaults[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            defaults[key] = float(value)
    return defaults


def calibrate_usb_camera_device_settings(
    role: str,
    source: int,
    controls: List[Dict[str, Any]],
    current_settings: Dict[str, int | float | bool],
    *,
    preview_settings: PreviewSettings,
    capture_frame: CaptureFrameForCalibration,
    report_progress: ReportProgress | None = None,
    gallery_dir: Path | None = None,
) -> tuple[Dict[str, int | float | bool], Dict[str, Any], Dict[str, Any] | None]:
    """Returns (best_settings, analysis_dict, response_curve_data_or_None)."""
    control_by_key = {
        str(control.get("key")): control
        for control in controls
        if isinstance(control, dict) and isinstance(control.get("key"), str)
    }

    exposure_control = control_by_key.get("exposure")
    gain_control = control_by_key.get("gain")
    wb_control = control_by_key.get("white_balance_temperature")
    auto_exposure_control = control_by_key.get("auto_exposure")
    auto_wb_control = control_by_key.get("auto_white_balance")
    saturation_control = control_by_key.get("saturation")
    contrast_control = control_by_key.get("contrast")
    gamma_control = control_by_key.get("gamma")
    brightness_control = control_by_key.get("brightness")
    sharpness_control = control_by_key.get("sharpness")

    defaults = _usb_control_defaults(controls, current_settings)

    # Build baseline: auto off, gain to minimum
    baseline = dict(defaults or current_settings)
    if auto_exposure_control is not None:
        baseline["auto_exposure"] = False
    if auto_wb_control is not None:
        baseline["auto_white_balance"] = False
    if gain_control is not None:
        baseline["gain"] = as_number(gain_control.get("min")) or 0.0

    total_steps = max(1, 7 + 2 + 4)  # bracketing + neutral + detection
    completed_steps = 0
    gallery_step = 0

    def _report(stage: str, message: str, analysis: Dict[str, Any] | None = None) -> None:
        nonlocal completed_steps
        completed_steps += 1
        if report_progress is not None:
            progress = min(0.9, completed_steps / total_steps)
            report_progress(stage, progress, message, analysis)

    def _save_gallery(
        frame: np.ndarray | None,
        stage: str,
        settings: Dict[str, int | float | bool],
        extra: Dict[str, Any] | None = None,
    ) -> None:
        nonlocal gallery_step
        if gallery_dir is None or frame is None:
            return
        gallery_step += 1
        prefix = f"step_{gallery_step:03d}_{stage}"
        cv2.imwrite(str(gallery_dir / f"{prefix}.jpg"), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        meta: Dict[str, Any] = {"stage": stage, "step": gallery_step, "settings": {k: v for k, v in settings.items()}}
        if extra:
            meta.update(extra)
        (gallery_dir / f"{prefix}.json").write_text(json.dumps(meta, indent=2, default=str))

    settings = dict(baseline)

    def _apply_and_grab(s: Dict[str, int | float | bool]) -> np.ndarray | None:
        preview_settings(role, s)
        time.sleep(0.25)
        return capture_raw_frame(role, source, s)

    # ------------------------------------------------------------------
    # Phase 0: Debevec response curve → direct exposure calculation
    # Capture 5-7 frames at log-spaced exposures, estimate the camera
    # response function, compute optimal exposure from the HDR map.
    # ------------------------------------------------------------------

    response_curve_data: Dict[str, Any] | None = None

    if exposure_control is not None:
        exp_min = as_number(exposure_control.get("min")) or 1.0
        exp_max = as_number(exposure_control.get("max")) or 10000.0

        # Generate 7 log-spaced exposure values across the range.
        # UVC exposure_absolute is typically in 0.1ms units (linear);
        # some cameras use log2 scale where min <= 0 — use linear spacing then.
        if exp_min > 0:
            bracket_exposures = np.geomspace(exp_min, exp_max, num=7).tolist()
        else:
            bracket_exposures = np.linspace(exp_min, exp_max, num=7).tolist()

        bracket_exposures = [
            clamp_control(val, exposure_control) for val in bracket_exposures
        ]
        # Deduplicate after quantization
        bracket_exposures = list(dict.fromkeys(bracket_exposures))

        if len(bracket_exposures) >= 3:
            bracket_frames: list[np.ndarray] = []
            bracket_times: list[float] = []

            for i, exp_val in enumerate(bracket_exposures):
                candidate = dict(settings)
                candidate["exposure"] = exp_val
                frame = _apply_and_grab(candidate)
                if frame is not None:
                    bracket_frames.append(frame)
                    # Use exposure value as "time" — ratios are what matter
                    bracket_times.append(max(float(exp_val), 1e-6) if exp_min > 0 else 2.0 ** float(exp_val))
                    _save_gallery(frame, "bracket", candidate, {"exposure": exp_val, "bracket_index": i})
                _report("bracket", f"Bracketing {i + 1}/{len(bracket_exposures)} — exposure={exp_val:.1f}")

            if len(bracket_frames) >= 3:
                times_array = np.array(bracket_times, dtype=np.float32)

                try:
                    calibrate_debevec = cv2.createCalibrateDebevec(samples=50, lambda_=10.0)
                    response = calibrate_debevec.process(bracket_frames, times_array)
                    # response shape: (256, 1, 3) — log exposure for each pixel value per channel

                    merge_debevec = cv2.createMergeDebevec()
                    hdr = merge_debevec.process(bracket_frames, times_array, response)
                    # hdr shape: (H, W, 3) float32 — radiance map

                    # Build linearization LUT from response curve
                    # response[z] = ln(E*t), so linear_value = exp(response[z])
                    response_squeezed = response.squeeze(1)  # (256, 3)
                    lut_linear = np.exp(response_squeezed).astype(np.float32)  # (256, 3)
                    # Normalize each channel to [0, 1]
                    for c in range(3):
                        ch_max = lut_linear[:, c].max()
                        if ch_max > 0:
                            lut_linear[:, c] /= ch_max

                    response_curve_data = {
                        "lut_r": lut_linear[:, 2].tolist(),  # OpenCV is BGR
                        "lut_g": lut_linear[:, 1].tolist(),
                        "lut_b": lut_linear[:, 0].tolist(),
                    }

                    # Calculate optimal exposure from HDR map
                    hdr_gray = cv2.cvtColor(hdr, cv2.COLOR_BGR2GRAY)
                    p99_radiance = float(np.percentile(hdr_gray[hdr_gray > 0], 99))

                    if p99_radiance > 0:
                        # We want p99 to map to pixel value ~235. From the response
                        # curve: find the exposure time where the response function
                        # outputs 235 on the green channel.
                        target_log_exp = float(response_squeezed[235, 1])
                        target_exposure_product = np.exp(target_log_exp)
                        optimal_time = target_exposure_product / p99_radiance

                        # Convert back to UVC exposure units
                        if exp_min > 0:
                            optimal_exposure = optimal_time
                        else:
                            optimal_exposure = np.log2(max(optimal_time, 1e-10))

                        optimal_exposure = clamp_control(float(optimal_exposure), exposure_control)
                        settings["exposure"] = optimal_exposure

                        # Check if gain is needed
                        if gain_control is not None:
                            frame_check = _apply_and_grab(settings)
                            if frame_check is not None:
                                gray = cv2.cvtColor(frame_check, cv2.COLOR_BGR2GRAY)
                                p99_check = float(np.percentile(gray, 99))
                                if p99_check < 180:
                                    # Need gain boost
                                    gain_needed = 235.0 / max(p99_check, 1.0)
                                    gain_min = as_number(gain_control.get("min")) or 0.0
                                    gain_max = as_number(gain_control.get("max")) or 255.0
                                    current_gain = float(settings.get("gain", gain_min))
                                    settings["gain"] = clamp_control(
                                        current_gain + (gain_max - gain_min) * min(gain_needed - 1.0, 1.0) * 0.5,
                                        gain_control,
                                    )

                        _report("bracket", f"Debevec: optimal exposure={optimal_exposure:.1f}")
                    else:
                        _report("bracket", "Debevec: p99 radiance is zero, falling back to mid-range exposure.")
                        settings["exposure"] = clamp_control((exp_min + exp_max) / 2.0, exposure_control)

                except Exception as exc:
                    _report("bracket", f"Debevec failed ({exc}), falling back to binary search.")
                    # Fallback: simple binary search
                    settings["exposure"] = clamp_control((exp_min + exp_max) / 2.0, exposure_control)
                    response_curve_data = None
            else:
                settings["exposure"] = clamp_control((exp_min + exp_max) / 2.0, exposure_control)
        else:
            settings["exposure"] = clamp_control((exp_min + exp_max) / 2.0, exposure_control)

    # Quick verify: capture a frame and check histogram
    verify_frame = _apply_and_grab(settings)
    if verify_frame is not None:
        gray = cv2.cvtColor(verify_frame, cv2.COLOR_BGR2GRAY)
        p1 = float(np.percentile(gray, 1))
        p99 = float(np.percentile(gray, 99))
        _save_gallery(verify_frame, "exposure_verify", settings, {"p1": p1, "p99": p99})
        _report("bracket", f"Exposure verify — p1={p1:.0f} p99={p99:.0f}")

        # If way off, do a quick 4-step binary search correction
        if p99 > 250 or p99 < 180:
            exp_min = as_number(exposure_control.get("min")) or 1.0 if exposure_control else 1.0
            exp_max = as_number(exposure_control.get("max")) or 10000.0 if exposure_control else 10000.0
            low, high = exp_min, exp_max
            for _ in range(4):
                trial = clamp_control((low + high) / 2.0, exposure_control) if exposure_control else (low + high) / 2.0
                settings["exposure"] = trial
                f = _apply_and_grab(settings)
                if f is None:
                    continue
                g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
                p99 = float(np.percentile(g, 99))
                if p99 > 240:
                    high = trial
                elif p99 < 230:
                    low = trial
                else:
                    break

    # ------------------------------------------------------------------
    # Phase 1: Set WB / saturation / gamma / contrast to neutral
    # Only exposure + gain matter at the hardware level — everything else
    # is firmware math that the software CCM can do better with ground truth.
    # ------------------------------------------------------------------

    def _control_neutral(ctrl: Dict[str, Any] | None) -> float | None:
        """Return the neutral/default value for a control, or midpoint if unknown."""
        if ctrl is None:
            return None
        default = ctrl.get("default")
        if isinstance(default, (int, float)) and not isinstance(default, bool):
            return float(default)
        c_min = as_number(ctrl.get("min"))
        c_max = as_number(ctrl.get("max"))
        if c_min is not None and c_max is not None:
            return (c_min + c_max) / 2.0
        return None

    for key, ctrl in [
        ("white_balance_temperature", wb_control),
        ("saturation", saturation_control),
        ("gamma", gamma_control),
        ("contrast", contrast_control),
        ("brightness", brightness_control),
    ]:
        neutral = _control_neutral(ctrl)
        if neutral is not None:
            settings[key] = clamp_control(neutral, ctrl)
    # Sharpening to minimum (adds artifacts)
    if sharpness_control is not None:
        sharpness_min = as_number(sharpness_control.get("min"))
        if sharpness_min is not None:
            settings["sharpness"] = sharpness_min

    # Apply neutral settings so the capture thread picks them up
    _apply_and_grab(settings)
    _report("neutral", "Firmware color controls set to neutral.")
    _save_gallery(None, "neutral_settings", settings, {"note": "firmware color controls set to neutral"})

    # ------------------------------------------------------------------
    # Phase 2: Detect the calibration target
    # With good exposure + neutral tone controls, detection should be
    # reliable. The orchestrator generates the CCM from detected patches
    # afterward.
    # ------------------------------------------------------------------

    _report("detection", "Detecting calibration target.")

    best_settings: Dict[str, int | float | bool] = dict(settings)
    best_analysis: Dict[str, Any] | None = None

    # Capture 3 frames, analyze each, keep best
    for attempt in range(3):
        f = capture_frame(role, source, fallback_settings=settings)
        if f is not None:
            result = analyze_color_plate_target(f)
            if result is not None:
                analysis_dict = result.to_dict()
                if best_analysis is None or calibration_selection_value(analysis_dict) > calibration_selection_value(best_analysis):
                    best_analysis = analysis_dict
                    _save_gallery(f, "detection", settings, {"detected": True, "score": result.score, "attempt": attempt})

    # Fallback: try live grab
    if best_analysis is None:
        frame = _apply_and_grab(settings)
        if frame is not None:
            result = analyze_color_plate_target(frame)
            if result is not None:
                best_analysis = result.to_dict()
                _save_gallery(frame, "detection_live", settings, {"detected": True, "score": result.score})

    if best_analysis is None:
        raise HTTPException(
            status_code=400,
            detail="Calibration target not detected. Make sure the 6-color calibration plate "
            "is fully visible and well lit.",
        )

    _report("detection", "Calibration target detected.", best_analysis)
    return best_settings, best_analysis, response_curve_data


def calibrate_android_camera_device_settings(
    role: str,
    source: str,
    current_settings: Dict[str, Any],
    capabilities: Dict[str, Any],
    *,
    analyze_frame: AnalyzeFrame,
    report_progress: ReportProgress | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    white_balance_modes = [
        str(mode)
        for mode in capabilities.get("white_balance_modes", ["auto"])
        if isinstance(mode, str) and mode
    ] or ["auto"]
    preferred_wb_mode = "auto" if "auto" in white_balance_modes else white_balance_modes[0]
    exposure_min = int(capabilities.get("exposure_compensation_min", 0))
    exposure_max = int(capabilities.get("exposure_compensation_max", 0))
    neutral_exposure = int(max(exposure_min, min(exposure_max, 0)))

    base_settings = {
        "exposure_compensation": neutral_exposure,
        "ae_lock": False,
        "awb_lock": False,
        "white_balance_mode": preferred_wb_mode,
        "processing_mode": str(current_settings.get("processing_mode", "standard")),
    }

    best_settings: Dict[str, int | float | bool] | None = None
    best_analysis: Dict[str, Any] | None = None
    total_steps = 1

    def tick(stage: str, progress: float, message: str, analysis: Dict[str, Any] | None = None) -> None:
        if report_progress is not None:
            report_progress(stage, min(0.9, progress), message, analysis)

    steps_done = 0

    def consider(candidate: Dict[str, Any], *, stage: str, message: str) -> None:
        nonlocal best_settings, best_analysis
        nonlocal steps_done
        steps_done += 1
        tick(stage, steps_done / total_steps, message)
        applied_settings, analysis, _ = analyze_frame(role, source, candidate)
        if analysis is None:
            return
        if best_analysis is None or calibration_selection_value(analysis) > calibration_selection_value(best_analysis):
            best_settings = dict(applied_settings)
            best_analysis = analysis
            tick(stage, steps_done / total_steps, message, analysis)

    exposure_values = sorted(
        {
            exposure_min,
            exposure_max,
            neutral_exposure,
            int(current_settings.get("exposure_compensation", neutral_exposure)),
            *[
                int(round(value))
                for value in np.linspace(exposure_min, exposure_max, num=max(3, min(7, exposure_max - exposure_min + 1))).tolist()
            ],
        }
    )
    total_steps = max(1, 1 + len(exposure_values) + len(white_balance_modes))

    consider(
        base_settings,
        stage="baseline",
        message="Analyzing baseline candidate 1 of 1.",
    )

    for index, exposure_value in enumerate(exposure_values, start=1):
        candidate = dict(base_settings)
        candidate["exposure_compensation"] = int(exposure_value)
        consider(
            candidate,
            stage="exposure_search",
            message=f"Evaluating exposure candidate {index} of {len(exposure_values)}.",
        )

    if best_settings is None or best_analysis is None:
        raise HTTPException(
            status_code=400,
            detail="Calibration target not found. Make sure the 6-color calibration plate is fully visible and not clipped.",
        )

    # Refine exposure: try values around the best with finer steps
    if best_settings is not None and exposure_min != exposure_max:
        best_exp = int(best_settings.get("exposure_compensation", 0))
        refine_values = sorted(
            {
                value
                for value in range(max(exposure_min, best_exp - 2), min(exposure_max, best_exp + 2) + 1)
                if value != best_exp
            }
        )
        total_steps += len(refine_values)
        for index, exp_value in enumerate(refine_values, start=1):
            candidate = dict(best_settings)
            candidate["exposure_compensation"] = int(exp_value)
            candidate["ae_lock"] = False
            candidate["awb_lock"] = False
            consider(
                candidate,
                stage="exposure_refine",
                message=f"Refining exposure candidate {index} of {len(refine_values)}.",
            )

    wb_base = dict(best_settings)
    wb_base["ae_lock"] = False
    wb_base["awb_lock"] = False
    for index, mode in enumerate(white_balance_modes, start=1):
        candidate = dict(wb_base)
        candidate["white_balance_mode"] = mode
        consider(
            candidate,
            stage="white_balance_search",
            message=f"Evaluating white balance candidate {index} of {len(white_balance_modes)}.",
        )

    if best_settings is None or best_analysis is None:
        raise HTTPException(status_code=400, detail="Calibration failed to find usable settings.")

    # Final polish: try the best settings with locks to verify stability
    total_steps += 1
    polish_candidate = dict(best_settings)
    if bool(capabilities.get("supports_ae_lock")):
        polish_candidate["ae_lock"] = True
    if bool(capabilities.get("supports_awb_lock")):
        polish_candidate["awb_lock"] = True
    consider(
        polish_candidate,
        stage="polish_search",
        message="Verifying with exposure and white balance locked.",
    )

    if bool(capabilities.get("supports_ae_lock")):
        best_settings["ae_lock"] = True
    if bool(capabilities.get("supports_awb_lock")):
        best_settings["awb_lock"] = True

    return best_settings, best_analysis


__all__ = [
    "calibrate_android_camera_device_settings",
    "calibrate_usb_camera_device_settings",
]
