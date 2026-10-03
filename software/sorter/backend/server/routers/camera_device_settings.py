"""Router for a camera role's own controls: the UVC controls of a USB camera.
Read them, preview a change live, save them, reset them to automatic, and
compare what is saved with what the camera reports. A camera whose source is
a stream URL has no controls to adjust.
"""

from __future__ import annotations

import platform
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

import machine_toml
from irl.config import cameraDeviceSettingsToDict, cameraSettingsForRole, parseCameraDeviceSettings
from server import shared_state
from server.routers.cameras import _camera_source_for_role, _settings_role

router = APIRouter()


def _get_camera_device_settings_table(config: Dict[str, Any]) -> Dict[str, Any]:
    device_settings = config.get("camera_device_settings", {})
    return device_settings if isinstance(device_settings, dict) else {}


def _saved_camera_device_settings(config: Dict[str, Any], role: str) -> Dict[str, int | float | bool]:
    return cameraDeviceSettingsToDict(
        parseCameraDeviceSettings(cameraSettingsForRole(_get_camera_device_settings_table(config), role))
    )


NETWORK_STREAM_MESSAGE = "A network stream camera has no adjustable controls."


def _assigned_camera_source(role: str) -> int:
    source = _camera_source_for_role(machine_toml.read(), role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")
    if not isinstance(source, int):
        raise HTTPException(status_code=400, detail=NETWORK_STREAM_MESSAGE)
    return source


# ---------------------------------------------------------------------------
# USB cameras
# ---------------------------------------------------------------------------


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

    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setDeviceSettingsForRole"):
        try:
            live_result = shared_state.vision_manager.setDeviceSettingsForRole(role, parsed, persist=persist)
            if live_result is not None:
                return cameraDeviceSettingsToDict(live_result), True
        except Exception:
            pass

    return dict(parsed), False


def _auto_camera_device_settings_from_controls(
    controls: List[Dict[str, Any]],
) -> Dict[str, bool]:
    auto_keys = {"auto_exposure", "auto_white_balance", "autofocus"}
    settings: Dict[str, bool] = {}
    for control in controls:
        key = control.get("key")
        if key in auto_keys and control.get("kind") == "boolean":
            settings[str(key)] = True
    return settings


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/api/cameras/device-settings/{role}")
def get_camera_device_settings(role: str) -> Dict[str, Any]:
    config = machine_toml.read()
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
        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": "network-stream",
            "settings": {},
            "controls": [],
            "supported": False,
            "message": NETWORK_STREAM_MESSAGE,
        }

    saved_settings = _saved_camera_device_settings(config, role)
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
    source = _assigned_camera_source(role)
    parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(payload))
    applied_settings, applied_live = _apply_live_usb_device_settings(role, parsed, persist=False)

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
    source = _assigned_camera_source(role)
    parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(payload))
    settings_role = _settings_role(role)
    with machine_toml.edit() as config:
        device_settings = _get_camera_device_settings_table(config)
        if settings_role == "classification_channel":
            device_settings.pop("carousel", None)
        if parsed:
            device_settings[settings_role] = dict(parsed)
        else:
            device_settings.pop(settings_role, None)
        config["camera_device_settings"] = device_settings

    applied_settings, applied_live = _apply_live_usb_device_settings(role, parsed, persist=True)

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


@router.post("/api/cameras/device-settings/{role}/reset-defaults")
def reset_camera_device_settings_to_defaults(role: str) -> Dict[str, Any]:
    source = _assigned_camera_source(role)
    controls, _ = _camera_service_usb_device_controls(role, source, {})
    auto_settings = _auto_camera_device_settings_from_controls(controls)
    if not auto_settings:
        from vision.camera import default_auto_camera_device_settings

        auto_settings = default_auto_camera_device_settings()

    with machine_toml.edit() as config:
        device_settings = _get_camera_device_settings_table(config)
        device_settings.pop(role, None)
        if role in {"classification_channel", "carousel"}:
            device_settings.pop("classification_channel", None)
            device_settings.pop("carousel", None)
        config["camera_device_settings"] = device_settings

    applied_settings, applied_live = _apply_live_usb_device_settings(role, auto_settings, persist=False)
    svc = shared_state.camera_service
    if svc is not None and hasattr(svc, "clear_persisted_device_settings_for_role"):
        try:
            svc.clear_persisted_device_settings_for_role(role)
        except Exception:
            pass

    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": applied_settings,
        "controls": controls,
        "persisted": False,
        "applied_live": applied_live,
        "message": "Camera reset to automatic settings.",
    }


# ---------------------------------------------------------------------------
# Drift between saved and live settings
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
    config = machine_toml.read()
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

    saved_settings = _saved_camera_device_settings(config, role)

    controls: List[Dict[str, Any]] = []
    live_settings: Dict[str, Any] = {}
    if isinstance(source, int):
        controls, live_settings = _camera_service_usb_device_controls(role, source, saved_settings)

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
