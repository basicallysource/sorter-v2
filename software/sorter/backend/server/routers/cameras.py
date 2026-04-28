"""Router for camera-related endpoints.

Covers camera config, listing, streaming, assignment, picture settings,
device settings, calibration, and baseline capture.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from toml_config import getCameraSetup
from hardware.macos_camera_registry import refresh_macos_cameras
from irl.config import (
    cameraColorProfileToDict,
    cameraDeviceSettingsToDict,
    cameraPictureSettingsToDict,
    parseCameraColorProfile,
    parseCameraDeviceSettings,
    parseCameraPictureSettings,
)
from role_aliases import (
    lookup_camera_role_keys,
    public_aux_camera_role,
    stored_camera_role_key,
)
from server import shared_state
from server.calibration_reference import REFERENCE_TILE_RGB
from server.camera_calibration import (
    analyze_color_plate_target,
    generate_color_profile_from_analysis,
)
from server.camera_discovery import getDiscoveredCameraStreams
from server.services.camera_calibration.histogram import (
    EXPOSURE_HISTOGRAM_TARGET_LUMA,
    calibrate_exposure_via_histogram as _calibrate_exposure_via_histogram,
)
from server.services.camera_calibration.llm import (
    DEFAULT_LLM_CALIBRATION_MAX_ITERATIONS,
    calibrate_camera_device_settings_with_llm as _calibrate_camera_device_settings_with_llm,
    normalize_llm_calibration_iterations as _normalize_llm_calibration_iterations,
    normalize_llm_calibration_model as _normalize_llm_calibration_model,
    run_llm_final_review as _run_llm_final_review,
)
from server.services.camera_calibration.smart import (
    calibrate_android_camera_device_settings as _calibrate_android_camera_device_settings,
    calibrate_usb_camera_device_settings as _calibrate_usb_camera_device_settings,
)
from server.services.camera_dashboard_crop import (
    apply_dashboard_crop as _apply_dashboard_crop,
    dashboard_crop_spec as _dashboard_crop_spec,
)
from server.services.camera_calibration.common import (
    CALIBRATION_METHOD_EXPOSURE_HISTOGRAM,
    CALIBRATION_METHOD_LLM_GUIDED,
    CALIBRATION_METHOD_TARGET_PLATE,
    DEFAULT_CAMERA_CALIBRATION_METHOD,
    as_number as _as_number,
    cleanup_old_gallery_dirs as _cleanup_old_gallery_dirs,
    create_camera_calibration_task as _create_camera_calibration_task,
    get_camera_calibration_task as _get_camera_calibration_task,
    normalize_camera_calibration_method as _normalize_camera_calibration_method,
    quantize_numeric_value as _quantize_numeric_value,
    update_camera_calibration_task as _update_camera_calibration_task,
)
router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

logger = logging.getLogger(__name__)


from server.config_helpers import (
    read_machine_params_config as _read_machine_params_config,
    write_machine_params_config as _write_machine_params_config,
)
from server.services.camera_settings import (
    CAMERA_SETUP_ROLES,
    CameraSettingsWriteError,
    camera_color_profile_for_role as _camera_color_profile_for_role,
    get_role_config_value as _camera_config_value,
    picture_settings_for_role as _picture_settings_for_role,
    restore_camera_color_profile as _restore_camera_color_profile,
    save_camera_color_profile as _save_camera_color_profile,
)


# ---------------------------------------------------------------------------
# Camera helper functions
# ---------------------------------------------------------------------------


def _get_picture_settings_table(config: Dict[str, Any]) -> Dict[str, Any]:
    picture_settings = config.get("camera_picture_settings", {})
    return picture_settings if isinstance(picture_settings, dict) else {}


def _get_camera_device_settings_table(config: Dict[str, Any]) -> Dict[str, Any]:
    device_settings = config.get("camera_device_settings", {})
    return device_settings if isinstance(device_settings, dict) else {}


def _camera_source_for_role(config: Dict[str, Any], role: str) -> int | str | None:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")

    def _normalized_source(value: Any) -> int | str | None:
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized or normalized.lower() in {"none", "null", "-1"}:
                return None
            return normalized
        return None

    cameras = config.get("cameras", {})
    if isinstance(cameras, dict):
        for lookup_role in lookup_camera_role_keys(role, config):
            source = _normalized_source(cameras.get(lookup_role))
            if source is not None:
                return source

    if role in {"feeder", "classification_top", "classification_bottom", "classification_channel", "carousel"}:
        camera_setup = getCameraSetup()
        if isinstance(camera_setup, dict):
            for lookup_role in lookup_camera_role_keys(role, config):
                fallback_source = _normalized_source(camera_setup.get(lookup_role))
                if fallback_source is not None:
                    return fallback_source
    return None


def _android_camera_base_url(source: int | str | None) -> str | None:
    if not isinstance(source, str):
        return None
    try:
        parsed = urllib_parse.urlparse(source)
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _android_camera_request(
    source: int | str | None,
    path: str,
    *,
    method: str = "GET",
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    base_url = _android_camera_base_url(source)
    if base_url is None:
        raise HTTPException(status_code=400, detail="Camera source is not an Android camera app URL.")

    url = f"{base_url}{path}"
    data = None
    headers: Dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(request, timeout=4) as response:
            body = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=detail or f"Android camera app returned HTTP {exc.code}.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Android camera app: {exc}")

    try:
        parsed = json.loads(body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Android camera app returned invalid JSON: {exc}")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Android camera app returned an unexpected response.")

    return parsed


def _android_camera_bytes_request(source: int | str | None, path: str) -> bytes:
    base_url = _android_camera_base_url(source)
    if base_url is None:
        raise HTTPException(status_code=400, detail="Camera source is not an Android camera app URL.")

    url = f"{base_url}{path}"
    request = urllib_request.Request(url, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=4) as response:
            return response.read()
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=detail or f"Android camera app returned HTTP {exc.code}.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Android camera app: {exc}")


def _camera_service_usb_device_controls(
    role: str,
    source: int,
    saved_settings: Dict[str, int | float | bool],
) -> tuple[List[Dict[str, Any]], Dict[str, int | float | bool]]:
    svc = shared_state.camera_service
    if svc is not None and hasattr(svc, "inspect_device_controls_for_role"):
        try:
            controls, live_settings = svc.inspect_device_controls_for_role(role, source, saved_settings)
            return controls, cameraDeviceSettingsToDict(live_settings or saved_settings)
        except Exception:
            pass
    return [], cameraDeviceSettingsToDict(saved_settings)


def _apply_live_usb_device_settings(
    role: str,
    parsed: Dict[str, int | float | bool],
    *,
    persist: bool,
) -> tuple[Dict[str, int | float | bool], bool]:
    svc = shared_state.camera_service
    if svc is not None and hasattr(svc, "set_device_settings_for_role"):
        try:
            live_result = svc.set_device_settings_for_role(role, parsed, persist=persist)
            if live_result is not None:
                return cameraDeviceSettingsToDict(live_result), True
        except Exception:
            pass

    return dict(parsed), False


def _numeric_control_candidates(
    control: Dict[str, Any],
    current: Any,
    *,
    count: int,
    prefer_log: bool = False,
    preferred_values: List[float] | None = None,
) -> List[float]:
    min_value = _as_number(control.get("min"))
    max_value = _as_number(control.get("max"))
    if min_value is None or max_value is None:
        current_value = _as_number(current)
        return [current_value] if current_value is not None else []

    step = _as_number(control.get("step"))
    values: List[float] = []
    current_value = _as_number(current)
    default_value = _as_number(control.get("default"))

    if prefer_log and min_value > 0 and max_value / max(min_value, 1e-6) >= 16:
        generated = np.geomspace(min_value, max_value, num=max(count, 2))
    else:
        generated = np.linspace(min_value, max_value, num=max(count, 2))

    values.extend(float(v) for v in generated.tolist())
    if preferred_values:
        values.extend(float(v) for v in preferred_values)
    if current_value is not None:
        values.append(current_value)
    if default_value is not None:
        values.append(default_value)
    values.extend([min_value, max_value])

    normalized: List[float] = []
    seen: set[float] = set()
    for raw in values:
        clipped = max(min_value, min(max_value, float(raw)))
        quantized = _quantize_numeric_value(clipped, min_value, step)
        rounded = round(quantized, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        normalized.append(int(round(quantized)) if step is not None and step >= 1 else float(quantized))

    normalized.sort(key=float)
    return normalized


def _focused_numeric_control_candidates(
    control: Dict[str, Any],
    current: Any,
    *,
    count: int,
    prefer_log: bool = False,
    relative_span: float = 0.35,
    linear_span_fraction: float = 0.12,
) -> List[float]:
    min_value = _as_number(control.get("min"))
    max_value = _as_number(control.get("max"))
    current_value = _as_number(current)
    if min_value is None or max_value is None or current_value is None:
        return _numeric_control_candidates(control, current, count=count, prefer_log=prefer_log)

    step = _as_number(control.get("step"))
    if prefer_log and current_value > 0:
        low = max(min_value, current_value * (1.0 - relative_span))
        high = min(max_value, current_value * (1.0 + relative_span))
        if high <= low:
            values = [current_value]
        else:
            values = np.geomspace(low, high, num=max(count, 3)).tolist()
    else:
        span = max(
            float(step) if step is not None else 0.0,
            (max_value - min_value) * linear_span_fraction,
        )
        low = max(min_value, current_value - span)
        high = min(max_value, current_value + span)
        if high <= low:
            values = [current_value]
        else:
            values = np.linspace(low, high, num=max(count, 3)).tolist()

    values.append(current_value)
    normalized: List[float] = []
    seen: set[float] = set()
    for raw in values:
        clipped = max(min_value, min(max_value, float(raw)))
        quantized = _quantize_numeric_value(clipped, min_value, step)
        rounded = round(quantized, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        normalized.append(int(round(quantized)) if step is not None and step >= 1 else float(quantized))
    normalized.sort(key=float)
    return normalized


# ---------------------------------------------------------------------------
# Frame capture & analysis helpers for calibration
# ---------------------------------------------------------------------------


def _capture_frame_for_calibration(
    role: str,
    source: int | str | None,
    *,
    after_timestamp: float | None = None,
    fallback_settings: Dict[str, int | float | bool] | None = None,
    picture_settings: Dict[str, Any] | None = None,
    color_profile: Dict[str, Any] | None = None,
) -> np.ndarray | None:
    from vision.camera import (
        apply_camera_color_profile,
        apply_camera_device_settings,
        apply_picture_settings,
    )

    parsed_picture_settings = parseCameraPictureSettings(picture_settings)
    parsed_color_profile = parseCameraColorProfile(color_profile)

    if isinstance(source, str):
        best_frame = None
        for index in range(5):
            try:
                jpg = _android_camera_bytes_request(source, "/snapshot.jpg")
                buffer = np.frombuffer(jpg, dtype=np.uint8)
                frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
                if frame is not None and frame.size > 0:
                    best_frame = frame
            except HTTPException:
                pass
            if index < 4:
                time.sleep(0.18)
        if best_frame is not None:
            best_frame = apply_camera_color_profile(best_frame, parsed_color_profile)
            best_frame = apply_picture_settings(best_frame, parsed_picture_settings)
            return best_frame
        return None

    if not isinstance(source, int):
        return None

    cap = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION) if platform.system() == "Darwin" else cv2.VideoCapture(source)
    if not cap.isOpened():
        cap.release()
        return None

    try:
        if fallback_settings:
            apply_camera_device_settings(cap, fallback_settings, source=source)
            time.sleep(0.2)
        frame: np.ndarray | None = None
        for _ in range(4):
            ret, current = cap.read()
            if ret and current is not None:
                frame = current
        if frame is None:
            return None
        frame = apply_camera_color_profile(frame, parsed_color_profile)
        frame = apply_picture_settings(frame, parsed_picture_settings)
        return frame.copy()
    finally:
        cap.release()


def _analyze_candidate_settings(
    role: str,
    source: int | str | None,
    settings: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any] | None, np.ndarray | None]:
    preview_started_at = time.time()
    preview = preview_camera_device_settings(role, settings)
    preview_settings = preview.get("settings", settings)
    if isinstance(source, str):
        applied_settings = dict(preview_settings) if isinstance(preview_settings, dict) else dict(settings)
        time.sleep(1.35)
    else:
        applied_settings = cameraDeviceSettingsToDict(parseCameraDeviceSettings(preview_settings))
        time.sleep(0.25)
    frame = _capture_frame_for_calibration(
        role, source, after_timestamp=preview_started_at, fallback_settings=applied_settings
    )

    if frame is None:
        return applied_settings, None, None
    analysis = analyze_color_plate_target(frame)
    analysis_dict = analysis.to_dict() if analysis is not None else None
    return applied_settings, analysis_dict, frame


# ---------------------------------------------------------------------------
# Camera opening helpers
# ---------------------------------------------------------------------------


def _open_camera(index: int) -> cv2.VideoCapture:
    if platform.system() == "Darwin":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


def _probe_camera_index(index: int) -> Optional[Dict[str, Any]]:
    cap = _open_camera(index)
    if not cap.isOpened():
        cap.release()
        return None

    try:
        ret, frame = cap.read()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if ret and frame is not None:
            height, width = frame.shape[:2]
        if width <= 0 or height <= 0:
            return None
        return {
            "kind": "usb",
            "index": index,
            "width": width,
            "height": height,
            "preview_available": bool(ret and frame is not None),
        }
    finally:
        cap.release()


def _active_camera_indices() -> dict[int, tuple[int, int]]:
    """Return {index: (width, height)} for cameras already open in CameraService."""
    svc = shared_state.camera_service
    if svc is None:
        return {}
    result: dict[int, tuple[int, int]] = {}
    for device in svc.devices.values():
        source = device.capture_thread.getCameraSource()
        if not isinstance(source, int):
            continue
        frame = device.latest_frame
        if frame is not None and frame.raw is not None:
            h, w = frame.raw.shape[:2]
            result[source] = (w, h)
        else:
            result[source] = (0, 0)
    return result


def _list_usb_cameras() -> List[Dict[str, Any]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    active = _active_camera_indices()

    if platform.system() == "Darwin":
        enumerated = list(refresh_macos_cameras())
        if enumerated:
            indices_to_probe = [
                int(c.index) for c in enumerated if int(c.index) not in active
            ]
            probed_map: dict[int, dict] = {}
            if indices_to_probe:
                with ThreadPoolExecutor(max_workers=min(4, len(indices_to_probe))) as pool:
                    futs = {pool.submit(_probe_camera_index, idx): idx for idx in indices_to_probe}
                    for fut in as_completed(futs):
                        idx = futs[fut]
                        probed_map[idx] = fut.result() or {}

            cameras: List[Dict[str, Any]] = []
            for camera in enumerated:
                idx = int(camera.index)
                if idx in active:
                    w, h = active[idx]
                    info = {"width": w, "height": h, "preview_available": w > 0 and h > 0}
                else:
                    info = probed_map.get(idx, {})
                cameras.append(
                    {
                        "kind": "usb",
                        "index": idx,
                        "name": str(camera.name),
                        "width": int(info.get("width", 0)),
                        "height": int(info.get("height", 0)),
                        "preview_available": bool(info.get("preview_available", False)),
                    }
                )
            return cameras

    # Non-macOS: probe indices 0-15, skip active ones
    indices_to_probe = [i for i in range(16) if i not in active]
    probed_map: dict[int, dict] = {}
    if indices_to_probe:
        with ThreadPoolExecutor(max_workers=min(4, len(indices_to_probe))) as pool:
            futs = {pool.submit(_probe_camera_index, idx): idx for idx in indices_to_probe}
            for fut in as_completed(futs):
                idx = futs[fut]
                result = fut.result()
                if result is not None:
                    probed_map[idx] = result

    usb_cameras: List[Dict[str, Any]] = []
    for i in range(16):
        if i in active:
            w, h = active[i]
            if w > 0 or h > 0:
                usb_cameras.append({
                    "kind": "usb",
                    "index": i,
                    "width": w,
                    "height": h,
                    "preview_available": True,
                })
        elif i in probed_map:
            usb_cameras.append(probed_map[i])
    return usb_cameras


# ---------------------------------------------------------------------------
# Synchronous calibration runner
# ---------------------------------------------------------------------------


def _run_camera_calibration_sync(
    role: str,
    *,
    method: str = DEFAULT_CAMERA_CALIBRATION_METHOD,
    openrouter_model: str | None = None,
    max_iterations: int = DEFAULT_LLM_CALIBRATION_MAX_ITERATIONS,
    apply_color_profile: bool = True,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
    report_trace: Callable[[List[Dict[str, Any]]], None] | None = None,
    task_id: str | None = None,
) -> Dict[str, Any]:
    current_response = get_camera_device_settings(role)
    source = current_response.get("source")
    provider = current_response.get("provider")
    normalized_method = _normalize_camera_calibration_method(method)
    normalized_openrouter_model = _normalize_llm_calibration_model(openrouter_model)
    normalized_max_iterations = _normalize_llm_calibration_iterations(max_iterations)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")
    if not bool(current_response.get("supported")):
        raise HTTPException(status_code=400, detail=current_response.get("message") or "This camera cannot be calibrated through the current control backend.")

    # Create gallery directory for this calibration run
    _cleanup_old_gallery_dirs()
    gallery_id = task_id or uuid4().hex
    gallery_dir = Path("/tmp/calibration-gallery") / gallery_id
    gallery_dir.mkdir(parents=True, exist_ok=True)

    _, raw_config = _read_machine_params_config()
    original_picture_settings = _picture_settings_for_role(raw_config, role)
    original_color_profile = _camera_color_profile_for_role(raw_config, role)

    if provider == "android-camera-app":
        original_settings = (
            dict(current_response.get("settings"))
            if isinstance(current_response.get("settings"), dict)
            else {}
        )
    else:
        original_settings = cameraDeviceSettingsToDict(
            parseCameraDeviceSettings(current_response.get("settings"))
        )

    try:
        response_curve_data: Dict[str, Any] | None = None
        calibration_metadata: Dict[str, Any] = {"method": normalized_method}

        live_color_profile_disabled = False
        if normalized_method == CALIBRATION_METHOD_EXPOSURE_HISTOGRAM:
            controls = current_response.get("controls")
            if not isinstance(controls, list):
                raise HTTPException(
                    status_code=400,
                    detail="This camera does not expose a control list required for histogram exposure calibration.",
                )
            if report_progress is not None:
                report_progress(
                    "preparing",
                    0.05,
                    "Preparing histogram-driven exposure calibration.",
                    None,
                )
            best_settings, analysis = _calibrate_exposure_via_histogram(
                role,
                source,
                controls,
                original_settings,
                analyze_frame=_analyze_candidate_settings,
                capture_frame=_capture_frame_for_calibration,
                report_progress=report_progress,
                gallery_dir=gallery_dir,
            )
            calibration_metadata = {
                "method": normalized_method,
                "target_luma": EXPOSURE_HISTOGRAM_TARGET_LUMA,
                "final_luma": analysis.get("final_luma"),
                "iterations": analysis.get("iterations"),
                "converged": analysis.get("converged"),
            }
        elif normalized_method == CALIBRATION_METHOD_LLM_GUIDED:
            if report_progress is not None:
                report_progress("preparing", 0.05, "Preparing LLM-guided camera calibration.", None)
            # Push a disabled color profile to the live capture thread so the
            # advisor sees the raw, uncorrected sensor signal during the loop.
            # The persisted config is left untouched — it'll be replaced by the
            # freshly generated CCM after the loop, or restored on failure.
            live_color_profile_disabled = _push_live_color_profile(role, {"enabled": False})
            best_settings, analysis, calibration_metadata = _calibrate_camera_device_settings_with_llm(
                role,
                str(provider or "unknown"),
                source,
                current_response,
                openrouter_model=normalized_openrouter_model,
                max_iterations=normalized_max_iterations,
                analyze_frame=_analyze_candidate_settings,
                dashboard_crop_spec=_dashboard_crop_spec,
                apply_dashboard_crop=_apply_dashboard_crop,
                report_progress=report_progress,
                report_trace=report_trace,
                gallery_dir=gallery_dir,
            )
        elif provider == "usb-opencv":
            controls = current_response.get("controls")
            if not isinstance(controls, list) or not isinstance(source, int):
                raise HTTPException(status_code=400, detail="USB camera controls are not available for calibration.")
            if report_progress is not None:
                report_progress("preparing", 0.05, "Preparing USB camera calibration.", None)
            best_settings, analysis, response_curve_data = _calibrate_usb_camera_device_settings(
                role,
                source,
                controls,
                original_settings,
                preview_settings=preview_camera_device_settings,
                capture_frame=_capture_frame_for_calibration,
                report_progress=report_progress,
                gallery_dir=gallery_dir,
            )
        elif provider == "android-camera-app":
            capabilities = current_response.get("capabilities")
            if not isinstance(capabilities, dict) or not isinstance(source, str):
                raise HTTPException(status_code=400, detail="Android camera capabilities are not available for calibration.")
            if report_progress is not None:
                report_progress("preparing", 0.05, "Preparing Android camera calibration.", None)
            best_settings, analysis = _calibrate_android_camera_device_settings(
                role,
                source,
                current_response.get("settings") if isinstance(current_response.get("settings"), dict) else {},
                capabilities,
                analyze_frame=_analyze_candidate_settings,
                report_progress=report_progress,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="This camera provider does not support target-based calibration yet.",
            )

        if report_progress is not None:
            report_progress("saving", 0.91, "Saving calibrated exposure and white balance.", analysis)
        saved = save_camera_device_settings(role, best_settings)
        time.sleep(1.5 if isinstance(source, str) else 0.2)

        # Histogram mode is exposure-only — we don't look at the 6-colour target
        # and we don't touch the camera's color profile. Leave whatever CCM the
        # operator already persisted alone and short-circuit the color-plate
        # path below.
        if normalized_method == CALIBRATION_METHOD_EXPOSURE_HISTOGRAM:
            return {
                "ok": True,
                "method": normalized_method,
                "task_id": task_id,
                "role": role,
                "provider": provider,
                "source": source,
                "applied_settings": saved,
                "calibration": calibration_metadata,
                "analysis": analysis,
                "message": (
                    "Exposure-histogram calibration saved. "
                    f"Final exposure {best_settings.get('exposure')}, "
                    f"final luma {int(analysis.get('final_luma', 0))}."
                ),
            }

        raw_frame = _capture_frame_for_calibration(
            role,
            source,
            fallback_settings=best_settings,
        )
        raw_analysis_obj = analyze_color_plate_target(raw_frame) if raw_frame is not None else None
        raw_analysis = raw_analysis_obj.to_dict() if raw_analysis_obj is not None else analysis
        profile_saved: Dict[str, Any] | None = None
        if not apply_color_profile:
            # User opted out of final color correction. Persist a disabled
            # profile so the live capture pipeline (vision_manager) skips
            # correction going forward, regardless of what the target analysis
            # would have suggested.
            if report_progress is not None:
                report_progress("profile_generation", 0.95, "Skipping color correction profile per user request.", raw_analysis)
            profile_saved = _save_camera_color_profile(role, {"enabled": False})
        elif raw_analysis is not None:
            if report_progress is not None:
                report_progress("profile_generation", 0.95, "Generating a color correction profile from the target plate.", raw_analysis)
            profile_payload = generate_color_profile_from_analysis(raw_analysis, response_curve=response_curve_data)
            if profile_payload is None and normalized_method == CALIBRATION_METHOD_TARGET_PLATE:
                raise HTTPException(
                    status_code=400,
                    detail="Calibration found the target, but could not generate a color profile from it.",
                )
            if profile_payload is not None:
                profile_saved = _save_camera_color_profile(role, profile_payload)
        elif normalized_method == CALIBRATION_METHOD_TARGET_PLATE:
            raise HTTPException(
                status_code=400,
                detail="Calibration found device settings, but could not re-analyze the target plate afterwards.",
            )

        # If we disabled the live color profile for the LLM loop but never
        # generated a replacement, restore the original profile to the live
        # capture thread so we don't leave the camera with no correction.
        if live_color_profile_disabled and profile_saved is None:
            _push_live_color_profile(role, original_color_profile)

        if report_progress is not None:
            report_progress("verifying", 0.98, "Verifying the calibrated profile on the live feed.", raw_analysis)

        final_frame = raw_frame
        if final_frame is None:
            final_frame = _capture_frame_for_calibration(
                role,
                source,
                fallback_settings=best_settings,
            )
        if final_frame is not None:
            from vision.camera import apply_camera_color_profile, apply_picture_settings

            if apply_color_profile:
                final_frame = apply_camera_color_profile(
                    final_frame,
                    parseCameraColorProfile(profile_saved.get("profile") if profile_saved is not None else original_color_profile),
                )
            final_frame = apply_picture_settings(
                final_frame,
                parseCameraPictureSettings(original_picture_settings),
            )

        final_analysis = analyze_color_plate_target(final_frame) if final_frame is not None else None
        chosen_analysis = final_analysis.to_dict() if final_analysis is not None else raw_analysis

        # LLM-guided calibration: send the CCM-corrected frame back to the advisor
        # for a final sign-off so the trace shows whether the finished pipeline is
        # actually acceptable.
        if (
            normalized_method == CALIBRATION_METHOD_LLM_GUIDED
            and final_frame is not None
        ):
            existing_trace_raw = calibration_metadata.get("trace")
            existing_trace: List[Dict[str, Any]] = (
                list(existing_trace_raw) if isinstance(existing_trace_raw, list) else []
            )
            iteration_numbers = [
                int(entry.get("iteration"))
                for entry in existing_trace
                if isinstance(entry, dict) and isinstance(entry.get("iteration"), int)
            ]
            next_iteration_index = (max(iteration_numbers) + 1) if iteration_numbers else 1
            advisor_history_step = len(existing_trace) + 1
            if report_progress is not None:
                report_progress(
                    "llm_final_review",
                    0.99,
                    "Asking the advisor to sign off on the color-corrected result.",
                    chosen_analysis,
                )
            review_entry = _run_llm_final_review(
                role=role,
                gallery_dir=gallery_dir,
                openrouter_model=normalized_openrouter_model,
                final_frame=final_frame,
                final_settings=best_settings,
                profile_present=profile_saved is not None,
                last_loop_summary=str(calibration_metadata.get("summary") or ""),
                next_iteration_index=next_iteration_index,
                advisor_history_step=advisor_history_step,
                dashboard_crop_spec=_dashboard_crop_spec,
                apply_dashboard_crop=_apply_dashboard_crop,
            )
            existing_trace.append(review_entry)
            calibration_metadata["trace"] = existing_trace
            calibration_metadata["final_review"] = review_entry
            if report_trace is not None:
                report_trace([dict(entry) for entry in existing_trace])

        if normalized_method == CALIBRATION_METHOD_LLM_GUIDED:
            review_status = ""
            review_obj = calibration_metadata.get("final_review")
            if isinstance(review_obj, dict):
                review_status = str(review_obj.get("status") or "").strip().lower()
            if not apply_color_profile:
                base_msg = "Camera settings were tuned by the LLM advisor. Final color correction was disabled — no color profile is applied."
            elif profile_saved is not None:
                base_msg = "Camera settings were tuned by the LLM advisor and a fresh color profile was generated from the target plate."
            else:
                base_msg = "Camera settings were tuned by the LLM advisor. The existing color profile was kept because the target plate was not confidently re-analyzed."
            if review_status == "approved":
                message = f"{base_msg} Advisor signed off on the corrected image."
            elif review_status == "concerns":
                message = f"{base_msg} Advisor flagged remaining concerns — review the trace."
            else:
                message = base_msg
        else:
            if not apply_color_profile:
                message = "Camera calibrated from the 6-color target plate. Final color correction was disabled per request."
            else:
                message = "Camera calibrated from the 6-color target plate, and a color profile was generated."
        result = {
            **saved,
            "color_profile": profile_saved.get("profile") if profile_saved is not None else original_color_profile,
            "analysis": chosen_analysis,
            "gallery_id": gallery_id,
            "message": message,
            "method": normalized_method,
        }
        if normalized_method == CALIBRATION_METHOD_LLM_GUIDED:
            result["openrouter_model"] = calibration_metadata.get("openrouter_model")
            result["advisor_trace"] = calibration_metadata.get("trace")
            result["advisor_summary"] = calibration_metadata.get("summary")
            result["advisor_final_review"] = calibration_metadata.get("final_review")
        if report_progress is not None:
            report_progress("completed", 1.0, "Camera calibration finished.", result.get("analysis"))
        return result
    except HTTPException:
        _restore_preview_settings(role, original_settings)
        _restore_camera_color_profile(role, original_color_profile)
        raise
    except Exception as exc:
        _restore_preview_settings(role, original_settings)
        _restore_camera_color_profile(role, original_color_profile)
        raise HTTPException(status_code=500, detail=f"Camera calibration failed: {exc}")


def _run_camera_calibration_task(
    task_id: str,
    role: str,
    *,
    method: str = DEFAULT_CAMERA_CALIBRATION_METHOD,
    openrouter_model: str | None = None,
    max_iterations: int = DEFAULT_LLM_CALIBRATION_MAX_ITERATIONS,
    apply_color_profile: bool = True,
) -> None:
    def report_progress(stage: str, progress: float, message: str, analysis: Dict[str, Any] | None = None) -> None:
        _update_camera_calibration_task(
            task_id,
            status="running" if stage != "completed" else "completed",
            stage=stage,
            progress=max(0.0, min(1.0, float(progress))),
            message=message,
            analysis_preview=analysis,
        )

    def report_trace(trace: List[Dict[str, Any]]) -> None:
        _update_camera_calibration_task(
            task_id,
            advisor_trace=trace,
        )

    try:
        _update_camera_calibration_task(
            task_id,
            status="running",
            stage="starting",
            progress=0.01,
            message="Starting camera calibration.",
        )
        result = _run_camera_calibration_sync(
            role,
            method=method,
            openrouter_model=openrouter_model,
            max_iterations=max_iterations,
            apply_color_profile=apply_color_profile,
            report_progress=report_progress,
            report_trace=report_trace,
            task_id=task_id,
        )
        _update_camera_calibration_task(
            task_id,
            status="completed",
            stage="completed",
            progress=1.0,
            message=str(result.get("message") or "Camera calibration finished."),
            result=result,
            error=None,
        )
    except HTTPException as exc:
        _update_camera_calibration_task(
            task_id,
            status="failed",
            stage="failed",
            progress=1.0,
            message="Camera calibration failed.",
            error=str(exc.detail),
        )
    except Exception as exc:
        _update_camera_calibration_task(
            task_id,
            status="failed",
            stage="failed",
            progress=1.0,
            message="Camera calibration failed.",
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Color profile save / restore helpers
# ---------------------------------------------------------------------------


def _restore_preview_settings(role: str, settings: Dict[str, int | float | bool]) -> None:
    try:
        preview_camera_device_settings(role, settings)
    except Exception:
        pass


def _push_live_color_profile(role: str, profile: Any) -> bool:
    """Legacy hook: pushed a color profile to the running CaptureThread during
    LLM-guided calibration. Post-cutover there is no vision_manager accessor,
    so the advisor sees whatever the persisted config produces.
    """
    return False


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CameraAssignment(BaseModel):
    layout: Optional[str] = None
    feeder: Optional[int | str] = None
    c_channel_2: Optional[int | str] = None
    c_channel_3: Optional[int | str] = None
    carousel: Optional[int | str] = None
    classification_channel: Optional[int | str] = None
    classification_top: Optional[int | str] = None
    classification_bottom: Optional[int | str] = None


class CameraLayoutPayload(BaseModel):
    layout: str


class CameraPictureSettingsPayload(BaseModel):
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False


class CameraCalibrationStartPayload(BaseModel):
    method: Optional[str] = None
    openrouter_model: Optional[str] = None
    max_iterations: Optional[int] = None
    apply_color_profile: Optional[bool] = None


# ===================================================================
# Routes
# ===================================================================


# ---------------------------------------------------------------------------
# Camera config / list / assign
# ---------------------------------------------------------------------------


@router.get("/api/cameras/health")
def get_camera_health() -> Dict[str, Any]:
    """Return per-role camera health status."""
    import server.shared_state as shared_state

    if shared_state.camera_service is None:
        raise HTTPException(status_code=500, detail="Camera service not initialized")
    return shared_state.camera_service.get_health_status()


@router.get("/api/cameras/config")
def get_camera_config() -> Dict[str, Any]:
    """Return current camera assignments from TOML."""
    try:
        _, raw = _read_machine_params_config()
        cameras = raw.get("cameras", {}) if isinstance(raw, dict) else {}
        if not isinstance(cameras, dict):
            cameras = {}
        aux_role = public_aux_camera_role(raw if isinstance(raw, dict) else {})
        return {
            "layout": cameras.get("layout", "default"),
            "feeder": _camera_source_for_role(raw, "feeder"),
            "c_channel_2": _camera_source_for_role(raw, "c_channel_2"),
            "c_channel_3": _camera_source_for_role(raw, "c_channel_3"),
            aux_role: _camera_source_for_role(raw, aux_role),
            "classification_top": _camera_source_for_role(raw, "classification_top"),
            "classification_bottom": _camera_source_for_role(raw, "classification_bottom"),
        }
    except HTTPException:
        aux_role = public_aux_camera_role({})
        return {
            "layout": "default",
            "feeder": None,
            "c_channel_2": None,
            "c_channel_3": None,
            aux_role: None,
            "classification_top": None,
            "classification_bottom": None,
        }


@router.post("/api/cameras/layout")
def save_camera_layout(payload: CameraLayoutPayload) -> Dict[str, Any]:
    if payload.layout not in {"default", "split_feeder"}:
        raise HTTPException(
            status_code=400,
            detail="layout must be 'default' or 'split_feeder'.",
        )

    params_path, config = _read_machine_params_config()
    cameras = config.get("cameras", {})
    if not isinstance(cameras, dict):
        cameras = {}
    cameras["layout"] = payload.layout
    config["cameras"] = cameras

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    result = get_camera_config()
    shared_state.publishCamerasConfig(result)
    return result


@router.get("/api/cameras/list")
def list_cameras() -> Dict[str, Any]:
    """List local USB cameras plus discovered network camera streams."""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        usb_fut = pool.submit(_list_usb_cameras)
        net_fut = pool.submit(getDiscoveredCameraStreams)
        return {
            "usb": usb_fut.result(),
            "network": net_fut.result(),
        }


@router.post("/api/cameras/assign")
def assign_cameras(assignment: CameraAssignment) -> Dict[str, Any]:
    """Save camera role assignments to the machine TOML config."""
    params_path, config = _read_machine_params_config()
    aux_role = public_aux_camera_role(config)

    # Update cameras section
    cameras = config.get("cameras", {})
    if not isinstance(cameras, dict):
        cameras = {}
    updates = assignment.model_dump(exclude_unset=True)
    layout = updates.pop("layout", None)
    if layout is not None:
        if layout not in {"default", "split_feeder"}:
            raise HTTPException(
                status_code=400,
                detail="layout must be 'default' or 'split_feeder'.",
            )
        cameras["layout"] = layout
    elif "layout" not in cameras:
        if "feeder" in updates:
            cameras["layout"] = "default"
        elif any(role in updates for role in ("c_channel_2", "c_channel_3", "carousel", "classification_channel")):
            cameras["layout"] = "split_feeder"
    for key, value in updates.items():
        target_key = stored_camera_role_key(key, config)
        if target_key == "classification_channel":
            cameras.pop("carousel", None)
        elif target_key == "carousel":
            cameras.pop("classification_channel", None)
        if value is None:
            cameras.pop(target_key, None)
        else:
            cameras[target_key] = value
    config["cameras"] = cameras

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live: Dict[str, bool] = {}

    assignment = {
        "layout": cameras.get("layout", "default"),
        "feeder": cameras.get("feeder"),
        "c_channel_2": cameras.get("c_channel_2"),
        "c_channel_3": cameras.get("c_channel_3"),
        aux_role: _camera_source_for_role(config, aux_role),
        "classification_top": cameras.get("classification_top"),
        "classification_bottom": cameras.get("classification_bottom"),
    }
    shared_state.publishCamerasConfig(assignment)

    return {
        "ok": True,
        "assignment": assignment,
        "applied_live": applied_live,
        "message": (
            "Camera assignment updated live."
            if updates and all(applied_live.get(key, False) for key in updates.keys())
            else "Camera assignment saved."
        ),
    }


# ---------------------------------------------------------------------------
# Picture settings
# ---------------------------------------------------------------------------


@router.get("/api/cameras/picture-settings/{role}")
def get_camera_picture_settings(role: str) -> Dict[str, Any]:
    """Return persisted picture settings for a camera role."""
    _, config = _read_machine_params_config()
    return {
        "role": role,
        "settings": _picture_settings_for_role(config, role),
    }


@router.post("/api/cameras/picture-settings/{role}")
def save_camera_picture_settings(
    role: str,
    payload: CameraPictureSettingsPayload,
) -> Dict[str, Any]:
    """Save and live-apply picture settings for a camera role when possible."""
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")

    params_path, config = _read_machine_params_config()
    picture_settings = _get_picture_settings_table(config)
    parsed = parseCameraPictureSettings(payload.model_dump())
    config_role = stored_camera_role_key(role, config)
    if config_role == "classification_channel":
        picture_settings.pop("carousel", None)
    elif config_role == "carousel":
        picture_settings.pop("classification_channel", None)
    picture_settings[config_role] = cameraPictureSettingsToDict(parsed)
    config["camera_picture_settings"] = picture_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    return {
        "ok": True,
        "role": role,
        "settings": cameraPictureSettingsToDict(parsed),
        "applied_live": False,
        "message": "Feed orientation saved.",
    }


# ---------------------------------------------------------------------------
# Color profile (CCM)
# ---------------------------------------------------------------------------


@router.get("/api/cameras/color-profile/{role}")
def get_camera_color_profile(role: str) -> Dict[str, Any]:
    """Return persisted color correction profile (CCM) for a camera role."""
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    _, config = _read_machine_params_config()
    profile = _camera_color_profile_for_role(config, role)
    return {
        "ok": True,
        "role": role,
        "profile": profile,
    }


@router.delete("/api/cameras/color-profile/{role}")
def delete_camera_color_profile(role: str) -> Dict[str, Any]:
    """Remove persisted color correction profile for a camera role and disable live correction."""
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    try:
        saved = _save_camera_color_profile(role, {"enabled": False})
    except CameraSettingsWriteError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {
        "ok": True,
        "role": role,
        "profile": saved.get("profile"),
        "applied_live": saved.get("applied_live", False),
        "message": "Color correction removed.",
    }


# ---------------------------------------------------------------------------
# Live histogram
# ---------------------------------------------------------------------------

_HISTOGRAM_BINS = 64


@router.get("/api/cameras/{role}/histogram")
def get_camera_histogram(role: str) -> Dict[str, Any]:
    """Return live RGB histogram (64 bins) with reference color markers."""
    markers: Dict[str, Dict[str, int]] = {}
    for label, (r, g, b) in REFERENCE_TILE_RGB.items():
        markers[label] = {"r": r, "g": g, "b": b}

    # Live histogram needs a running camera_service frame source; post-cutover
    # there is no vision_manager accessor, so the endpoint stays in the waiting
    # envelope until the camera_service frame bridge lands.
    return {
        "ok": True,
        "waiting": True,
        "bins": _HISTOGRAM_BINS,
        "r": [],
        "g": [],
        "b": [],
        "reference_markers": markers,
    }


# ---------------------------------------------------------------------------
# Device settings
# ---------------------------------------------------------------------------


@router.get("/api/cameras/device-settings/{role}")
def get_camera_device_settings(role: str) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        return {
            "ok": True,
            "role": role,
            "source": None,
            "provider": "none",
            "settings": {},
            "controls": [],
            "supported": False,
            "message": "No camera is assigned to this role.",
        }

    if isinstance(source, str):
        try:
            android_data = _android_camera_request(source, "/camera-settings")
        except HTTPException as exc:
            return {
                "ok": True,
                "role": role,
                "source": source,
                "provider": "network-stream",
                "settings": {},
                "controls": [],
                "supported": False,
                "message": str(exc.detail),
            }

        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": android_data.get("provider", "android-camera-app"),
            "settings": android_data.get("settings", {}),
            "capabilities": android_data.get("capabilities", {}),
            "controls": [],
            "supported": True,
        }

    saved_settings = cameraDeviceSettingsToDict(
        parseCameraDeviceSettings(_camera_config_value(config, "camera_device_settings", role))
    )
    controls, live_settings = _camera_service_usb_device_controls(role, source, saved_settings)
    current_settings = live_settings or saved_settings
    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": current_settings,
        "controls": controls,
        "supported": bool(controls),
        "message": (
            "Real USB camera controls are available for this camera."
            if controls
            else (
                "This USB camera does not expose adjustable UVC controls on this macOS setup."
                if platform.system() == "Darwin"
                else "This USB camera does not expose adjustable controls through the current capture backend."
            )
        ),
    }


@router.post("/api/cameras/device-settings/{role}/preview")
def preview_camera_device_settings(role: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")

    if isinstance(source, str):
        proxied = _android_camera_request(
            source,
            "/camera-settings/preview",
            method="POST",
            payload=payload,
        )
        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": proxied.get("provider", "android-camera-app"),
            "settings": proxied.get("settings", payload),
            "persisted": False,
            "applied_live": True,
        }

    parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(payload))
    shared_state.camera_device_preview_overrides[role] = dict(parsed)
    applied_settings, applied_live = _apply_live_usb_device_settings(role, parsed, persist=False)
    shared_state.camera_device_preview_overrides[role] = dict(applied_settings)

    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": applied_settings,
        "persisted": False,
        "applied_live": applied_live,
    }


@router.post("/api/cameras/device-settings/{role}")
def save_camera_device_settings(role: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    params_path, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")

    if isinstance(source, str):
        proxied = _android_camera_request(
            source,
            "/camera-settings",
            method="POST",
            payload=payload,
        )
        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": proxied.get("provider", "android-camera-app"),
            "settings": proxied.get("settings", payload),
            "persisted": True,
            "applied_live": True,
        }

    parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(payload))
    device_settings = _get_camera_device_settings_table(config)
    config_role = stored_camera_role_key(role, config)
    if parsed:
        if config_role == "classification_channel":
            device_settings.pop("carousel", None)
        elif config_role == "carousel":
            device_settings.pop("classification_channel", None)
        device_settings[config_role] = dict(parsed)
    else:
        device_settings.pop(config_role, None)
    config["camera_device_settings"] = device_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    shared_state.camera_device_preview_overrides[role] = dict(parsed)
    applied_settings, applied_live = _apply_live_usb_device_settings(role, parsed, persist=True)
    shared_state.camera_device_preview_overrides[role] = dict(applied_settings)

    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": applied_settings,
        "persisted": True,
        "applied_live": applied_live,
        "message": "Camera device settings saved.",
    }


# ---------------------------------------------------------------------------
# Drift detection (device settings)
# ---------------------------------------------------------------------------


def _device_setting_diff(
    key: str,
    saved_value: Any,
    live_value: Any,
    control: Dict[str, Any] | None,
) -> Dict[str, Any] | None:
    if saved_value is None:
        return None
    if live_value is None:
        return None

    if isinstance(saved_value, bool) or isinstance(live_value, bool):
        if bool(saved_value) == bool(live_value):
            return None
        return {"key": key, "saved": bool(saved_value), "live": bool(live_value), "kind": "boolean"}

    try:
        saved_num = float(saved_value)
        live_num = float(live_value)
    except (TypeError, ValueError):
        return None

    step = 1.0
    tol_pct = 0.01
    if isinstance(control, dict):
        step_raw = control.get("step")
        if isinstance(step_raw, (int, float)) and step_raw > 0:
            step = float(step_raw)
        min_raw = control.get("min")
        max_raw = control.get("max")
        if isinstance(min_raw, (int, float)) and isinstance(max_raw, (int, float)) and max_raw > min_raw:
            tol_pct = max(tol_pct, 0.01 * (float(max_raw) - float(min_raw)))
    tolerance = max(step, abs(saved_num) * 0.01, tol_pct * 0.01)
    if abs(saved_num - live_num) <= tolerance:
        return None
    return {"key": key, "saved": saved_num, "live": live_num, "kind": "number"}


@router.get("/api/cameras/device-settings/{role}/diff")
def get_camera_device_settings_diff(role: str) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        return {
            "ok": True,
            "role": role,
            "source": None,
            "supported": False,
            "saved": {},
            "live": {},
            "diffs": [],
            "message": "No camera is assigned to this role.",
        }

    saved_settings = cameraDeviceSettingsToDict(
        parseCameraDeviceSettings(_camera_config_value(config, "camera_device_settings", role))
    )

    controls: List[Dict[str, Any]] = []
    live_settings: Dict[str, Any] = {}
    if isinstance(source, int):
        controls, live_settings = _camera_service_usb_device_controls(role, source, saved_settings)
    else:
        # Network-stream (Android) — proxied read
        try:
            android_data = _android_camera_request(source, "/camera-settings")
            raw_settings = android_data.get("settings") or {}
            if isinstance(raw_settings, dict):
                live_settings = {k: v for k, v in raw_settings.items() if isinstance(v, (int, float, bool))}
        except HTTPException as exc:
            return {
                "ok": True,
                "role": role,
                "source": source,
                "supported": False,
                "saved": saved_settings,
                "live": {},
                "diffs": [],
                "message": str(exc.detail),
            }

    controls_by_key: Dict[str, Dict[str, Any]] = {}
    for control in controls:
        key = control.get("key")
        if isinstance(key, str):
            controls_by_key[key] = control

    diffs: List[Dict[str, Any]] = []
    keys = set(saved_settings.keys()) | set(live_settings.keys())
    for key in sorted(keys):
        diff = _device_setting_diff(
            key,
            saved_settings.get(key),
            live_settings.get(key),
            controls_by_key.get(key),
        )
        if diff is not None:
            diffs.append(diff)

    return {
        "ok": True,
        "role": role,
        "source": source,
        "supported": bool(controls) or bool(live_settings),
        "saved": saved_settings,
        "live": live_settings,
        "diffs": diffs,
    }


# ---------------------------------------------------------------------------
# Capture modes (resolution / fps)
# ---------------------------------------------------------------------------


def _capture_modes_for_source(source: int | str | None) -> tuple[List[Dict[str, Any]], str]:
    """Return (modes, backend) for a given source. Modes: {width,height,fps,fourcc,label}."""
    if not isinstance(source, int):
        return [], "none"

    if platform.system() == "Darwin":
        try:
            from hardware.macos_camera_modes import list_modes_for_unique_id
            from hardware.macos_camera_registry import refresh_macos_cameras as _refresh

            cam = next((c for c in _refresh() if c.index == source), None)
            unique_id = cam.path if (cam is not None and isinstance(cam.path, str)) else None
            if unique_id:
                modes = list_modes_for_unique_id(unique_id)
                return (
                    [
                        {
                            "width": m.width,
                            "height": m.height,
                            "fps": int(round(m.max_fps)),
                            "fourcc": _avf_to_opencv_fourcc(m.fourcc),
                            "native_fourcc": m.fourcc,
                        }
                        for m in modes
                    ],
                    "avfoundation",
                )
        except Exception:
            pass

    # Fallback: probe common modes
    common = [
        (640, 480),
        (800, 600),
        (1024, 768),
        (1280, 720),
        (1280, 960),
        (1600, 1200),
        (1920, 1080),
        (2048, 1536),
        (2560, 1440),
        (2592, 1944),
        (3840, 2160),
    ]
    return (
        [
            {"width": w, "height": h, "fps": 30, "fourcc": "MJPG", "native_fourcc": "MJPG"}
            for (w, h) in common
        ],
        "probe-fallback",
    )


def _avf_to_opencv_fourcc(native: str) -> str:
    """AVFoundation subtype → OpenCV fourcc hint. 420v/420f/yuvs → MJPG (USB cams compress)."""
    native = (native or "").strip()
    if native in {"420v", "420f", "yuvs", "YUY2", "YUYV", "MJPG"}:
        # Prefer MJPG for maximum FPS at high res on USB UVC cams
        return "MJPG"
    return "MJPG"


class CaptureModePayload(BaseModel):
    width: int
    height: int
    fps: int | None = None
    fourcc: str | None = None


@router.get("/api/cameras/capture-modes/{role}")
def get_camera_capture_modes(role: str) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        return {
            "ok": True,
            "role": role,
            "source": None,
            "supported": False,
            "modes": [],
            "current": None,
            "message": "No camera is assigned to this role.",
        }

    if isinstance(source, str):
        return {
            "ok": True,
            "role": role,
            "source": source,
            "supported": False,
            "modes": [],
            "current": None,
            "message": "Resolution selection is not available for network-stream cameras.",
        }

    modes, backend = _capture_modes_for_source(source)
    svc = shared_state.camera_service
    current: Dict[str, Any] | None = None
    if svc is not None and hasattr(svc, "get_capture_mode_for_role"):
        current = svc.get_capture_mode_for_role(role)
    if current is None:
        saved_entry = _camera_config_value(config, "camera_capture_modes", role)
        if isinstance(saved_entry, dict):
            current = {
                "width": int(saved_entry.get("width", 0)) or None,
                "height": int(saved_entry.get("height", 0)) or None,
                "fps": int(saved_entry.get("fps", 0)) or None,
                "fourcc": saved_entry.get("fourcc") if isinstance(saved_entry.get("fourcc"), str) else None,
            }

    # Enrich current with actual live resolution from telemetry
    live: Dict[str, Any] | None = None
    if svc is not None:
        device = svc.get_device(role) if hasattr(svc, "get_device") else None
        if device is not None:
            try:
                telemetry = device.capture_thread.getTelemetrySnapshot()
                res = telemetry.get("resolution")
                if isinstance(res, tuple) and len(res) == 2:
                    live = {
                        "width": int(res[0]),
                        "height": int(res[1]),
                        "fps": int(round(float(telemetry.get("fps", 0)))) or None,
                    }
            except Exception:
                pass

    return {
        "ok": True,
        "role": role,
        "source": source,
        "supported": bool(modes),
        "backend": backend,
        "modes": modes,
        "current": current,
        "live": live,
    }


@router.post("/api/cameras/capture-modes/{role}")
def save_camera_capture_mode(role: str, payload: CaptureModePayload) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    if payload.width <= 0 or payload.height <= 0:
        raise HTTPException(status_code=400, detail="Width and height must be positive.")

    params_path, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if not isinstance(source, int):
        raise HTTPException(status_code=400, detail="Resolution selection requires a USB camera.")

    modes, _ = _capture_modes_for_source(source)
    mode_match = next(
        (m for m in modes if m["width"] == payload.width and m["height"] == payload.height),
        None,
    )
    if mode_match is None:
        raise HTTPException(
            status_code=400,
            detail=f"Resolution {payload.width}x{payload.height} is not supported by this camera.",
        )

    fps = int(payload.fps) if payload.fps else int(mode_match["fps"])
    fourcc = (payload.fourcc or mode_match["fourcc"] or "MJPG").upper()[:4]

    entry = {"width": int(payload.width), "height": int(payload.height), "fps": fps, "fourcc": fourcc}
    capture_modes = config.get("camera_capture_modes", {})
    if not isinstance(capture_modes, dict):
        capture_modes = {}
    config_role = stored_camera_role_key(role, config)
    if config_role == "classification_channel":
        capture_modes.pop("carousel", None)
    elif config_role == "carousel":
        capture_modes.pop("classification_channel", None)
    capture_modes[config_role] = entry
    config["camera_capture_modes"] = capture_modes

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    svc = shared_state.camera_service
    applied_live = False
    if svc is not None and hasattr(svc, "set_capture_mode_for_role"):
        try:
            applied_live = svc.set_capture_mode_for_role(
                role, width=entry["width"], height=entry["height"], fps=fps, fourcc=fourcc
            )
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "source": source,
        "mode": entry,
        "persisted": True,
        "applied_live": applied_live,
        "message": "Capture mode saved. Camera will reopen at the new resolution.",
    }


# ---------------------------------------------------------------------------
# Calibrate from target
# ---------------------------------------------------------------------------


@router.post("/api/cameras/device-settings/{role}/calibrate-target")
def start_camera_device_settings_calibration_from_target(
    role: str,
    payload: CameraCalibrationStartPayload | None = None,
) -> Dict[str, Any]:
    current_response = get_camera_device_settings(role)
    source = current_response.get("source")
    provider = str(current_response.get("provider") or "unknown")
    method = _normalize_camera_calibration_method(payload.method if payload is not None else None)
    openrouter_model = _normalize_llm_calibration_model(payload.openrouter_model if payload is not None else None)
    max_iterations = _normalize_llm_calibration_iterations(payload.max_iterations if payload is not None else None)
    apply_color_profile = True
    if payload is not None and payload.apply_color_profile is not None:
        apply_color_profile = bool(payload.apply_color_profile)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")
    if not bool(current_response.get("supported")):
        raise HTTPException(status_code=400, detail=current_response.get("message") or "This camera cannot be calibrated through the current control backend.")
    if method == CALIBRATION_METHOD_LLM_GUIDED and not os.getenv("OPENROUTER_API_KEY"):
        raise HTTPException(status_code=400, detail="OpenRouter API key is required for LLM-guided calibration.")

    task_id = _create_camera_calibration_task(
        role,
        provider,
        source,
        method=method,
        openrouter_model=openrouter_model if method == CALIBRATION_METHOD_LLM_GUIDED else None,
        apply_color_profile=apply_color_profile,
    )
    thread = threading.Thread(
        target=_run_camera_calibration_task,
        args=(task_id, role),
        kwargs={
            "method": method,
            "openrouter_model": openrouter_model if method == CALIBRATION_METHOD_LLM_GUIDED else None,
            "max_iterations": max_iterations,
            "apply_color_profile": apply_color_profile,
        },
        daemon=True,
    )
    thread.start()
    task = _get_camera_calibration_task(task_id)
    assert task is not None
    return {
        "ok": True,
        "started": True,
        "task_id": task_id,
        "role": role,
        "provider": provider,
        "source": source,
        "method": task.get("method"),
        "openrouter_model": task.get("openrouter_model"),
        "status": task.get("status"),
        "stage": task.get("stage"),
        "progress": task.get("progress"),
        "message": task.get("message"),
    }


@router.get("/api/cameras/device-settings/{role}/calibrate-target/{task_id}")
def get_camera_device_settings_calibration_task(role: str, task_id: str) -> Dict[str, Any]:
    task = _get_camera_calibration_task(task_id)
    if task is None or task.get("role") != role:
        raise HTTPException(status_code=404, detail="Calibration task not found.")
    return {
        "ok": True,
        "task_id": task_id,
        "role": role,
        "provider": task.get("provider"),
        "source": task.get("source"),
        "method": task.get("method"),
        "openrouter_model": task.get("openrouter_model"),
        "status": task.get("status"),
        "stage": task.get("stage"),
        "progress": task.get("progress"),
        "message": task.get("message"),
        "result": task.get("result"),
        "analysis_preview": task.get("analysis_preview"),
        "advisor_trace": task.get("advisor_trace"),
        "error": task.get("error"),
    }


# ---------------------------------------------------------------------------
# Calibration debug gallery
# ---------------------------------------------------------------------------


@router.get("/api/cameras/device-settings/{role}/calibrate-target/{task_id}/gallery")
def get_calibration_gallery(role: str, task_id: str) -> Dict[str, Any]:
    """List all frames saved during a calibration run."""
    gallery_dir = Path("/tmp/calibration-gallery") / task_id
    if not gallery_dir.exists():
        raise HTTPException(status_code=404, detail="Gallery not found for this calibration task.")

    entries: list[Dict[str, Any]] = []
    for json_path in sorted(gallery_dir.glob("*.json")):
        try:
            meta = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        image_name = json_path.stem + ".jpg"
        image_path = gallery_dir / image_name
        if not image_path.exists():
            continue
        entries.append({
            "filename": image_name,
            "image_url": f"/api/cameras/device-settings/{role}/calibrate-target/{task_id}/gallery/{image_name}",
            **meta,
        })

    return {"ok": True, "task_id": task_id, "entries": entries}


@router.get("/api/cameras/device-settings/{role}/calibrate-target/{task_id}/gallery/{filename}")
def get_calibration_gallery_image(role: str, task_id: str, filename: str) -> StreamingResponse:
    """Serve a single saved calibration frame."""
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    image_path = Path("/tmp/calibration-gallery") / task_id / filename
    if not image_path.exists() or not image_path.suffix == ".jpg":
        raise HTTPException(status_code=404, detail="Image not found.")
    return StreamingResponse(
        open(image_path, "rb"),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )
