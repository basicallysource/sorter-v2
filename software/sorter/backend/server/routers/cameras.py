"""Router for camera-related endpoints.

Covers camera config, listing, streaming, assignment, picture settings,
device settings, calibration, and baseline capture.
"""

from __future__ import annotations

import json
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
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from blob_manager import BLOB_DIR, getCameraSetup, getChannelPolygons, getClassificationPolygons
from hardware.macos_camera_registry import refresh_macos_cameras
from irl.bin_layout import getBinLayout
from irl.config import (
    cameraColorProfileToDict,
    cameraDeviceSettingsToDict,
    cameraPictureSettingsToDict,
    parseCameraColorProfile,
    parseCameraDeviceSettings,
    parseCameraPictureSettings,
)
from server import shared_state
from server.camera_calibration import (
    analyze_color_plate_target,
    generate_color_profile_from_analysis,
)
from server.camera_discovery import getDiscoveredCameraStreams

router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAMERA_SETUP_ROLES = {
    "feeder",
    "c_channel_2",
    "c_channel_3",
    "carousel",
    "classification_top",
    "classification_bottom",
}

_DASHBOARD_CROP_PADDING_FACTOR = 0.14
_DASHBOARD_CROP_MIN_PADDING_PX = 48.0
_DASHBOARD_QUAD_PADDING_FACTOR = 0.1


from server.config_helpers import (
    machine_params_path as _camera_params_path,
    read_machine_params_config as _read_machine_params_config,
    toml_value as _toml_value,
    write_machine_params_config as _write_machine_params_config,
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


def _get_camera_color_profile_table(config: Dict[str, Any]) -> Dict[str, Any]:
    profiles = config.get("camera_color_profiles", {})
    return profiles if isinstance(profiles, dict) else {}


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
        source = _normalized_source(cameras.get(role))
        if source is not None:
            return source

    if role in {"feeder", "classification_top", "classification_bottom"}:
        camera_setup = getCameraSetup()
        if isinstance(camera_setup, dict):
            fallback_source = _normalized_source(camera_setup.get(role))
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


def _live_usb_device_controls(
    role: str,
    source: int,
    saved_settings: Dict[str, int | float | bool],
) -> tuple[List[Dict[str, Any]], Dict[str, int | float | bool]]:
    from vision.camera import probe_camera_device_controls

    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "getCaptureThreadForRole"):
        try:
            capture = shared_state.vision_manager.getCaptureThreadForRole(role)
        except Exception:
            capture = None
        if capture is not None and hasattr(capture, "describeDeviceControls"):
            try:
                controls, live_settings = capture.describeDeviceControls()
                if controls:
                    return controls, cameraDeviceSettingsToDict(live_settings)
            except Exception:
                pass

    controls, current_settings = probe_camera_device_controls(source, saved_settings)
    return controls, cameraDeviceSettingsToDict(current_settings)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _quantize_numeric_value(value: float, min_value: float, step: float | None) -> float:
    if not isinstance(step, (int, float)) or step <= 0:
        return float(value)
    return float(min_value + round((value - min_value) / float(step)) * float(step))


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


def _picture_settings_for_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    picture_settings = _get_picture_settings_table(config)
    return cameraPictureSettingsToDict(parseCameraPictureSettings(picture_settings.get(role)))


def _camera_color_profile_for_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    profiles = _get_camera_color_profile_table(config)
    return cameraColorProfileToDict(parseCameraColorProfile(profiles.get(role)))


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
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    preview_started_at = time.time()
    preview = preview_camera_device_settings(role, settings)
    preview_settings = preview.get("settings", settings)
    if isinstance(source, str):
        applied_settings = dict(preview_settings) if isinstance(preview_settings, dict) else dict(settings)
        time.sleep(1.35)
    else:
        applied_settings = cameraDeviceSettingsToDict(
            parseCameraDeviceSettings(preview_settings)
        )
        time.sleep(0.35)
    frame = _capture_frame_for_calibration(
        role,
        source,
        after_timestamp=preview_started_at,
        fallback_settings=applied_settings,
    )
    if frame is None:
        return applied_settings, None
    analysis = analyze_color_plate_target(frame)
    return applied_settings, analysis.to_dict() if analysis is not None else None


# ---------------------------------------------------------------------------
# Camera opening helpers
# ---------------------------------------------------------------------------


def _open_camera(index: int) -> cv2.VideoCapture:
    if platform.system() == "Darwin":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


def _open_camera_source(source: int | str) -> cv2.VideoCapture:
    if isinstance(source, int):
        return _open_camera(source)
    return cv2.VideoCapture(source)


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
# Calibration analysis helpers
# ---------------------------------------------------------------------------


def _analysis_number(analysis: Dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    if not isinstance(analysis, dict):
        return default
    value = analysis.get(key)
    return float(value) if isinstance(value, (int, float)) else default


def _analysis_neutral_mean_bgr(analysis: Dict[str, Any] | None) -> tuple[float, float, float] | None:
    if not isinstance(analysis, dict):
        return None
    value = analysis.get("neutral_mean_bgr")
    if not isinstance(value, list) or len(value) != 3:
        return None
    if not all(isinstance(channel, (int, float)) for channel in value):
        return None
    return float(value[0]), float(value[1]), float(value[2])


def _exposure_direction(analysis: Dict[str, Any] | None) -> int:
    white_luma = _analysis_number(analysis, "white_luma_mean")
    black_luma = _analysis_number(analysis, "black_luma_mean")
    clipped = _analysis_number(analysis, "clipped_white_fraction")
    if clipped >= 0.03 or white_luma >= 210.0:
        return 1
    if white_luma <= 165.0 and black_luma <= 28.0:
        return -1
    if white_luma <= 180.0:
        return -1
    return 0


def _white_balance_direction(analysis: Dict[str, Any] | None) -> int:
    neutral_bgr = _analysis_neutral_mean_bgr(analysis)
    if neutral_bgr is None:
        return 0
    blue, green, red = neutral_bgr
    if green <= 1e-6:
        return 0
    bias = (red - blue) / green
    if abs(bias) <= 0.035:
        return 0
    return -1 if bias > 0 else 1


def _camera_analysis_score(analysis: Dict[str, Any] | None) -> float:
    if not isinstance(analysis, dict):
        return float("-inf")
    value = analysis.get("score")
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def _calibration_selection_value(analysis: Dict[str, Any] | None) -> float:
    score = _camera_analysis_score(analysis)
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


# ---------------------------------------------------------------------------
# Calibration task management
# ---------------------------------------------------------------------------


def _create_camera_calibration_task(
    role: str,
    provider: str,
    source: int | str | None,
) -> str:
    task_id = uuid4().hex
    task = {
        "task_id": task_id,
        "role": role,
        "provider": provider,
        "source": source,
        "status": "queued",
        "stage": "queued",
        "message": "Queued camera calibration.",
        "progress": 0.0,
        "result": None,
        "analysis_preview": None,
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with shared_state.camera_calibration_tasks_lock:
        shared_state.camera_calibration_tasks[task_id] = task
    return task_id


def _update_camera_calibration_task(task_id: str, **updates: Any) -> None:
    with shared_state.camera_calibration_tasks_lock:
        task = shared_state.camera_calibration_tasks.get(task_id)
        if task is None:
            return
        task.update(updates)
        task["updated_at"] = time.time()


def _get_camera_calibration_task(task_id: str) -> Dict[str, Any] | None:
    with shared_state.camera_calibration_tasks_lock:
        task = shared_state.camera_calibration_tasks.get(task_id)
        return dict(task) if task is not None else None


# ---------------------------------------------------------------------------
# USB camera calibration
# ---------------------------------------------------------------------------


def _calibrate_usb_camera_device_settings(
    role: str,
    source: int,
    controls: List[Dict[str, Any]],
    current_settings: Dict[str, int | float | bool],
    *,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
) -> tuple[Dict[str, int | float | bool], Dict[str, Any]]:
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
    defaults = _usb_control_defaults(controls, current_settings)
    primary_keys = {
        "auto_exposure",
        "exposure",
        "gain",
        "auto_white_balance",
        "white_balance_temperature",
        "power_line_frequency",
        "backlight_compensation",
        "sharpness",
    }
    baseline_candidate = dict(defaults or current_settings)
    for key in primary_keys:
        if key in current_settings:
            baseline_candidate[key] = current_settings[key]
    if auto_exposure_control is not None:
        baseline_candidate["auto_exposure"] = False
    if auto_wb_control is not None:
        baseline_candidate["auto_white_balance"] = False
    initial_candidates: List[Dict[str, int | float | bool]] = [baseline_candidate]

    best_settings: Dict[str, int | float | bool] | None = None
    best_analysis: Dict[str, Any] | None = None

    # Discovery sweep steps (used if baseline fails to find the card).
    # We sweep exposure first (9 steps), then gain (5 steps) if still not found.
    brightness_control = control_by_key.get("brightness")
    discovery_exposure_steps = 9 if exposure_control is not None else 0
    discovery_gain_steps = 5 if gain_control is not None else 0
    discovery_brightness_steps = 5 if brightness_control is not None and exposure_control is None and gain_control is None else 0
    discovery_total = discovery_exposure_steps + discovery_gain_steps + discovery_brightness_steps
    total_steps = max(
        1,
        len(initial_candidates)
        + discovery_total
        + (8 if exposure_control is not None else 0)
        + (5 if gain_control is not None and exposure_control is None else 0)
        + (8 if wb_control is not None else 0),
    )
    completed_steps = 0

    def consider(
        candidate: Dict[str, int | float | bool],
        *,
        stage: str,
        message: str,
    ) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
        nonlocal best_settings, best_analysis, completed_steps
        completed_steps += 1
        applied_settings, analysis = _analyze_candidate_settings(role, source, candidate)
        progress = min(0.9, completed_steps / total_steps)
        if report_progress is not None:
            report_progress(stage, progress, message, analysis)
        if analysis is None:
            return applied_settings, None
        if best_analysis is None or _calibration_selection_value(analysis) > _calibration_selection_value(best_analysis):
            best_settings = dict(applied_settings)
            best_analysis = analysis
            if report_progress is not None:
                report_progress(stage, progress, message, analysis)
        return applied_settings, analysis

    for index, candidate in enumerate(initial_candidates, start=1):
        consider(
            candidate,
            stage="baseline",
            message=f"Analyzing baseline candidate {index} of {len(initial_candidates)}.",
        )

    # If the baseline failed to find the card, sweep through exposure and gain
    # values to discover a setting where the card is visible.
    if best_settings is None or best_analysis is None:
        discovery_found = False

        def _sweep_control(
            control: Dict[str, Any] | None,
            key: str,
            steps: int,
            label: str,
            base: Dict[str, int | float | bool],
        ) -> bool:
            nonlocal discovery_found
            if control is None or steps <= 0 or discovery_found:
                return False
            c_min = _as_number(control.get("min"))
            c_max = _as_number(control.get("max"))
            c_step = _as_number(control.get("step"))
            if c_min is None or c_max is None:
                return False
            for idx, val in enumerate(np.linspace(c_min, c_max, num=steps).tolist(), start=1):
                cand = dict(base)
                cand[key] = int(round(_quantize_numeric_value(val, c_min, c_step))) if c_step is not None and c_step >= 1 else float(_quantize_numeric_value(val, c_min, c_step))
                if auto_exposure_control is not None:
                    cand["auto_exposure"] = False
                _, analysis = consider(
                    cand,
                    stage="discovery",
                    message=f"Searching for calibration target — {label} {idx}/{steps}.",
                )
                if analysis is not None:
                    discovery_found = True
                    return True
            return False

        # Sweep exposure across full range
        _sweep_control(exposure_control, "exposure", discovery_exposure_steps, "exposure", baseline_candidate)
        # If still not found, sweep gain too
        if not discovery_found:
            _sweep_control(gain_control, "gain", discovery_gain_steps, "gain", best_settings or baseline_candidate)
        # Last resort: brightness (only if neither exposure nor gain exist)
        if not discovery_found:
            _sweep_control(brightness_control, "brightness", discovery_brightness_steps, "brightness", baseline_candidate)

    if best_settings is None or best_analysis is None:
        raise HTTPException(
            status_code=400,
            detail="Calibration target not found. Make sure the 6-color calibration plate is fully visible and not clipped.",
        )

    if exposure_control is not None:
        exposure_min = _as_number(exposure_control.get("min"))
        exposure_max = _as_number(exposure_control.get("max"))
        current_exposure = _as_number(best_settings.get("exposure"))
        if exposure_min is not None and exposure_max is not None and current_exposure is not None:
            low = exposure_min
            high = exposure_max
            trial = float(
                _quantize_numeric_value(
                    max(exposure_min, min(exposure_max, current_exposure)),
                    exposure_min,
                    _as_number(exposure_control.get("step")),
                )
            )
            last_trial: float | None = None
            for index in range(8):
                candidate = dict(best_settings)
                candidate["exposure"] = trial
                if auto_exposure_control is not None:
                    candidate["auto_exposure"] = False
                _, analysis = consider(
                    candidate,
                    stage="exposure_search",
                    message=f"Evaluating exposure candidate {index + 1} of 8.",
                )
                if analysis is None:
                    break
                direction = _exposure_direction(analysis)
                if direction > 0:
                    high = min(high, trial)
                elif direction < 0:
                    low = max(low, trial)
                else:
                    break
                if high <= low:
                    break
                next_trial = float(np.sqrt(low * high)) if low > 0 else float((low + high) / 2.0)
                next_trial = float(
                    _quantize_numeric_value(
                        max(exposure_min, min(exposure_max, next_trial)),
                        exposure_min,
                        _as_number(exposure_control.get("step")),
                    )
                )
                if last_trial is not None and abs(next_trial - last_trial) < 1e-6:
                    break
                last_trial = trial
                trial = next_trial
    elif gain_control is not None:
        gain_values = _focused_numeric_control_candidates(
            gain_control,
            best_settings.get("gain"),
            count=5,
            linear_span_fraction=0.12,
        )
        for index, gain_value in enumerate(gain_values, start=1):
            candidate = dict(best_settings)
            candidate["gain"] = gain_value
            consider(
                candidate,
                stage="exposure_search",
                message=f"Evaluating gain candidate {index} of {len(gain_values)}.",
            )

    if wb_control is not None:
        wb_min = _as_number(wb_control.get("min"))
        wb_max = _as_number(wb_control.get("max"))
        current_wb = _as_number(best_settings.get("white_balance_temperature"))
        if wb_min is not None and wb_max is not None and current_wb is not None:
            low = wb_min
            high = wb_max
            trial = float(
                _quantize_numeric_value(
                    max(wb_min, min(wb_max, current_wb)),
                    wb_min,
                    _as_number(wb_control.get("step")),
                )
            )
            last_trial: float | None = None
            for index in range(8):
                candidate = dict(best_settings)
                candidate["white_balance_temperature"] = trial
                if auto_wb_control is not None:
                    candidate["auto_white_balance"] = False
                _, analysis = consider(
                    candidate,
                    stage="white_balance_search",
                    message=f"Evaluating white balance candidate {index + 1} of 8.",
                )
                if analysis is None:
                    break
                direction = _white_balance_direction(analysis)
                if direction > 0:
                    low = max(low, trial)
                elif direction < 0:
                    high = min(high, trial)
                else:
                    break
                if high <= low:
                    break
                next_trial = float((low + high) / 2.0)
                next_trial = float(
                    _quantize_numeric_value(
                        max(wb_min, min(wb_max, next_trial)),
                        wb_min,
                        _as_number(wb_control.get("step")),
                    )
                )
                if last_trial is not None and abs(next_trial - last_trial) < 1e-6:
                    break
                last_trial = trial
                trial = next_trial

    if best_settings is None or best_analysis is None:
        raise HTTPException(status_code=400, detail="Calibration failed to find usable settings.")

    return best_settings, best_analysis


# ---------------------------------------------------------------------------
# Android camera calibration
# ---------------------------------------------------------------------------


def _calibrate_android_camera_device_settings(
    role: str,
    source: str,
    current_settings: Dict[str, Any],
    capabilities: Dict[str, Any],
    *,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
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
        applied_settings, analysis = _analyze_candidate_settings(role, source, candidate)
        if analysis is None:
            return
        if best_analysis is None or _calibration_selection_value(analysis) > _calibration_selection_value(best_analysis):
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


# ---------------------------------------------------------------------------
# Synchronous calibration runner
# ---------------------------------------------------------------------------


def _run_camera_calibration_sync(
    role: str,
    *,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
) -> Dict[str, Any]:
    current_response = get_camera_device_settings(role)
    source = current_response.get("source")
    provider = current_response.get("provider")
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")
    if not bool(current_response.get("supported")):
        raise HTTPException(status_code=400, detail=current_response.get("message") or "This camera cannot be calibrated through the current control backend.")

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
        if provider == "usb-opencv":
            controls = current_response.get("controls")
            if not isinstance(controls, list) or not isinstance(source, int):
                raise HTTPException(status_code=400, detail="USB camera controls are not available for calibration.")
            if report_progress is not None:
                report_progress("preparing", 0.05, "Preparing USB camera calibration.", None)
            best_settings, analysis = _calibrate_usb_camera_device_settings(
                role,
                source,
                controls,
                original_settings,
                report_progress=report_progress,
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

        if report_progress is not None:
            report_progress("profile_generation", 0.95, "Generating a color correction profile from the target plate.", analysis)
        raw_frame = _capture_frame_for_calibration(
            role,
            source,
            fallback_settings=best_settings,
        )
        raw_analysis_obj = analyze_color_plate_target(raw_frame) if raw_frame is not None else None
        raw_analysis = raw_analysis_obj.to_dict() if raw_analysis_obj is not None else analysis
        profile_payload = generate_color_profile_from_analysis(raw_analysis)
        if profile_payload is None:
            raise HTTPException(
                status_code=400,
                detail="Calibration found the target, but could not generate a color profile from it.",
            )

        profile_saved = _save_camera_color_profile(role, profile_payload)

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

            final_frame = apply_camera_color_profile(
                final_frame,
                parseCameraColorProfile(profile_saved.get("profile")),
            )
            final_frame = apply_picture_settings(
                final_frame,
                parseCameraPictureSettings(original_picture_settings),
            )

        final_analysis = analyze_color_plate_target(final_frame) if final_frame is not None else None
        chosen_analysis = final_analysis.to_dict() if final_analysis is not None else raw_analysis
        result = {
            **saved,
            "color_profile": profile_saved.get("profile"),
            "analysis": chosen_analysis,
            "message": "Camera calibrated from the 6-color target plate, and a color profile was generated.",
        }
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


def _run_camera_calibration_task(task_id: str, role: str) -> None:
    def report_progress(stage: str, progress: float, message: str, analysis: Dict[str, Any] | None = None) -> None:
        _update_camera_calibration_task(
            task_id,
            status="running" if stage != "completed" else "completed",
            stage=stage,
            progress=max(0.0, min(1.0, float(progress))),
            message=message,
            analysis_preview=analysis,
        )

    try:
        _update_camera_calibration_task(
            task_id,
            status="running",
            stage="starting",
            progress=0.01,
            message="Starting camera calibration.",
        )
        result = _run_camera_calibration_sync(role, report_progress=report_progress)
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


def _save_camera_color_profile(
    role: str,
    payload: Dict[str, Any] | None,
) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")

    params_path, config = _read_machine_params_config()
    parsed = parseCameraColorProfile(payload)
    profile_dict = cameraColorProfileToDict(parsed)
    profiles = _get_camera_color_profile_table(config)
    if parsed.enabled:
        profiles[role] = profile_dict
    else:
        profiles.pop(role, None)
    config["camera_color_profiles"] = profiles

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    applied_live = False
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setColorProfileForRole"):
        try:
            applied_live = bool(shared_state.vision_manager.setColorProfileForRole(role, parsed))
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "profile": profile_dict,
        "applied_live": applied_live,
    }


def _restore_preview_settings(role: str, settings: Dict[str, int | float | bool]) -> None:
    try:
        preview_camera_device_settings(role, settings)
    except Exception:
        pass


def _restore_camera_color_profile(role: str, profile: Dict[str, Any]) -> None:
    try:
        _save_camera_color_profile(role, profile)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class CameraAssignment(BaseModel):
    layout: Optional[str] = None
    feeder: Optional[int | str] = None
    c_channel_2: Optional[int | str] = None
    c_channel_3: Optional[int | str] = None
    carousel: Optional[int | str] = None
    classification_top: Optional[int | str] = None
    classification_bottom: Optional[int | str] = None


class CameraLayoutPayload(BaseModel):
    layout: str


class CameraPictureSettingsPayload(BaseModel):
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False


# ===================================================================
# Routes
# ===================================================================


# ---------------------------------------------------------------------------
# Video feed (MJPEG from VisionManager)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Camera config / list / stream / feed / assign
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
        return {
            "layout": cameras.get("layout", "default"),
            "feeder": _camera_source_for_role(raw, "feeder"),
            "c_channel_2": _camera_source_for_role(raw, "c_channel_2"),
            "c_channel_3": _camera_source_for_role(raw, "c_channel_3"),
            "carousel": _camera_source_for_role(raw, "carousel"),
            "classification_top": _camera_source_for_role(raw, "classification_top"),
            "classification_bottom": _camera_source_for_role(raw, "classification_bottom"),
        }
    except HTTPException:
        return {
            "layout": "default",
            "feeder": None,
            "c_channel_2": None,
            "c_channel_3": None,
            "carousel": None,
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

    return get_camera_config()


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


@router.get("/api/cameras/stream/{index}")
def camera_stream(index: int):
    """MJPEG stream for a single camera by index (thumbnail)."""
    def generate():
        cap = _open_camera(index)
        if not cap.isOpened():
            return
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                thumb = cv2.resize(frame, (426, 240))
                _, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 60])
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                )
        finally:
            cap.release()

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


def _dashboard_polygon_resolution(saved: Dict[str, Any] | None) -> tuple[float, float]:
    if not isinstance(saved, dict):
        return (1920.0, 1080.0)
    resolution = saved.get("resolution")
    if isinstance(resolution, (list, tuple)) and len(resolution) >= 2:
        width = _as_number(resolution[0])
        height = _as_number(resolution[1])
        if width and width > 0 and height and height > 0:
            return (width, height)
    return (1920.0, 1080.0)


def _dashboard_points(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, (list, tuple)):
        return []
    points: list[tuple[float, float]] = []
    for point in raw:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x = _as_number(point[0])
        y = _as_number(point[1])
        if x is None or y is None:
            continue
        points.append((float(x), float(y)))
    return points


def _dashboard_quad_points(raw: Any) -> list[tuple[float, float]]:
    if not isinstance(raw, dict):
        return []
    return _dashboard_points(raw.get("corners"))


def _scale_dashboard_points(
    points: list[tuple[float, float]],
    source_resolution: tuple[float, float],
    frame_w: int,
    frame_h: int,
) -> np.ndarray | None:
    if len(points) < 3:
        return None
    src_w, src_h = source_resolution
    if src_w <= 0 or src_h <= 0 or frame_w <= 0 or frame_h <= 0:
        return None
    scaled = np.array(points, dtype=np.float32)
    scaled[:, 0] *= float(frame_w) / float(src_w)
    scaled[:, 1] *= float(frame_h) / float(src_h)
    return scaled


def _dashboard_padded_bbox(
    polygons: list[np.ndarray],
    frame_w: int,
    frame_h: int,
) -> tuple[int, int, int, int] | None:
    if not polygons:
        return None
    merged = np.concatenate(polygons, axis=0)
    min_x = float(np.min(merged[:, 0]))
    min_y = float(np.min(merged[:, 1]))
    max_x = float(np.max(merged[:, 0]))
    max_y = float(np.max(merged[:, 1]))
    width = max(1.0, max_x - min_x)
    height = max(1.0, max_y - min_y)
    pad_x = max(_DASHBOARD_CROP_MIN_PADDING_PX, width * _DASHBOARD_CROP_PADDING_FACTOR)
    pad_y = max(_DASHBOARD_CROP_MIN_PADDING_PX, height * _DASHBOARD_CROP_PADDING_FACTOR)
    x1 = max(0, int(np.floor(min_x - pad_x)))
    y1 = max(0, int(np.floor(min_y - pad_y)))
    x2 = min(frame_w, int(np.ceil(max_x + pad_x)))
    y2 = min(frame_h, int(np.ceil(max_y + pad_y)))
    if x2 <= x1 or y2 <= y1:
        return None
    return (x1, y1, x2, y2)


def _dashboard_expand_quad(quad: np.ndarray) -> np.ndarray:
    # Expand the quad along its *own* local axes (width direction = u, height
    # direction = v) rather than radially from the centroid. Radial expansion
    # gives non-uniform padding on the two axes for non-square quads – a tall
    # quad ends up with far less horizontal padding than vertical, which is
    # why classification previews appeared clipped on the left/right sides.
    width_top_vec = quad[1] - quad[0]
    width_bottom_vec = quad[2] - quad[3]
    height_right_vec = quad[2] - quad[1]
    height_left_vec = quad[3] - quad[0]

    avg_width_vec = (width_top_vec + width_bottom_vec) / 2.0
    avg_height_vec = (height_right_vec + height_left_vec) / 2.0
    avg_width_len = float(np.linalg.norm(avg_width_vec))
    avg_height_len = float(np.linalg.norm(avg_height_vec))

    if avg_width_len <= 1e-6 or avg_height_len <= 1e-6:
        return quad.astype(np.float32)

    padding = max(
        _DASHBOARD_CROP_MIN_PADDING_PX,
        max(avg_width_len, avg_height_len) * _DASHBOARD_QUAD_PADDING_FACTOR,
    )

    u = (avg_width_vec / avg_width_len).astype(np.float32)
    v = (avg_height_vec / avg_height_len).astype(np.float32)

    # Each corner moves `padding` pixels outward along both local axes.
    signs = np.array(
        [
            [-1.0, -1.0],  # top-left
            [+1.0, -1.0],  # top-right
            [+1.0, +1.0],  # bottom-right
            [-1.0, +1.0],  # bottom-left
        ],
        dtype=np.float32,
    )

    expanded = quad.astype(np.float32).copy()
    for index in range(4):
        s_u, s_v = signs[index]
        expanded[index] = expanded[index] + (s_u * padding) * u + (s_v * padding) * v
    return expanded


def _dashboard_quad_size(quad: np.ndarray) -> tuple[int, int]:
    width_top = float(np.linalg.norm(quad[1] - quad[0]))
    width_bottom = float(np.linalg.norm(quad[2] - quad[3]))
    height_right = float(np.linalg.norm(quad[2] - quad[1]))
    height_left = float(np.linalg.norm(quad[3] - quad[0]))
    width = max(1, int(round(max(width_top, width_bottom))))
    height = max(1, int(round(max(height_right, height_left))))
    return (width, height)


def _dashboard_crop_spec(role: str, frame_w: int, frame_h: int) -> Dict[str, Any] | None:
    if role in {"feeder", "c_channel_2", "c_channel_3", "carousel"}:
        saved = getChannelPolygons() or {}
        source_resolution = _dashboard_polygon_resolution(saved)
        polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
        quad_table = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}

        if role == "carousel":
            quad_points = _dashboard_quad_points(quad_table.get("carousel"))
            if len(quad_points) != 4:
                quad_points = _dashboard_points(polygons_table.get("carousel"))
            scaled_quad = (
                _scale_dashboard_points(quad_points, source_resolution, frame_w, frame_h)
                if len(quad_points) == 4 else None
            )
            if scaled_quad is not None and len(scaled_quad) == 4:
                expanded_quad = _dashboard_expand_quad(scaled_quad)
                target_w, target_h = _dashboard_quad_size(expanded_quad)
                destination = np.array(
                    [[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
                    dtype=np.float32,
                )
                return {
                    "kind": "rectified",
                    "matrix": cv2.getPerspectiveTransform(expanded_quad.astype(np.float32), destination),
                    "size": (target_w, target_h),
                }

        polygon_keys = {
            "feeder": ["second_channel", "third_channel", "carousel"],
            "c_channel_2": ["second_channel"],
            "c_channel_3": ["third_channel"],
            "carousel": ["carousel"],
        }.get(role, [])
        scaled_polygons = [
            scaled
            for key in polygon_keys
            for scaled in [
                _scale_dashboard_points(
                    _dashboard_points(polygons_table.get(key)),
                    source_resolution,
                    frame_w,
                    frame_h,
                )
            ]
            if scaled is not None
        ]
        bbox = _dashboard_padded_bbox(scaled_polygons, frame_w, frame_h)
        return {"kind": "bbox", "bbox": bbox} if bbox is not None else None

    if role in {"classification_top", "classification_bottom"}:
        saved = getClassificationPolygons() or {}
        source_resolution = _dashboard_polygon_resolution(saved)
        polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
        quad_table = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
        quad_key = "class_top" if role == "classification_top" else "class_bottom"
        polygon_key = "top" if role == "classification_top" else "bottom"
        quad_points = _dashboard_quad_points(quad_table.get(quad_key))
        if len(quad_points) != 4:
            quad_points = _dashboard_points(polygons_table.get(polygon_key))
        scaled_quad = (
            _scale_dashboard_points(quad_points, source_resolution, frame_w, frame_h)
            if len(quad_points) == 4 else None
        )
        if scaled_quad is not None and len(scaled_quad) == 4:
            expanded_quad = _dashboard_expand_quad(scaled_quad)
            target_w, target_h = _dashboard_quad_size(expanded_quad)
            destination = np.array(
                [[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
                dtype=np.float32,
            )
            return {
                "kind": "rectified",
                "matrix": cv2.getPerspectiveTransform(expanded_quad.astype(np.float32), destination),
                "size": (target_w, target_h),
                "square": True,
            }

        scaled_polygon = _scale_dashboard_points(
            _dashboard_points(polygons_table.get(polygon_key)),
            source_resolution,
            frame_w,
            frame_h,
        )
        bbox = _dashboard_padded_bbox([scaled_polygon], frame_w, frame_h) if scaled_polygon is not None else None
        return {"kind": "bbox", "bbox": bbox, "square": True} if bbox is not None else None

    return None


def _dashboard_pad_square(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    if height <= 0 or width <= 0 or height == width:
        return frame
    target = max(height, width)
    pad_y = target - height
    pad_x = target - width
    top = pad_y // 2
    bottom = pad_y - top
    left = pad_x // 2
    right = pad_x - left
    return cv2.copyMakeBorder(frame, top, bottom, left, right, cv2.BORDER_REPLICATE)


def _apply_dashboard_crop(frame: np.ndarray, spec: Dict[str, Any] | None) -> np.ndarray:
    if not spec:
        return frame
    processed = frame
    if spec.get("kind") == "rectified":
        size = spec.get("size")
        matrix = spec.get("matrix")
        if not isinstance(size, tuple) or matrix is None:
            return frame
        processed = cv2.warpPerspective(
            frame,
            matrix,
            size,
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
    else:
        bbox = spec.get("bbox")
        if not isinstance(bbox, tuple) or len(bbox) != 4:
            return frame
        x1, y1, x2, y2 = [int(value) for value in bbox]
        if x2 <= x1 or y2 <= y1:
            return frame
        processed = frame[y1:y2, x1:x2]

    if spec.get("square"):
        processed = _dashboard_pad_square(processed)
    return processed


@router.get("/api/cameras/feed/{role}")
def camera_feed_by_role(
    role: str,
    annotated: bool = True,
    layer: str = "annotated",
    direct: bool = False,
    dashboard: bool = False,
):
    """MJPEG stream for a camera role.

    ``layer`` controls annotation: ``"annotated"`` (default) or ``"raw"``.
    The legacy ``annotated`` bool param is supported for backward compat.
    """
    from vision.camera import (
        apply_camera_color_profile,
        apply_camera_device_settings,
        apply_picture_settings,
    )
    from vision.outputs.mjpeg import MjpegOutput

    # Resolve layer — legacy `annotated` param maps into `layer`
    want_annotated = layer == "annotated" and annotated

    _, raw = _read_machine_params_config(require_exists=True)
    cameras_section = raw.get("cameras", {})
    picture_settings = parseCameraPictureSettings(_get_picture_settings_table(raw).get(role))
    color_profile = parseCameraColorProfile(_get_camera_color_profile_table(raw).get(role))
    saved_device_settings = parseCameraDeviceSettings(
        _get_camera_device_settings_table(raw).get(role)
    )
    preview_device_settings = shared_state.camera_device_preview_overrides.get(role)
    device_settings = cameraDeviceSettingsToDict(
        preview_device_settings if preview_device_settings is not None else saved_device_settings
    )
    source = cameras_section.get(role)
    if source is None or not isinstance(source, (int, str)):
        raise HTTPException(404, f"Camera role '{role}' not configured")

    encoder = MjpegOutput()

    cached_dashboard_shape: tuple[int, int] | None = None
    cached_dashboard_spec: Dict[str, Any] | None = None

    def _dashboard_frame(frame: np.ndarray) -> np.ndarray:
        nonlocal cached_dashboard_shape, cached_dashboard_spec
        if not dashboard:
            return frame
        frame_h, frame_w = frame.shape[:2]
        shape = (frame_w, frame_h)
        if cached_dashboard_shape != shape:
            cached_dashboard_spec = _dashboard_crop_spec(role, frame_w, frame_h)
            cached_dashboard_shape = shape
        return _apply_dashboard_crop(frame, cached_dashboard_spec)

    # Live path: use CameraService feed if available
    if not direct and shared_state.camera_service is not None:
        feed = shared_state.camera_service.get_feed(role)
        if feed is not None:
            def generate_live():
                while True:
                    frame_obj = feed.get_frame(annotated=want_annotated)
                    if frame_obj is None:
                        time.sleep(0.05)
                        continue
                    frame = (
                        frame_obj.annotated
                        if want_annotated and frame_obj.annotated is not None
                        else frame_obj.raw
                    )
                    frame = _dashboard_frame(frame)
                    yield encoder.encode_chunk(frame, quality=70)
                    time.sleep(0.03)

            return StreamingResponse(
                generate_live(),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

    def generate_direct():
        cap = _open_camera_source(source)
        if not cap.isOpened():
            return
        try:
            if isinstance(source, int) and device_settings:
                apply_camera_device_settings(cap, device_settings, source=source)
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frame = apply_camera_color_profile(frame, color_profile)
                frame = apply_picture_settings(frame, picture_settings)
                frame = _dashboard_frame(frame)
                yield encoder.encode_chunk(frame, quality=70)
        finally:
            cap.release()

    return StreamingResponse(
        generate_direct(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@router.post("/api/cameras/assign")
def assign_cameras(assignment: CameraAssignment) -> Dict[str, Any]:
    """Save camera role assignments to the machine TOML config."""
    params_path, config = _read_machine_params_config()

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
        elif any(role in updates for role in ("c_channel_2", "c_channel_3", "carousel")):
            cameras["layout"] = "split_feeder"
    for key, value in updates.items():
        if value is None:
            cameras.pop(key, None)
        else:
            cameras[key] = value
    config["cameras"] = cameras

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live: Dict[str, bool] = {}
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setCameraSourceForRole"):
        for key, value in updates.items():
            try:
                applied_live[key] = bool(shared_state.vision_manager.setCameraSourceForRole(key, value))
            except Exception:
                applied_live[key] = False

    return {
        "ok": True,
        "assignment": {
            "layout": cameras.get("layout", "default"),
            "feeder": cameras.get("feeder"),
            "c_channel_2": cameras.get("c_channel_2"),
            "c_channel_3": cameras.get("c_channel_3"),
            "carousel": cameras.get("carousel"),
            "classification_top": cameras.get("classification_top"),
            "classification_bottom": cameras.get("classification_bottom"),
        },
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
    picture_settings[role] = cameraPictureSettingsToDict(parsed)
    config["camera_picture_settings"] = picture_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live = False
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setPictureSettingsForRole"):
        try:
            applied_live = bool(shared_state.vision_manager.setPictureSettingsForRole(role, parsed))
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "settings": cameraPictureSettingsToDict(parsed),
        "applied_live": applied_live,
        "message": "Feed orientation saved.",
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
        parseCameraDeviceSettings(_get_camera_device_settings_table(config).get(role))
    )
    controls, live_settings = _live_usb_device_controls(role, source, saved_settings)
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
    applied_live = False
    applied_settings = dict(parsed)

    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setDeviceSettingsForRole"):
        try:
            live_result = shared_state.vision_manager.setDeviceSettingsForRole(role, parsed, persist=False)
            if live_result is not None:
                applied_settings = cameraDeviceSettingsToDict(live_result)
                shared_state.camera_device_preview_overrides[role] = dict(applied_settings)
                applied_live = True
        except Exception:
            applied_live = False

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
    if parsed:
        device_settings[role] = dict(parsed)
    else:
        device_settings.pop(role, None)
    config["camera_device_settings"] = device_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    shared_state.camera_device_preview_overrides[role] = dict(parsed)
    applied_live = False
    applied_settings = dict(parsed)
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setDeviceSettingsForRole"):
        try:
            live_result = shared_state.vision_manager.setDeviceSettingsForRole(role, parsed, persist=True)
            if live_result is not None:
                applied_settings = cameraDeviceSettingsToDict(live_result)
                shared_state.camera_device_preview_overrides[role] = dict(applied_settings)
                applied_live = True
        except Exception:
            applied_live = False

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
# Calibrate from target
# ---------------------------------------------------------------------------


@router.post("/api/cameras/device-settings/{role}/calibrate-target")
def start_camera_device_settings_calibration_from_target(role: str) -> Dict[str, Any]:
    current_response = get_camera_device_settings(role)
    source = current_response.get("source")
    provider = str(current_response.get("provider") or "unknown")
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")
    if not bool(current_response.get("supported")):
        raise HTTPException(status_code=400, detail=current_response.get("message") or "This camera cannot be calibrated through the current control backend.")

    task_id = _create_camera_calibration_task(role, provider, source)
    thread = threading.Thread(
        target=_run_camera_calibration_task,
        args=(task_id, role),
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
        "status": task.get("status"),
        "stage": task.get("stage"),
        "progress": task.get("progress"),
        "message": task.get("message"),
        "result": task.get("result"),
        "analysis_preview": task.get("analysis_preview"),
        "error": task.get("error"),
    }
