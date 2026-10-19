"""Machine specs snapshot — the "what is this machine" details a connected
Hive gets.

It answers the basic compatibility and support questions (what camera, what
controller board, what platform and OS) and says how the machine is set up:
each camera's saved settings and each stepper's driver settings. fleet_telemetry
writes it as a `machine_specs` telemetry record (the machine_telemetry stream)
at start and whenever it changes; Hive shows a summary on the machine's
dashboard and keeps the history. Collection is entirely best-effort — a missing
/proc file, an uninitialized camera, or a machine still in standby just yields
a smaller snapshot, never an error that touches the sorting path.

It carries nothing that identifies the hardware (hostname, MAC addresses, CPU
serial): it is always shared with a connected Hive, and where to find the
machine is the optional network stream's.

BOOT_ID is fresh per process, so every restart produces a new snapshot the
server can distinguish from the previous one even when nothing else changed —
that is how the account dashboard can show a report per restart over time.
"""

from __future__ import annotations

import os
import platform
import uuid
from datetime import datetime, timezone
from typing import Any

import machine_toml

# 2: per-camera `calibration` block (device and picture settings, capture mode).
# 3: `steppers` (each motor's driver settings); no `host`.
SCHEMA_VERSION = 3

BOOT_ID = str(uuid.uuid4())
_BOOTED_AT = datetime.now(timezone.utc).isoformat()


def v4l2CameraModel(index: int) -> str | None:
    try:
        with open(f"/sys/class/video4linux/video{index}/name") as handle:
            name = handle.read().strip()
            return name or None
    except OSError:
        return None


def _cameraEntry(role_value: Any) -> dict[str, Any]:
    # A role in the TOML is either a bare device index or a dict carrying the
    # index/url plus capture settings. Normalize both into one shape.
    entry: dict[str, Any] = {
        "device_index": None,
        "url": None,
        "width": None,
        "height": None,
        "fps": None,
        "fourcc": None,
        "model": None,
    }
    if isinstance(role_value, dict):
        raw_index = role_value.get("device_index")
        if isinstance(raw_index, int) and not isinstance(raw_index, bool):
            entry["device_index"] = raw_index
        url = role_value.get("url")
        if isinstance(url, str) and url.strip():
            entry["url"] = url.strip()
        for key in ("width", "height", "fps"):
            value = role_value.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                entry[key] = value
        fourcc = role_value.get("fourcc")
        if isinstance(fourcc, str) and fourcc.strip():
            entry["fourcc"] = fourcc.strip()
    elif isinstance(role_value, int) and not isinstance(role_value, bool):
        entry["device_index"] = role_value

    if entry["url"] is None and isinstance(entry["device_index"], int) and entry["device_index"] >= 0:
        entry["model"] = v4l2CameraModel(entry["device_index"])
    return entry


def _liveCameras() -> dict[str, Any]:
    # The running camera service holds the resolution each camera actually
    # opened with, which the raw TOML setup may not carry.
    try:
        from server import shared_state

        service = shared_state.camera_service
        devices = service.devices if service is not None else {}
    except Exception:
        return {}
    cameras: dict[str, Any] = {}
    for role, device in (devices or {}).items():
        config = getattr(device, "config", None)
        if config is None:
            continue
        index = getattr(config, "device_index", None)
        index = index if isinstance(index, int) and not isinstance(index, bool) else None
        url = getattr(config, "url", None)
        url = url.strip() if isinstance(url, str) and url.strip() else None
        if index is None and url is None:
            continue
        entry: dict[str, Any] = {
            "device_index": index,
            "url": url,
            "width": getattr(config, "width", None),
            "height": getattr(config, "height", None),
            "fps": getattr(config, "fps", None),
            "fourcc": getattr(config, "fourcc", None),
            "model": None,
        }
        if url is None and index is not None and index >= 0:
            entry["model"] = v4l2CameraModel(index)
        cameras[str(role)] = entry
    return cameras


def _machineParamsTable(section: str) -> dict[str, Any]:
    table = machine_toml.read().get(section)
    return table if isinstance(table, dict) else {}


def _calibrationByRole() -> dict[str, dict[str, Any]]:
    device_settings = _machineParamsTable("camera_device_settings")
    picture_settings = _machineParamsTable("camera_picture_settings")
    capture_modes = _machineParamsTable("camera_capture_modes")

    roles = set(device_settings) | set(picture_settings) | set(capture_modes)
    result: dict[str, dict[str, Any]] = {}
    for role in roles:
        result[str(role)] = {
            "device_settings": device_settings.get(role) if isinstance(device_settings.get(role), dict) else None,
            "picture_settings": picture_settings.get(role) if isinstance(picture_settings.get(role), dict) else None,
            "capture_mode": capture_modes.get(role) if isinstance(capture_modes.get(role), dict) else None,
        }
    return result


def _withCalibration(cameras: dict[str, Any]) -> dict[str, Any]:
    calibration = _calibrationByRole()
    for role, entry in cameras.items():
        if isinstance(entry, dict):
            entry["calibration"] = calibration.get(str(role)) or {
                "device_settings": None,
                "picture_settings": None,
                "capture_mode": None,
            }
    return cameras


def _cameras() -> dict[str, Any]:
    live = _liveCameras()
    if live:
        return _withCalibration(live)
    # Fall back to the TOML setup when the camera service isn't up yet.
    try:
        from toml_config import getCameraSetup

        setup = getCameraSetup()
    except Exception:
        return {}
    if not isinstance(setup, dict):
        return {}
    cameras: dict[str, Any] = {}
    for role, value in setup.items():
        if value is None:
            continue
        entry = _cameraEntry(value)
        if entry["device_index"] is not None or entry["url"] is not None:
            cameras[role] = entry
    return _withCalibration(cameras)


def _controllerBoards() -> dict[str, Any]:
    # Populated only once hardware has been discovered (homing/ready); a machine
    # sitting in standby reports no boards, which the dashboard renders as "—".
    try:
        from server import shared_state

        irl = shared_state.getActiveIRL()
    except Exception:
        return {}
    boards = getattr(irl, "control_boards", None) if irl is not None else None
    if not isinstance(boards, dict):
        return {}
    result: dict[str, Any] = {}
    for key, board in boards.items():
        identity = getattr(board, "identity", None)
        if identity is None:
            continue
        result[str(key)] = {
            "family": getattr(identity, "family", None),
            "role": getattr(identity, "role", None),
            "device_name": getattr(identity, "device_name", None),
            "port": getattr(identity, "port", None),
        }
    return result


def _system() -> dict[str, Any]:
    info: dict[str, Any] = {"ram_bytes": None, "disk_total_bytes": None, "cpu_count": os.cpu_count()}
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    info["ram_bytes"] = int(line.split()[1]) * 1024
                    break
    except Exception:
        pass
    try:
        import shutil

        info["disk_total_bytes"] = int(shutil.disk_usage("/").total)
    except Exception:
        pass
    return info


def _steppers() -> dict[str, Any]:
    # What each motor's driver is set to (machine.toml and the built-in
    # defaults), so the load the drivers report can be read against it.
    from hardware_settings.motors import MOTORS
    from hardware_settings.steppers import readStepperSettings

    result: dict[str, Any] = {}
    for motor in MOTORS:
        try:
            settings = readStepperSettings(motor)
        except Exception:
            continue
        result[motor.name] = {
            "irun": settings.irun,
            "ihold": settings.ihold,
            "ihold_delay": settings.ihold_delay,
            "microsteps": settings.microsteps,
            "stealthchop": settings.stealthchop,
            "coolstep": settings.coolstep,
            "stallguard": settings.stallguard,
            "sgthrs": settings.sgthrs,
            "tcoolthrs": settings.tcoolthrs,
            "inverted": settings.inverted,
            "saved": sorted(settings.saved),
        }
    return result


def buildMachineSpecs() -> dict[str, Any]:
    from status_ping import _configInfo, _hardwareInfo, _osInfo, _softwareInfo

    hardware = _hardwareInfo()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "boot_id": BOOT_ID,
        "booted_at": _BOOTED_AT,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "model": hardware.get("model"),
            "arch": platform.machine() or None,
            "python": platform.python_version(),
            "os": _osInfo(),
        },
        "software": _softwareInfo(),
        "system": _system(),
        "config": _configInfo(),
        "cameras": _cameras(),
        "controller_boards": _controllerBoards(),
        "steppers": _steppers(),
    }
    return payload
