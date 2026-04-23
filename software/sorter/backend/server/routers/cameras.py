"""Router for camera-related endpoints.

Covers camera config, listing, streaming, assignment, picture settings,
device settings, calibration, and baseline capture.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import platform
import re
import threading
import time
from functools import lru_cache
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

from local_state import get_channel_polygons, get_classification_polygons
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
from server.detection_config.common import public_aux_scope as _public_aux_scope
from server.camera_calibration import (
    analyze_color_plate_target,
    generate_color_profile_from_analysis,
)
from server.camera_discovery import getDiscoveredCameraStreams
from server.services.camera_calibration.common import (
    CALIBRATION_METHOD_EXPOSURE_HISTOGRAM,
    CALIBRATION_METHOD_LLM_GUIDED,
    CALIBRATION_METHOD_TARGET_PLATE,
    DEFAULT_CAMERA_CALIBRATION_METHOD,
    as_number as _as_number,
    calibration_selection_value as _calibration_selection_value,
    camera_calibration_allowed_controls as _camera_calibration_allowed_controls,
    camera_calibration_analysis_summary as _camera_calibration_analysis_summary,
    capture_raw_frame as _capture_raw_frame,
    clamp_control as _clamp_control,
    cleanup_old_gallery_dirs as _cleanup_old_gallery_dirs,
    compute_calibration_neutral_baseline as _compute_calibration_neutral_baseline,
    create_camera_calibration_task as _create_camera_calibration_task,
    get_camera_calibration_task as _get_camera_calibration_task,
    normalize_camera_calibration_method as _normalize_camera_calibration_method,
    quantize_numeric_value as _quantize_numeric_value,
    update_camera_calibration_task as _update_camera_calibration_task,
)
from utils.polygon_resolution import saved_polygon_resolution

router = APIRouter()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CAMERA_SETUP_ROLES = {
    "feeder",
    "c_channel_2",
    "c_channel_3",
    "carousel",
    "classification_channel",
    "classification_top",
    "classification_bottom",
}

_DASHBOARD_CROP_PADDING_FACTOR = 0.14
_DASHBOARD_CROP_MIN_PADDING_PX = 48.0
_DASHBOARD_QUAD_PADDING_FACTOR = 0.1
EXPOSURE_HISTOGRAM_TARGET_LUMA = 128.0
EXPOSURE_HISTOGRAM_TOLERANCE_LUMA = 3.0
EXPOSURE_HISTOGRAM_MAX_ITERATIONS = 20
EXPOSURE_HISTOGRAM_P_GAIN = 1.4
EXPOSURE_HISTOGRAM_SETTLE_S = 0.35
DEFAULT_LLM_CALIBRATION_MODEL = "google/gemini-3.1-pro-preview"
DEFAULT_LLM_CALIBRATION_MAX_ITERATIONS = 10

logger = logging.getLogger(__name__)


from server.config_helpers import (
    read_machine_params_config as _read_machine_params_config,
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


def _camera_config_value(config: Dict[str, Any], table_name: str, role: str) -> Any:
    table = config.get(table_name, {})
    if not isinstance(table, dict):
        return None
    for lookup_role in lookup_camera_role_keys(role, config):
        if lookup_role in table:
            return table.get(lookup_role)
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
    return cameraPictureSettingsToDict(
        parseCameraPictureSettings(_camera_config_value(config, "camera_picture_settings", role))
    )


def _camera_color_profile_for_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    return cameraColorProfileToDict(
        parseCameraColorProfile(_camera_config_value(config, "camera_color_profiles", role))
    )


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
# Calibration analysis helpers
# ---------------------------------------------------------------------------


def _normalize_llm_calibration_model(value: str | None) -> str:
    try:
        from vision.gemini_sam_detector import SUPPORTED_OPENROUTER_MODELS
    except Exception:
        return DEFAULT_LLM_CALIBRATION_MODEL
    if isinstance(value, str):
        normalized = value.strip()
        if normalized in SUPPORTED_OPENROUTER_MODELS:
            return normalized
    return DEFAULT_LLM_CALIBRATION_MODEL


def _normalize_llm_calibration_iterations(value: int | None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_LLM_CALIBRATION_MAX_ITERATIONS
    # Hard ceiling at 10 — beyond that we're wasting tokens. Model is expected
    # to return status="done" as soon as exposure looks clean.
    return max(2, min(10, int(value)))


def _extract_openrouter_json(text: str) -> Dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        excerpt = re.sub(r"\s+", " ", text or "").strip()
        if len(excerpt) > 220:
            excerpt = excerpt[:217] + "..."
        raise RuntimeError(
            "Model response did not contain JSON."
            + (f" Response excerpt: {excerpt}" if excerpt else "")
        )
    raw = match.group()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", raw)
        parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise RuntimeError("Model response did not contain a JSON object.")
    return parsed


def _openrouter_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: List[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(str(item["text"]))
        return "\n".join(text_parts)
    return str(content or "")


def _frame_to_openrouter_jpeg(frame: np.ndarray, *, quality: int = 88) -> str:
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Failed to encode calibration frame for OpenRouter.")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


@lru_cache(maxsize=1)
def _llm_calibration_reference_image_b64() -> str | None:
    reference_path = Path(__file__).resolve().parents[3] / "frontend" / "static" / "setup" / "color-checker-reference.png"
    if not reference_path.exists():
        return None
    try:
        return base64.b64encode(reference_path.read_bytes()).decode("ascii")
    except OSError:
        return None


LLM_CALIBRATION_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "apply_camera_settings",
            "description": (
                "Apply one or more camera setting changes and capture a fresh frame "
                "for review. The system replies with the new frame and analyzer numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Short sentence explaining why these changes are being made.",
                    },
                    "changes": {
                        "type": "array",
                        "description": "List of setting changes to apply (max 3 per call).",
                        "items": {
                            "type": "object",
                            "properties": {
                                "key": {
                                    "type": "string",
                                    "description": "Setting key from the allowed_controls list.",
                                },
                                "value": {
                                    "description": "New value (number, boolean, or enum string per the control's kind).",
                                },
                                "reason": {
                                    "type": "string",
                                    "description": "Why this specific change.",
                                },
                            },
                            "required": ["key", "value"],
                        },
                    },
                },
                "required": ["changes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish_calibration",
            "description": (
                "Call this when exposure is clean (white patch ~235-245, black ~15-30, "
                "no clipping) and you are satisfied with the result. Ends the loop."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Short sentence describing the final state.",
                    },
                },
                "required": ["summary"],
            },
        },
    },
]


def _build_llm_calibration_system_prompt(
    *,
    role: str,
    provider: str,
    max_iterations: int,
    allowed_controls: Dict[str, Any],
    baseline_reset_keys: List[str] | None = None,
) -> str:
    baseline_note = ""
    if baseline_reset_keys:
        baseline_note = (
            "\nBefore your first iteration, the system reset these post-processing controls to firmware defaults: "
            + ", ".join(sorted(baseline_reset_keys))
            + ". Prefer exposure/gain first — but if the defaults look clearly wrong, you MAY re-tune them.\n"
        )
    return (
        "You are an iterative camera calibration agent for a sorting machine.\n"
        "You will see a sequence of frames from the camera, each cropped to the working zone. "
        "The scene ideally contains a 6-color LEGO calibration plate (white, black, blue, red, green, yellow). "
        "You also have a clean reference image of the intended plate appearance.\n\n"
        "YOUR JOB:\n"
        "- AFTER your tuning, the system applies a per-camera color correction matrix (CCM) + gamma profile "
        "derived from the calibration plate. That stage handles fine color accuracy and WB neutrality.\n"
        "- Your PRIMARY focus: deliver a CLEAN, WELL-EXPOSED RAW SIGNAL — exposure (exposure_time / exposure_compensation), "
        "gain / ISO, brightness as fallback.\n"
        "- SECONDARY: if the raw image is clearly unusable (colors indistinguishable, extreme cast, crushed contrast), "
        "you MAY tune saturation, contrast, sharpness, gamma, or white balance — small, conservative nudges.\n"
        "- Do NOT fuss over small color/WB drift — the CCM cleans that up.\n\n"
        "EXPOSURE PRIORITY:\n"
        "- Aim for white patch ~235–245 (NEVER clip), black patch ~15–30 (don't crush).\n"
        "- If `clipped_white_fraction` > 0.02, lower exposure/gain immediately.\n"
        "- When unsure between brighter and darker, choose darker.\n\n"
        "TOOL USE (you MUST use tools — do not reply with plain text):\n"
        "- Call `apply_camera_settings` to change settings — you'll get the new frame back as a follow-up user message.\n"
        "- Call `finish_calibration` as soon as exposure is clean. Do NOT keep tweaking for cosmetic gains.\n"
        f"- Maximum {max_iterations} `apply_camera_settings` calls before the loop force-stops.\n"
        "- Each call: at most 3 changes, only keys from `allowed_controls`, exact enum values for enum controls.\n"
        "- Avoid oscillation: don't undo a previous change unless the new image clearly demands it.\n\n"
        f"Camera role: {role}\n"
        f"Provider: {provider}\n"
        f"Max iterations: {max_iterations}\n"
        f"{baseline_note}"
        f"\nAllowed controls:\n{json.dumps(allowed_controls, indent=2, sort_keys=True)}"
    )


def _build_llm_calibration_user_text(
    *,
    iteration: int,
    max_iterations: int,
    current_settings: Dict[str, Any],
    analysis_summary: Dict[str, Any],
    is_initial: bool,
) -> str:
    header = (
        "First frame for calibration. Cropped working-zone view + clean reference image attached."
        if is_initial
        else f"Frame after iteration {iteration - 1}."
    )
    return (
        f"{header}\n"
        f"Iteration {iteration} of {max_iterations}.\n\n"
        f"Current device settings:\n{json.dumps(current_settings, indent=2, sort_keys=True)}\n\n"
        f"Analyzer summary:\n{json.dumps(analysis_summary, indent=2, sort_keys=True)}\n\n"
        "Either call `apply_camera_settings` with the next changes or `finish_calibration` if exposure is clean."
    )


def _call_openrouter_calibration_advisor(
    prompt: str,
    image_b64: str,
    *,
    model: str,
    reference_image_b64: str | None = None,
) -> Dict[str, Any]:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is not configured for LLM-guided calibration.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise HTTPException(status_code=500, detail=f"openai package is required for LLM-guided calibration: {exc}")

    from vision.gemini_sam_detector import OPENROUTER_BASE_URL

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
    ]
    if reference_image_b64:
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{reference_image_b64}"},
            }
        )

    model_name = _normalize_llm_calibration_model(model)
    last_error: Exception | None = None
    last_text = ""

    base_messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Return only a valid JSON object. "
                "Do not include markdown, explanation, code fences, or any text before or after the JSON."
            ),
        },
        {
            "role": "user",
            "content": content,
        },
    ]

    retry_messages: List[Dict[str, Any]] = [
        *base_messages,
        {
            "role": "user",
            "content": (
                "Your previous reply was not valid JSON. "
                "Reply again using only a single raw JSON object with keys status, summary, and changes."
            ),
        },
    ]

    for messages in (base_messages, retry_messages):
        try:
            try:
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=1400,
                    timeout=25.0,
                    response_format={"type": "json_object"},
                )
            except Exception:
                # Fallback for providers that reject JSON mode but still support plain chat completions.
                response = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.1,
                    max_tokens=1400,
                    timeout=25.0,
                )

            last_text = _openrouter_message_text(response.choices[0].message.content)
            return _extract_openrouter_json(last_text)
        except Exception as exc:
            last_error = exc
            continue

    excerpt = re.sub(r"\s+", " ", last_text or "").strip()
    if len(excerpt) > 220:
        excerpt = excerpt[:217] + "..."
    if last_error is None:
        raise RuntimeError("OpenRouter calibration advisor failed without an error.")
    raise RuntimeError(
        f"OpenRouter calibration advisor failed after retry: {last_error}"
        + (f" Response excerpt: {excerpt}" if excerpt else "")
    )


def _coerce_llm_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on", "1"}:
            return True
        if normalized in {"false", "no", "off", "0"}:
            return False
    return None


def _apply_llm_calibration_changes(
    provider: str,
    current_settings: Dict[str, Any],
    current_response: Dict[str, Any],
    advisor_payload: Dict[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    next_settings = dict(current_settings)
    applied_changes: List[Dict[str, Any]] = []

    raw_changes = advisor_payload.get("changes")
    if not isinstance(raw_changes, list):
        settings_patch = advisor_payload.get("settings")
        if isinstance(settings_patch, dict):
            raw_changes = [{"key": key, "value": value} for key, value in settings_patch.items()]
        else:
            raw_changes = []

    if provider == "android-camera-app":
        capabilities = current_response.get("capabilities") if isinstance(current_response.get("capabilities"), dict) else {}
        for change in raw_changes:
            if not isinstance(change, dict) or not isinstance(change.get("key"), str):
                continue
            key = change["key"].strip()
            reason = str(change.get("reason") or "").strip()
            raw_value = change.get("value")
            if key == "exposure_compensation":
                if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
                    continue
                try:
                    numeric = int(round(float(raw_value)))
                except (TypeError, ValueError):
                    continue
                exp_min = int(capabilities.get("exposure_compensation_min", numeric))
                exp_max = int(capabilities.get("exposure_compensation_max", numeric))
                coerced: Any = max(exp_min, min(exp_max, numeric))
            elif key == "white_balance_mode":
                allowed = {
                    str(mode)
                    for mode in capabilities.get("white_balance_modes", [])
                    if isinstance(mode, str) and mode
                }
                if not isinstance(raw_value, str) or raw_value not in allowed:
                    continue
                coerced = raw_value
            elif key == "processing_mode":
                allowed = {
                    str(mode)
                    for mode in capabilities.get("processing_modes", [])
                    if isinstance(mode, str) and mode
                }
                if not isinstance(raw_value, str) or raw_value not in allowed:
                    continue
                coerced = raw_value
            elif key == "ae_lock":
                if not bool(capabilities.get("supports_ae_lock")):
                    continue
                coerced = _coerce_llm_boolean(raw_value)
                if coerced is None:
                    continue
            elif key == "awb_lock":
                if not bool(capabilities.get("supports_awb_lock")):
                    continue
                coerced = _coerce_llm_boolean(raw_value)
                if coerced is None:
                    continue
            else:
                continue

            if next_settings.get(key) == coerced:
                continue
            next_settings[key] = coerced
            applied_changes.append({"key": key, "value": coerced, "reason": reason})
        return next_settings, applied_changes

    controls = current_response.get("controls")
    if not isinstance(controls, list):
        return next_settings, applied_changes
    controls_by_key = {
        str(control.get("key")): control
        for control in controls
        if isinstance(control, dict) and isinstance(control.get("key"), str)
    }

    for change in raw_changes:
        if not isinstance(change, dict) or not isinstance(change.get("key"), str):
            continue
        key = change["key"].strip()
        control = controls_by_key.get(key)
        if control is None:
            continue
        reason = str(change.get("reason") or "").strip()
        raw_value = change.get("value")
        if control.get("kind") == "boolean":
            coerced_bool = _coerce_llm_boolean(raw_value)
            if coerced_bool is None or next_settings.get(key) == coerced_bool:
                continue
            next_settings[key] = coerced_bool
            applied_changes.append({"key": key, "value": coerced_bool, "reason": reason})
            continue

        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, str)):
            continue
        try:
            numeric = float(raw_value)
        except (TypeError, ValueError):
            continue
        coerced_numeric = _clamp_control(numeric, control)
        step = _as_number(control.get("step"))
        coerced_value: Any
        if step is not None and step >= 1:
            coerced_value = int(round(coerced_numeric))
        else:
            coerced_value = float(coerced_numeric)
        if next_settings.get(key) == coerced_value:
            continue
        next_settings[key] = coerced_value
        applied_changes.append({"key": key, "value": coerced_value, "reason": reason})

    return next_settings, applied_changes


def _calibrate_camera_device_settings_with_llm(
    role: str,
    provider: str,
    source: int | str | None,
    current_response: Dict[str, Any],
    *,
    openrouter_model: str,
    max_iterations: int,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
    report_trace: Callable[[List[Dict[str, Any]]], None] | None = None,
    gallery_dir: Path | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any] | None, Dict[str, Any]]:
    """Agentic LLM calibration loop.

    Maintains a multi-turn chat with the model: each ``apply_camera_settings``
    tool call is followed by a tool reply + a fresh user message containing the
    new captured frame. The model sees the full conversation history (its own
    earlier reasoning, applied changes, and resulting frames) — not a
    text-summarized recap.
    """
    current_settings = (
        dict(current_response.get("settings"))
        if provider == "android-camera-app" and isinstance(current_response.get("settings"), dict)
        else cameraDeviceSettingsToDict(parseCameraDeviceSettings(current_response.get("settings")))
    )
    if not current_settings:
        current_settings = {}

    allowed_controls = _camera_calibration_allowed_controls(provider, current_response)

    # Reset color/processing controls to firmware defaults so the LLM and
    # the downstream CCM start from a clean, neutral signal. Exposure/gain
    # controls are preserved (real sensor properties — let the LLM tune them).
    baseline_settings, reset_keys = _compute_calibration_neutral_baseline(
        provider, current_response, current_settings
    )
    if reset_keys:
        logger.info(
            "LLM calibration: reset %d post-processing control(s) to firmware defaults: %s",
            len(reset_keys),
            ", ".join(sorted(reset_keys)),
        )

    history: List[Dict[str, Any]] = []
    active_settings = dict(baseline_settings)
    best_settings = dict(baseline_settings)
    best_analysis: Dict[str, Any] | None = None
    best_selection_value = float("-inf")
    last_summary = ""
    gallery_step = 0

    def _report(stage: str, progress: float, message: str, analysis: Dict[str, Any] | None = None) -> None:
        if report_progress is None:
            return
        report_progress(stage, max(0.0, min(0.9, float(progress))), message, analysis)

    def _save_gallery(
        frame: np.ndarray | None,
        stage: str,
        iteration: int,
        settings: Dict[str, Any],
        *,
        analysis: Dict[str, Any] | None = None,
        advisor_payload: Dict[str, Any] | None = None,
        summary: str | None = None,
    ) -> str | None:
        nonlocal gallery_step
        if gallery_dir is None or frame is None:
            return None
        gallery_step += 1
        prefix = f"step_{gallery_step:03d}_{stage}"
        image_name = f"{prefix}.jpg"
        ok = cv2.imwrite(str(gallery_dir / image_name), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            logger.warning("Failed to write calibration gallery frame %s", image_name)
            return None
        meta: Dict[str, Any] = {
            "stage": stage,
            "iteration": iteration,
            "step": gallery_step,
            "settings": settings,
        }
        if analysis is not None:
            meta["analysis"] = analysis
        if advisor_payload is not None:
            meta["advisor_payload"] = advisor_payload
        if summary:
            meta["summary"] = summary
        (gallery_dir / f"{prefix}.json").write_text(json.dumps(meta, indent=2, default=str))
        task_id = gallery_dir.name
        return f"/api/cameras/device-settings/{role}/calibrate-target/{task_id}/gallery/{image_name}"

    def _track_best(applied_settings: Dict[str, Any], analysis: Dict[str, Any] | None) -> None:
        nonlocal best_analysis, best_settings, best_selection_value
        if analysis is not None:
            sel = _calibration_selection_value(analysis)
            if best_analysis is None or sel > best_selection_value:
                best_analysis = analysis
                best_settings = dict(applied_settings)
                best_selection_value = sel
        elif best_analysis is None:
            best_settings = dict(applied_settings)

    def _capture_review_frame(
        settings_to_apply: Dict[str, Any],
    ) -> tuple[Dict[str, Any], Dict[str, Any] | None, np.ndarray]:
        applied_settings, analysis, frame = _analyze_candidate_settings(role, source, settings_to_apply)
        if frame is None:
            raise HTTPException(status_code=400, detail="Could not capture a live frame for LLM-guided calibration.")
        frame_h, frame_w = frame.shape[:2]
        crop_spec = _dashboard_crop_spec(role, frame_w, frame_h)
        cropped_frame = _apply_dashboard_crop(frame, crop_spec) if crop_spec else frame
        return applied_settings, analysis, cropped_frame

    # ----- One-time OpenAI client setup ----------------------------------
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="OpenRouter API key is not configured for LLM-guided calibration.",
        )
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - runtime dependency guard
        raise HTTPException(
            status_code=500,
            detail=f"openai package is required for LLM-guided calibration: {exc}",
        )
    from vision.gemini_sam_detector import OPENROUTER_BASE_URL

    client = OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)
    model_name = _normalize_llm_calibration_model(openrouter_model)
    reference_image_b64 = _llm_calibration_reference_image_b64()

    system_prompt = _build_llm_calibration_system_prompt(
        role=role,
        provider=provider,
        max_iterations=max_iterations,
        allowed_controls=allowed_controls,
        baseline_reset_keys=reset_keys,
    )
    messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]

    # ----- Initial frame -------------------------------------------------
    _report("llm_capture", 0.08, "Capturing initial frame for LLM review.", None)
    applied_settings, analysis, cropped_frame = _capture_review_frame(active_settings)
    _track_best(applied_settings, analysis)
    analysis_summary = _camera_calibration_analysis_summary(analysis)
    iteration_index = 1
    input_frame_url = _save_gallery(
        cropped_frame, "llm_capture", iteration_index, applied_settings, analysis=analysis
    )

    initial_user_text = _build_llm_calibration_user_text(
        iteration=iteration_index,
        max_iterations=max_iterations,
        current_settings=applied_settings,
        analysis_summary=analysis_summary,
        is_initial=True,
    )
    initial_content: List[Dict[str, Any]] = [
        {"type": "text", "text": initial_user_text},
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{_frame_to_openrouter_jpeg(cropped_frame)}"},
        },
    ]
    if reference_image_b64:
        initial_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{reference_image_b64}"},
            }
        )
    messages.append({"role": "user", "content": initial_content})

    pending_entry: Dict[str, Any] = {
        "iteration": iteration_index,
        "status": "pending",
        "summary": "",
        "input": {
            "current_settings": dict(applied_settings),
            "analysis_summary": dict(analysis_summary),
            "reference_image_provided": reference_image_b64 is not None,
            "allowed_controls": dict(allowed_controls),
        },
        "response": None,
        "changes": [],
        "resulting_settings": dict(applied_settings),
        "analysis": analysis_summary,
        "input_image_url": input_frame_url,
    }
    history.append(pending_entry)
    if report_trace is not None:
        report_trace([dict(entry) for entry in history])

    done = False
    error_message: str | None = None
    safety_turn_cap = max_iterations + 4

    for _turn in range(safety_turn_cap):
        review_progress = 0.12 + (iteration_index / max_iterations) * 0.58
        _report(
            "llm_review",
            review_progress,
            f"LLM reviewing iteration {iteration_index} of {max_iterations}.",
            analysis,
        )

        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                tools=LLM_CALIBRATION_TOOLS,
                tool_choice="auto",
                temperature=0.1,
                max_tokens=1400,
                timeout=30.0,
            )
        except Exception as exc:
            error_message = f"OpenRouter call failed: {exc}"
            logger.warning("LLM calibration chat failed: %s", exc)
            history[-1] = {
                **history[-1],
                "status": "error",
                "summary": error_message,
                "response": {"error": str(exc)},
            }
            if report_trace is not None:
                report_trace([dict(entry) for entry in history])
            break

        msg = response.choices[0].message
        tool_calls = list(getattr(msg, "tool_calls", None) or [])
        text_reply = _openrouter_message_text(getattr(msg, "content", None)).strip()

        assistant_entry: Dict[str, Any] = {
            "role": "assistant",
            "content": getattr(msg, "content", None) or "",
        }
        if tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in tool_calls
            ]
        messages.append(assistant_entry)

        if not tool_calls:
            summary_text = text_reply or "LLM ended calibration without using a tool."
            history[-1] = {
                **history[-1],
                "status": "done",
                "summary": summary_text,
                "response": {"text": text_reply},
            }
            if report_trace is not None:
                report_trace([dict(entry) for entry in history])
            _save_gallery(
                cropped_frame,
                "llm_review",
                iteration_index,
                applied_settings,
                analysis=analysis,
                summary=summary_text,
            )
            last_summary = summary_text
            break

        apply_handled_this_turn = False

        for tc in tool_calls:
            name = tc.function.name or ""
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "finish_calibration":
                summary_text = str(args.get("summary") or "").strip() or "LLM signaled calibration complete."
                messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": "Calibration finished."}
                )
                history[-1] = {
                    **history[-1],
                    "status": "done",
                    "summary": summary_text,
                    "response": {"tool": name, "args": args},
                }
                if report_trace is not None:
                    report_trace([dict(entry) for entry in history])
                _save_gallery(
                    cropped_frame,
                    "llm_review",
                    iteration_index,
                    applied_settings,
                    analysis=analysis,
                    advisor_payload={"tool": name, "args": args},
                    summary=summary_text,
                )
                last_summary = summary_text
                done = True
                break

            if name == "apply_camera_settings":
                if apply_handled_this_turn:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": "Ignored: only one apply_camera_settings is honored per turn.",
                        }
                    )
                    continue

                summary_text = str(args.get("summary") or "").strip()
                advisor_payload_compat: Dict[str, Any] = {
                    "status": "continue",
                    "summary": summary_text,
                    "changes": args.get("changes") if isinstance(args.get("changes"), list) else [],
                }
                next_settings, applied_changes = _apply_llm_calibration_changes(
                    provider,
                    dict(applied_settings),
                    current_response,
                    advisor_payload_compat,
                )

                history[-1] = {
                    **history[-1],
                    "status": "continue",
                    "summary": summary_text,
                    "response": {"tool": name, "args": args},
                    "changes": list(applied_changes),
                    "resulting_settings": dict(next_settings),
                }
                if report_trace is not None:
                    report_trace([dict(entry) for entry in history])
                _save_gallery(
                    cropped_frame,
                    "llm_review",
                    iteration_index,
                    applied_settings,
                    analysis=analysis,
                    advisor_payload=advisor_payload_compat,
                    summary=summary_text,
                )
                last_summary = summary_text or last_summary
                apply_handled_this_turn = True

                if not applied_changes:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": "No supported changes were applied. Verify keys/values against allowed_controls and try again, or call finish_calibration if exposure is acceptable.",
                        }
                    )
                    history[-1] = {**history[-1], "status": "done"}
                    if report_trace is not None:
                        report_trace([dict(entry) for entry in history])
                    done = True
                    break

                _report(
                    "llm_apply",
                    min(0.88, review_progress + 0.04),
                    f"Applying {len(applied_changes)} LLM-suggested change{'s' if len(applied_changes) != 1 else ''}.",
                    analysis,
                )
                active_settings = next_settings

                if iteration_index >= max_iterations:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": (
                                f"Settings applied. Iteration limit ({max_iterations}) reached — "
                                "calibration loop ending."
                            ),
                        }
                    )
                    best_settings = dict(best_settings if best_analysis is not None else active_settings)
                    done = True
                    break

                iteration_index += 1
                _report(
                    "llm_capture",
                    0.08 + ((iteration_index - 1) / max_iterations) * 0.55,
                    f"Capturing iteration {iteration_index} of {max_iterations} for LLM review.",
                    best_analysis,
                )

                applied_settings, analysis, cropped_frame = _capture_review_frame(active_settings)
                _track_best(applied_settings, analysis)
                analysis_summary = _camera_calibration_analysis_summary(analysis)
                input_frame_url = _save_gallery(
                    cropped_frame,
                    "llm_capture",
                    iteration_index,
                    applied_settings,
                    analysis=analysis,
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": (
                            f"Applied {len(applied_changes)} change(s). New frame attached in next user message."
                        ),
                    }
                )

                followup_text = _build_llm_calibration_user_text(
                    iteration=iteration_index,
                    max_iterations=max_iterations,
                    current_settings=applied_settings,
                    analysis_summary=analysis_summary,
                    is_initial=False,
                )
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": followup_text},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{_frame_to_openrouter_jpeg(cropped_frame)}"
                                },
                            },
                        ],
                    }
                )

                pending_entry = {
                    "iteration": iteration_index,
                    "status": "pending",
                    "summary": "",
                    "input": {
                        "current_settings": dict(applied_settings),
                        "analysis_summary": dict(analysis_summary),
                        "reference_image_provided": reference_image_b64 is not None,
                        "allowed_controls": None,
                    },
                    "response": None,
                    "changes": [],
                    "resulting_settings": dict(applied_settings),
                    "analysis": analysis_summary,
                    "input_image_url": input_frame_url,
                }
                history.append(pending_entry)
                if report_trace is not None:
                    report_trace([dict(entry) for entry in history])
                continue

            # Unknown tool — reply and keep going
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": f"Unknown tool: {name}. Use apply_camera_settings or finish_calibration.",
                }
            )

        if done:
            break
        if not apply_handled_this_turn:
            # Only unknown/finish tools and we're not done — bail to avoid loops.
            break

    if not done and error_message is None and history and history[-1].get("status") == "pending":
        history[-1] = {
            **history[-1],
            "status": "done",
            "summary": history[-1].get("summary") or "Loop ended without explicit finish_calibration.",
        }
        if report_trace is not None:
            report_trace([dict(entry) for entry in history])

    best_settings = dict(best_settings if best_analysis is not None else active_settings)

    return best_settings, best_analysis, {
        "method": CALIBRATION_METHOD_LLM_GUIDED,
        "openrouter_model": openrouter_model,
        "max_iterations": max_iterations,
        "trace": history,
        "summary": last_summary,
    }


def _build_llm_final_review_prompt(
    *,
    role: str,
    final_settings: Dict[str, Any],
    profile_present: bool,
    last_loop_summary: str,
) -> str:
    profile_note = (
        "A per-camera color correction matrix (CCM) and gamma profile derived from the calibration plate "
        "have just been applied to the image you are reviewing."
        if profile_present
        else "No new color profile was generated — the image you are reviewing only reflects the LLM-tuned device settings."
    )
    summary_note = f"Loop summary so far: {last_loop_summary}\n" if last_loop_summary else ""
    return (
        "You are signing off on a finished camera calibration for a sorting machine.\n\n"
        "WHAT HAPPENED:\n"
        "- The LLM tuning loop finished adjusting exposure / gain / processing controls.\n"
        f"- {profile_note}\n"
        f"{summary_note}"
        "\nWHAT TO CHECK in the final image (cropped to the working zone):\n"
        "- Exposure: white patch around 235–245, no clipping; black patch around 15–30, not crushed.\n"
        "- Color separation: red, green, blue, yellow patches are clearly distinct after CCM.\n"
        "- White balance: white patch looks neutral (no obvious blue/yellow/green cast).\n"
        "- Overall: image looks usable for color-based piece sorting.\n\n"
        f"Final device settings:\n{json.dumps(final_settings, indent=2, sort_keys=True)}\n\n"
        "Return ONLY valid JSON with this exact shape:\n"
        '{"status":"approved|concerns","summary":"one short sentence","concerns":["short bullet","..."]}\n\n'
        "Rules:\n"
        "- Use status \"approved\" if the image is good enough for downstream sorting.\n"
        "- Use status \"concerns\" if real issues remain — list them in concerns[] (max 3, short phrases).\n"
        "- Do NOT propose new setting changes — calibration is finished.\n"
        "- No markdown, no code fences, no prose outside the JSON object."
    )


def _run_llm_final_review(
    *,
    role: str,
    gallery_dir: Path | None,
    openrouter_model: str,
    final_frame: np.ndarray,
    final_settings: Dict[str, Any],
    profile_present: bool,
    last_loop_summary: str,
    next_iteration_index: int,
    advisor_history_step: int,
) -> Dict[str, Any]:
    """Send the CCM-corrected final frame back to the advisor for sign-off.

    Returns a trace entry dict suitable for appending to ``calibration_metadata["trace"]``.
    Never raises — failures are turned into a status="error" entry so the rest of the
    calibration result still ships.
    """
    frame_h, frame_w = final_frame.shape[:2]
    crop_spec = _dashboard_crop_spec(role, frame_w, frame_h)
    cropped_frame = _apply_dashboard_crop(final_frame, crop_spec) if crop_spec else final_frame

    image_url: str | None = None
    if gallery_dir is not None:
        prefix = f"step_{advisor_history_step:03d}_llm_final_review"
        image_name = f"{prefix}.jpg"
        ok = cv2.imwrite(str(gallery_dir / image_name), cropped_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            meta: Dict[str, Any] = {
                "stage": "llm_final_review",
                "iteration": next_iteration_index,
                "step": advisor_history_step,
                "settings": final_settings,
                "profile_present": profile_present,
            }
            (gallery_dir / f"{prefix}.json").write_text(json.dumps(meta, indent=2, default=str))
            task_id = gallery_dir.name
            image_url = f"/api/cameras/device-settings/{role}/calibrate-target/{task_id}/gallery/{image_name}"
        else:
            logger.warning("Failed to write final-review gallery frame %s", image_name)

    prompt = _build_llm_final_review_prompt(
        role=role,
        final_settings=final_settings,
        profile_present=profile_present,
        last_loop_summary=last_loop_summary,
    )

    base_input = {
        "final_settings": dict(final_settings),
        "profile_present": profile_present,
        "loop_summary": last_loop_summary,
    }

    try:
        advisor_payload = _call_openrouter_calibration_advisor(
            prompt,
            _frame_to_openrouter_jpeg(cropped_frame),
            model=openrouter_model,
            reference_image_b64=_llm_calibration_reference_image_b64(),
        )
    except Exception as exc:
        logger.warning("LLM final-review call failed: %s", exc)
        return {
            "iteration": next_iteration_index,
            "stage": "final_review",
            "status": "error",
            "summary": f"Final review skipped: {exc}",
            "input": base_input,
            "response": None,
            "changes": [],
            "input_image_url": image_url,
        }

    raw_status = str(advisor_payload.get("status") or "").strip().lower()
    raw_concerns = advisor_payload.get("concerns")
    if raw_status not in {"approved", "concerns"}:
        raw_status = "concerns" if isinstance(raw_concerns, list) and raw_concerns else "approved"
    summary_text = str(advisor_payload.get("summary") or "").strip()

    return {
        "iteration": next_iteration_index,
        "stage": "final_review",
        "status": raw_status,
        "summary": summary_text,
        "input": base_input,
        "response": dict(advisor_payload),
        "changes": [],
        "input_image_url": image_url,
    }


def _calibrate_exposure_via_histogram(
    role: str,
    source: int | str | None,
    controls: List[Dict[str, Any]],
    current_settings: Dict[str, int | float | bool],
    *,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
    gallery_dir: Path | None = None,
    target_luma: float = EXPOSURE_HISTOGRAM_TARGET_LUMA,
    tolerance: float = EXPOSURE_HISTOGRAM_TOLERANCE_LUMA,
    max_iterations: int = EXPOSURE_HISTOGRAM_MAX_ITERATIONS,
) -> tuple[Dict[str, int | float | bool], Dict[str, Any]]:
    """Proportional-gain exposure calibration driven by frame-luma histogram.

    Captures a frame, measures mean grayscale brightness, adjusts the
    ``exposure`` device control proportionally toward ``target_luma`` (default
    128 = middle gray), settles, captures again, repeats. Converges fast
    on typical Classification-chamber scenes (4 – 8 iterations). No colour
    profile, no LLM round-trip, no target plate — just "make the scene
    middle-gray". Returns the winning settings + an analysis dict for the
    calling task to attach to the progress report.
    """

    if not isinstance(controls, list):
        raise HTTPException(status_code=400, detail="Camera controls are not available for exposure calibration.")

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
        applied, _, frame = _analyze_candidate_settings(role, source, settings)
        frame_to_use = frame
        if frame_to_use is None:
            frame_to_use = _capture_frame_for_calibration(
                role, source, fallback_settings=settings, after_timestamp=before,
            )
        if frame_to_use is None:
            raise HTTPException(status_code=500, detail="Could not capture a frame for histogram calibration.")

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

        # Proportional gain — exposure scales roughly linearly with light at
        # moderate values, so a gain just above 1 gets us to target in a handful
        # of steps without overshoot. Clamped to the control's advertised range.
        ratio = target_luma / max(mean_luma, 1.0)
        ratio = max(0.3, min(3.0, ratio))  # per-step safety bound
        new_exposure = float(settings["exposure"]) * (1.0 + (ratio - 1.0) * EXPOSURE_HISTOGRAM_P_GAIN)
        new_exposure = max(exposure_min, min(exposure_max, new_exposure))
        new_exposure = round(new_exposure / exposure_step) * exposure_step
        if abs(new_exposure - settings["exposure"]) < exposure_step:
            # P-controller wants a move smaller than the control resolution —
            # no further progress possible at this setting.
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


def _calibrate_usb_camera_device_settings(
    role: str,
    source: int,
    controls: List[Dict[str, Any]],
    current_settings: Dict[str, int | float | bool],
    *,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
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
        baseline["gain"] = _as_number(gain_control.get("min")) or 0.0

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
        preview_camera_device_settings(role, s)
        time.sleep(0.25)
        return _capture_raw_frame(role, source, s)

    # ------------------------------------------------------------------
    # Phase 0: Debevec response curve → direct exposure calculation
    # Capture 5-7 frames at log-spaced exposures, estimate the camera
    # response function, compute optimal exposure from the HDR map.
    # ------------------------------------------------------------------

    response_curve_data: Dict[str, Any] | None = None

    if exposure_control is not None:
        exp_min = _as_number(exposure_control.get("min")) or 1.0
        exp_max = _as_number(exposure_control.get("max")) or 10000.0

        # Generate 7 log-spaced exposure values across the range
        # UVC exposure_absolute is typically in 0.1ms units (linear)
        # If min <= 0 (some cameras use log2 scale), use linear spacing instead
        if exp_min > 0:
            bracket_exposures = np.geomspace(exp_min, exp_max, num=7).tolist()
        else:
            bracket_exposures = np.linspace(exp_min, exp_max, num=7).tolist()

        bracket_exposures = [
            _clamp_control(val, exposure_control) for val in bracket_exposures
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
                        # We want p99 to map to pixel value ~235
                        # From response curve: find the exposure time where
                        # the response function outputs 235
                        target_log_exp = float(response_squeezed[235, 1])  # use green channel
                        target_exposure_product = np.exp(target_log_exp)
                        optimal_time = target_exposure_product / p99_radiance

                        # Convert back to UVC exposure units
                        if exp_min > 0:
                            optimal_exposure = optimal_time
                        else:
                            optimal_exposure = np.log2(max(optimal_time, 1e-10))

                        optimal_exposure = _clamp_control(float(optimal_exposure), exposure_control)
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
                                    gain_min = _as_number(gain_control.get("min")) or 0.0
                                    gain_max = _as_number(gain_control.get("max")) or 255.0
                                    # Scale gain proportionally
                                    current_gain = float(settings.get("gain", gain_min))
                                    settings["gain"] = _clamp_control(
                                        current_gain + (gain_max - gain_min) * min(gain_needed - 1.0, 1.0) * 0.5,
                                        gain_control,
                                    )

                        _report("bracket", f"Debevec: optimal exposure={optimal_exposure:.1f}")
                    else:
                        _report("bracket", "Debevec: p99 radiance is zero, falling back to mid-range exposure.")
                        settings["exposure"] = _clamp_control((exp_min + exp_max) / 2.0, exposure_control)

                except Exception as exc:
                    _report("bracket", f"Debevec failed ({exc}), falling back to binary search.")
                    # Fallback: simple binary search
                    settings["exposure"] = _clamp_control((exp_min + exp_max) / 2.0, exposure_control)
                    response_curve_data = None
            else:
                settings["exposure"] = _clamp_control((exp_min + exp_max) / 2.0, exposure_control)
        else:
            settings["exposure"] = _clamp_control((exp_min + exp_max) / 2.0, exposure_control)

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
            exp_min = _as_number(exposure_control.get("min")) or 1.0 if exposure_control else 1.0
            exp_max = _as_number(exposure_control.get("max")) or 10000.0 if exposure_control else 10000.0
            low, high = exp_min, exp_max
            for _ in range(4):
                trial = _clamp_control((low + high) / 2.0, exposure_control) if exposure_control else (low + high) / 2.0
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
        c_min = _as_number(ctrl.get("min"))
        c_max = _as_number(ctrl.get("max"))
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
            settings[key] = _clamp_control(neutral, ctrl)
    # Sharpening to minimum (adds artifacts)
    if sharpness_control is not None:
        sharpness_min = _as_number(sharpness_control.get("min"))
        if sharpness_min is not None:
            settings["sharpness"] = sharpness_min

    # Apply neutral settings so the capture thread picks them up
    _apply_and_grab(settings)
    _report("neutral", "Firmware color controls set to neutral.")
    _save_gallery(None, "neutral_settings", settings, {"note": "firmware color controls set to neutral"})

    # ------------------------------------------------------------------
    # Phase 2: Detect the calibration target
    # With good exposure + neutral tone controls, detection should be reliable.
    # The orchestrator generates the CCM from detected patches afterward.
    # ------------------------------------------------------------------

    _report("detection", "Detecting calibration target.")

    best_settings: Dict[str, int | float | bool] = dict(settings)
    best_analysis: Dict[str, Any] | None = None

    # Capture 3 frames, analyze each, keep best
    for attempt in range(3):
        f = _capture_frame_for_calibration(role, source, fallback_settings=settings)
        if f is not None:
            result = analyze_color_plate_target(f)
            if result is not None:
                analysis_dict = result.to_dict()
                if best_analysis is None or _calibration_selection_value(analysis_dict) > _calibration_selection_value(best_analysis):
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
        applied_settings, analysis, _ = _analyze_candidate_settings(role, source, candidate)
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
    config_role = stored_camera_role_key(role, config)
    if parsed.enabled:
        if config_role == "classification_channel":
            profiles.pop("carousel", None)
        elif config_role == "carousel":
            profiles.pop("classification_channel", None)
        profiles[config_role] = profile_dict
    else:
        profiles.pop(config_role, None)
    config["camera_color_profiles"] = profiles

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    return {
        "ok": True,
        "role": role,
        "profile": profile_dict,
        "applied_live": False,
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


_POLYGON_KEY_TO_CHANNEL_KEY: Dict[str, str] = {
    "second_channel": "second",
    "third_channel": "third",
    "classification_channel": "classification_channel",
    "carousel": "carousel",
}


def _dashboard_polygon_resolution(
    saved: Dict[str, Any] | None,
    channel_key: str | None = None,
) -> tuple[float, float]:
    """Resolve the capture resolution a polygon was saved at.

    Prefers the per-channel ``resolution`` embedded by the zone editor
    (``arc_params[<key>].resolution`` for arc channels,
    ``quad_params[<key>].resolution`` for rect channels), and falls back to the
    legacy top-level ``saved["resolution"]`` — and then to a 1920x1080 default —
    so heterogeneous camera resolutions (e.g. C2 at 1280x720 while C3 runs at
    3840x2160) don't contaminate each other on the dashboard preview.
    """

    return saved_polygon_resolution(saved, channel_key=channel_key)


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
    if role in {"feeder", "c_channel_2", "c_channel_3", "carousel", "classification_channel"}:
        saved = get_channel_polygons() or {}
        polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
        quad_table = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
        classification_channel_setup = _public_aux_scope() == "classification_channel"
        carousel_polygon_key = "classification_channel" if classification_channel_setup else "carousel"

        if role == "carousel" and not classification_channel_setup:
            carousel_resolution = _dashboard_polygon_resolution(saved, "carousel")
            quad_points = _dashboard_quad_points(quad_table.get("carousel"))
            if len(quad_points) != 4:
                quad_points = _dashboard_points(polygons_table.get(carousel_polygon_key))
            scaled_quad = (
                _scale_dashboard_points(quad_points, carousel_resolution, frame_w, frame_h)
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
            "feeder": ["second_channel", "third_channel", carousel_polygon_key],
            "c_channel_2": ["second_channel"],
            "c_channel_3": ["third_channel"],
            "carousel": [carousel_polygon_key],
            "classification_channel": ["classification_channel"],
        }.get(role, [])
        scaled_polygons = []
        for key in polygon_keys:
            # Each polygon is stored in the resolution of the channel it was
            # edited in; scale from its own saved resolution to the live frame.
            channel_key = _POLYGON_KEY_TO_CHANNEL_KEY.get(key, key)
            per_channel_resolution = _dashboard_polygon_resolution(saved, channel_key)
            scaled = _scale_dashboard_points(
                _dashboard_points(polygons_table.get(key)),
                per_channel_resolution,
                frame_w,
                frame_h,
            )
            if scaled is not None:
                scaled_polygons.append(scaled)
        bbox = _dashboard_padded_bbox(scaled_polygons, frame_w, frame_h)
        return {"kind": "bbox", "bbox": bbox} if bbox is not None else None

    if role in {"classification_top", "classification_bottom"}:
        saved = get_classification_polygons() or {}
        polygons_table = saved.get("polygons") if isinstance(saved.get("polygons"), dict) else {}
        quad_table = saved.get("quad_params") if isinstance(saved.get("quad_params"), dict) else {}
        quad_key = "class_top" if role == "classification_top" else "class_bottom"
        polygon_key = "top" if role == "classification_top" else "bottom"
        source_resolution = _dashboard_polygon_resolution(saved, quad_key)
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
    saved = _save_camera_color_profile(role, {"enabled": False})
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
