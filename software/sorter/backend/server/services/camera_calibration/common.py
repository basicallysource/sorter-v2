"""Shared helpers for the three camera-calibration strategies.

The calibration flows (LLM-guided, exposure-via-histogram, target-plate
smart) all need the same primitive operations:

- frame capture without color profile / picture settings (for raw
  analysis);
- numeric-control quantisation + clamping to each camera's min/step/max
  grid;
- a typed task-state dict stored under
  ``shared_state.camera_calibration_tasks`` so polling endpoints can
  surface progress;
- analysis scoring + summary shaping for frontend status payloads;
- the neutral baseline that resets every ISP control except exposure /
  gain before a guided loop starts;
- scope-label normalisation + calibration-method string normalisation;
- the ``/tmp/calibration-gallery`` directory cleanup that every flow
  uses for debug-frame archival.

Router and strategy modules import from here; nothing in this module
depends on ``server/routers/cameras.py`` or on the router endpoints.
"""

from __future__ import annotations

import platform
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import cv2
import numpy as np

from server import shared_state


# ---------------------------------------------------------------------------
# Calibration method tokens
# ---------------------------------------------------------------------------

CALIBRATION_METHOD_TARGET_PLATE = "target_plate"
CALIBRATION_METHOD_LLM_GUIDED = "llm_guided"
CALIBRATION_METHOD_EXPOSURE_HISTOGRAM = "exposure_histogram"
DEFAULT_CAMERA_CALIBRATION_METHOD = CALIBRATION_METHOD_TARGET_PLATE


def normalize_camera_calibration_method(value: str | None) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == CALIBRATION_METHOD_LLM_GUIDED:
            return CALIBRATION_METHOD_LLM_GUIDED
        if normalized == CALIBRATION_METHOD_EXPOSURE_HISTOGRAM:
            return CALIBRATION_METHOD_EXPOSURE_HISTOGRAM
    return CALIBRATION_METHOD_TARGET_PLATE


# ---------------------------------------------------------------------------
# Numeric control helpers
# ---------------------------------------------------------------------------


def as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def quantize_numeric_value(value: float, min_value: float, step: float | None) -> float:
    if not isinstance(step, (int, float)) or step <= 0:
        return float(value)
    return float(min_value + round((value - min_value) / float(step)) * float(step))


def quantize_control(value: float, control: Dict[str, Any]) -> float:
    """Quantize a value to match a control's min/step grid."""
    c_min = as_number(control.get("min")) or 0.0
    step = as_number(control.get("step"))
    return quantize_numeric_value(value, c_min, step)


def clamp_control(value: float, control: Dict[str, Any]) -> float:
    """Clamp a value to a control's min/max range and quantize."""
    c_min = as_number(control.get("min"))
    c_max = as_number(control.get("max"))
    if c_min is not None:
        value = max(c_min, value)
    if c_max is not None:
        value = min(c_max, value)
    return quantize_control(value, control)


# ---------------------------------------------------------------------------
# Analysis scoring + summary
# ---------------------------------------------------------------------------


def analysis_number(analysis: Dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    if not isinstance(analysis, dict):
        return default
    value = analysis.get(key)
    return float(value) if isinstance(value, (int, float)) else default


def camera_analysis_score(analysis: Dict[str, Any] | None) -> float:
    if not isinstance(analysis, dict):
        return float("-inf")
    value = analysis.get("score")
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def calibration_selection_value(analysis: Dict[str, Any] | None) -> float:
    score = camera_analysis_score(analysis)
    if not isinstance(analysis, dict):
        return score
    tile_samples = analysis.get("tile_samples")
    if not isinstance(tile_samples, dict) or not tile_samples:
        return score

    important_keys = ("white_top", "white_bottom", "red", "yellow")
    important_matches: List[float] = []
    all_matches: List[float] = []
    for key, raw in tile_samples.items():
        if not isinstance(raw, dict):
            continue
        match_value = raw.get("reference_match_percent")
        if not isinstance(match_value, (int, float)):
            continue
        match = float(match_value)
        all_matches.append(match)
        if key in important_keys:
            important_matches.append(match)

    if not important_matches:
        return score

    min_match = min(important_matches)
    avg_match = float(sum(important_matches) / len(important_matches))
    overall_match = float(sum(all_matches) / len(all_matches)) if all_matches else avg_match
    return score * 0.15 + avg_match + min_match * 1.3 + overall_match * 0.25


def camera_calibration_analysis_summary(analysis: Dict[str, Any] | None) -> Dict[str, Any]:
    if not isinstance(analysis, dict):
        return {"target_detected": False}

    tile_samples = analysis.get("tile_samples")
    matches: List[float] = []
    if isinstance(tile_samples, dict):
        for sample in tile_samples.values():
            if isinstance(sample, dict) and isinstance(sample.get("reference_match_percent"), (int, float)):
                matches.append(float(sample["reference_match_percent"]))

    return {
        "target_detected": True,
        "score": float(analysis.get("score", 0.0) or 0.0),
        "reference_color_error_mean": float(analysis.get("reference_color_error_mean", 0.0) or 0.0),
        "white_luma_mean": float(analysis.get("white_luma_mean", 0.0) or 0.0),
        "black_luma_mean": float(analysis.get("black_luma_mean", 0.0) or 0.0),
        "white_balance_cast": float(analysis.get("white_balance_cast", 0.0) or 0.0),
        "color_separation": float(analysis.get("color_separation", 0.0) or 0.0),
        "clipped_white_fraction": float(analysis.get("clipped_white_fraction", 0.0) or 0.0),
        "shadow_black_fraction": float(analysis.get("shadow_black_fraction", 0.0) or 0.0),
        "match_average_percent": round(sum(matches) / len(matches), 2) if matches else None,
        "match_min_percent": round(min(matches), 2) if matches else None,
    }


# ---------------------------------------------------------------------------
# Allowed-controls extraction (for the LLM prompt + the smart-heuristic grid)
# ---------------------------------------------------------------------------


def camera_calibration_allowed_controls(
    provider: str,
    current_response: Dict[str, Any],
) -> Dict[str, Any]:
    if provider == "android-camera-app":
        capabilities = (
            current_response.get("capabilities")
            if isinstance(current_response.get("capabilities"), dict)
            else {}
        )
        settings = current_response.get("settings") if isinstance(current_response.get("settings"), dict) else {}
        white_balance_modes = [
            str(mode)
            for mode in capabilities.get("white_balance_modes", [])
            if isinstance(mode, str) and mode
        ]
        processing_modes = [
            str(mode)
            for mode in capabilities.get("processing_modes", [])
            if isinstance(mode, str) and mode
        ]
        return {
            "exposure_compensation": {
                "kind": "integer",
                "current": int(settings.get("exposure_compensation", 0) or 0),
                "min": int(capabilities.get("exposure_compensation_min", 0) or 0),
                "max": int(capabilities.get("exposure_compensation_max", 0) or 0),
            },
            "white_balance_mode": {
                "kind": "enum",
                "current": str(settings.get("white_balance_mode", "")),
                "allowed": white_balance_modes,
            },
            "processing_mode": {
                "kind": "enum",
                "current": str(settings.get("processing_mode", "")),
                "allowed": processing_modes,
            },
            "ae_lock": {
                "kind": "boolean",
                "current": bool(settings.get("ae_lock")),
                "supported": bool(capabilities.get("supports_ae_lock")),
            },
            "awb_lock": {
                "kind": "boolean",
                "current": bool(settings.get("awb_lock")),
                "supported": bool(capabilities.get("supports_awb_lock")),
            },
        }

    controls = current_response.get("controls")
    if not isinstance(controls, list):
        return {}

    allowed: Dict[str, Any] = {}
    current_settings = current_response.get("settings") if isinstance(current_response.get("settings"), dict) else {}
    for control in controls:
        if not isinstance(control, dict):
            continue
        key = control.get("key")
        kind = control.get("kind")
        if not isinstance(key, str) or kind not in {"boolean", "number"}:
            continue
        entry: Dict[str, Any] = {
            "kind": kind,
            "label": str(control.get("label") or key),
            "current": current_settings.get(key),
        }
        if kind == "number":
            if isinstance(control.get("min"), (int, float)):
                entry["min"] = float(control["min"])
            if isinstance(control.get("max"), (int, float)):
                entry["max"] = float(control["max"])
            if isinstance(control.get("step"), (int, float)):
                entry["step"] = float(control["step"])
            if isinstance(control.get("default"), (int, float)):
                entry["default"] = float(control["default"])
        else:
            if isinstance(control.get("default"), bool):
                entry["default"] = bool(control["default"])
        allowed[key] = entry
    return allowed


# ---------------------------------------------------------------------------
# Neutral baseline (reset ISP, keep exposure/gain)
# ---------------------------------------------------------------------------


# Keys we treat as real-sensor controls and therefore preserve as-is when
# resetting to a neutral baseline before LLM-guided calibration. Everything
# else (saturation, contrast, sharpness, gamma, hue, white balance, …) is
# post-processing on the camera ISP and gets reset to the firmware default
# so the LLM and the downstream CCM see a clean linear-ish signal.
_CALIBRATION_PRESERVE_TOKENS = ("exposure", "gain", "iso")


def is_exposure_or_gain_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _CALIBRATION_PRESERVE_TOKENS)


def compute_calibration_neutral_baseline(
    provider: str,
    current_response: Dict[str, Any],
    current_settings: Dict[str, Any],
) -> tuple[Dict[str, Any], List[str]]:
    """Return ``(baseline_settings, reset_keys)``.

    The baseline keeps exposure/gain controls at their current values
    (those are real sensor parameters) and resets every other control to
    its firmware-stated default. Auto-mode toggles are forced off so they
    don't fight the manual tuning loop.
    """

    baseline = dict(current_settings)
    reset_keys: List[str] = []

    if provider == "android-camera-app":
        # Android camera app: the only meaningful "reset" we can do is to
        # disable AE/AWB locks so the LLM can drive exposure_compensation
        # and white_balance_mode freely. Everything else is provider-managed.
        for key in ("ae_lock", "awb_lock"):
            if baseline.get(key):
                baseline[key] = False
                reset_keys.append(key)
        return baseline, reset_keys

    controls = current_response.get("controls")
    if not isinstance(controls, list):
        return baseline, reset_keys

    for control in controls:
        if not isinstance(control, dict):
            continue
        key = control.get("key")
        if not isinstance(key, str):
            continue

        kind = control.get("kind")
        default = control.get("default")
        previous = baseline.get(key)
        lowered = key.lower()
        new_value: Any | None = None

        # Auto-mode controls are checked FIRST — they often contain "exposure"
        # in the name (e.g. ``auto_exposure``) but we always want them off so
        # they don't fight the manual tuning loop.
        if "auto" in lowered:
            if kind == "boolean":
                new_value = False
            elif isinstance(default, (int, float)):
                # UVC ``auto_exposure`` enum: 1 = manual, 3 = aperture priority.
                # Default is often aperture priority — explicitly pick manual.
                new_value = 1 if lowered == "auto_exposure" else default
        elif is_exposure_or_gain_key(key):
            # Real sensor parameter — leave whatever the user already had.
            continue
        elif default is not None:
            new_value = default

        if new_value is None or new_value == previous:
            continue
        baseline[key] = new_value
        reset_keys.append(key)

    return baseline, reset_keys


# ---------------------------------------------------------------------------
# Calibration task state (stored under shared_state)
# ---------------------------------------------------------------------------


def create_camera_calibration_task(
    role: str,
    provider: str,
    source: int | str | None,
    *,
    method: str = DEFAULT_CAMERA_CALIBRATION_METHOD,
    openrouter_model: str | None = None,
    apply_color_profile: bool = True,
) -> str:
    task_id = uuid4().hex
    task = {
        "task_id": task_id,
        "role": role,
        "provider": provider,
        "source": source,
        "method": method,
        "openrouter_model": openrouter_model,
        "apply_color_profile": bool(apply_color_profile),
        "status": "queued",
        "stage": "queued",
        "message": "Queued camera calibration.",
        "progress": 0.0,
        "result": None,
        "analysis_preview": None,
        "advisor_trace": [],
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with shared_state.camera_calibration_tasks_lock:
        shared_state.camera_calibration_tasks[task_id] = task
    return task_id


def update_camera_calibration_task(task_id: str, **updates: Any) -> None:
    with shared_state.camera_calibration_tasks_lock:
        task = shared_state.camera_calibration_tasks.get(task_id)
        if task is None:
            return
        task.update(updates)
        task["updated_at"] = time.time()


def get_camera_calibration_task(task_id: str) -> Dict[str, Any] | None:
    with shared_state.camera_calibration_tasks_lock:
        task = shared_state.camera_calibration_tasks.get(task_id)
        return dict(task) if task is not None else None


# ---------------------------------------------------------------------------
# Raw frame capture (no color profile / picture settings) for histogram +
# smart flows. Android capture lives in the router as ``_android_camera_*``
# because it needs the router-local HTTP helpers; USB capture is local-only.
# ---------------------------------------------------------------------------


def capture_raw_frame(
    role: str,
    source: int,
    settings: Dict[str, int | float | bool],
) -> np.ndarray | None:
    """Capture a raw frame (no color profile / picture settings) for histogram analysis."""
    from vision.camera import apply_camera_device_settings

    cap = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION) if platform.system() == "Darwin" else cv2.VideoCapture(source)
    if not cap.isOpened():
        cap.release()
        return None
    try:
        apply_camera_device_settings(cap, settings, source=source)
        time.sleep(0.15)
        frame: np.ndarray | None = None
        for _ in range(4):
            ret, current = cap.read()
            if ret and current is not None:
                frame = current
        return frame.copy() if frame is not None else None
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# Debug gallery housekeeping
# ---------------------------------------------------------------------------


def cleanup_old_gallery_dirs(max_age_seconds: float = 3600.0) -> None:
    """Remove calibration gallery directories older than ``max_age_seconds``."""
    gallery_root = Path("/tmp/calibration-gallery")
    if not gallery_root.exists():
        return
    now = time.time()
    for child in gallery_root.iterdir():
        if child.is_dir():
            try:
                age = now - child.stat().st_mtime
                if age > max_age_seconds:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                pass


__all__ = [
    "CALIBRATION_METHOD_EXPOSURE_HISTOGRAM",
    "CALIBRATION_METHOD_LLM_GUIDED",
    "CALIBRATION_METHOD_TARGET_PLATE",
    "DEFAULT_CAMERA_CALIBRATION_METHOD",
    "analysis_number",
    "as_number",
    "calibration_selection_value",
    "camera_analysis_score",
    "camera_calibration_allowed_controls",
    "camera_calibration_analysis_summary",
    "capture_raw_frame",
    "clamp_control",
    "cleanup_old_gallery_dirs",
    "compute_calibration_neutral_baseline",
    "create_camera_calibration_task",
    "get_camera_calibration_task",
    "is_exposure_or_gain_key",
    "normalize_camera_calibration_method",
    "quantize_control",
    "quantize_numeric_value",
    "update_camera_calibration_task",
]
