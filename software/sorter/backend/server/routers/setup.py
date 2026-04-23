from __future__ import annotations

from dataclasses import asdict, is_dataclass
import time
from typing import Any, Dict, Literal, cast

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import serial.tools.list_ports

from machine_setup import (
    CLASSIFICATION_CHANNEL_SETUP,
    MANUAL_CAROUSEL_SETUP,
    STANDARD_CAROUSEL_SETUP,
    get_machine_setup_definition,
    get_machine_setup_options,
    machine_setup_key_from_feeding_mode,
    normalize_machine_setup_key,
)
from blob_manager import getMachineId, getMachineNickname
from hardware.bus import MCUBus
from irl.config import REQUIRED_STEPPER_NAMES
from irl.parse_user_toml import LOGICAL_STEPPER_BINDING_BASES
from role_aliases import lookup_camera_role_keys, public_aux_camera_role
from machine_platform.control_board import discover_control_boards
from server import shared_state
from server.config_helpers import (
    read_machine_params_config as _read_machine_params_config,
    write_machine_params_config as _write_machine_params_config,
)
from server.routers.hardware import _servo_settings_from_config

router = APIRouter()

STEPPER_LABELS: dict[str, str] = {
    "c_channel_1": "C-Channel 1",
    "c_channel_2": "C-Channel 2",
    "c_channel_3": "C-Channel 3",
    "carousel": "Carousel",
    "chute": "Chute",
}


class StepperDirectionPayload(BaseModel):
    inverted: bool


class CameraLayoutPayload(BaseModel):
    layout: Literal["default", "split_feeder"]


class FeedingModePayload(BaseModel):
    mode: Literal["auto_channels", "manual_carousel"]


class MachineSetupPayload(BaseModel):
    setup: Literal["standard_carousel", "classification_channel", "manual_carousel"]


def _board_summary(board: Any) -> dict[str, Any]:
    return {
        "family": getattr(board.identity, "family", "unknown"),
        "role": getattr(board.identity, "role", "unknown"),
        "device_name": getattr(board.identity, "device_name", "Unknown"),
        "port": getattr(board.identity, "port", ""),
        "address": getattr(board.identity, "address", 0),
        "logical_steppers": list(getattr(board, "logical_stepper_names", tuple())),
        "servo_count": len(getattr(board, "servos", [])),
        "input_aliases": dict(getattr(board, "input_aliases", {})),
    }


def _close_discovered_boards(boards: list[Any]) -> None:
    seen_serials: set[int] = set()
    for board in boards:
        bus = getattr(getattr(board, "interface", None), "_bus", None)
        serial_obj = getattr(bus, "_serial", None)
        if serial_obj is None or id(serial_obj) in seen_serials:
            continue
        seen_serials.add(id(serial_obj))
        try:
            serial_obj.close()
        except Exception:
            pass


def _camera_assignments_from_config(config: Dict[str, Any]) -> dict[str, Any]:
    cameras = config.get("cameras", {})
    if not isinstance(cameras, dict):
        cameras = {}
    layout = cameras.get("layout")
    if layout not in {"default", "split_feeder"}:
        layout = None
    aux_role = public_aux_camera_role(config)

    def _camera_source(role: str) -> Any:
        for lookup_role in lookup_camera_role_keys(role, config):
            if lookup_role in cameras:
                return cameras.get(lookup_role)
        return None

    return {
        "layout": layout,
        "feeder": _camera_source("feeder"),
        "c_channel_2": _camera_source("c_channel_2"),
        "c_channel_3": _camera_source("c_channel_3"),
        aux_role: _camera_source(aux_role),
        "classification_top": _camera_source("classification_top"),
        "classification_bottom": _camera_source("classification_bottom"),
    }


def _camera_assignments_complete(camera_assignments: dict[str, Any]) -> bool:
    layout = camera_assignments.get("layout")
    if layout not in {"default", "split_feeder"}:
        return False
    if layout == "split_feeder":
        aux_role = next(
            (role for role in ("classification_channel", "carousel") if role in camera_assignments),
            "carousel",
        )
        required_roles = ("c_channel_2", "c_channel_3", aux_role)
    else:
        required_roles = ("feeder",)
    return all(camera_assignments.get(role) is not None for role in required_roles)


def _legacy_feeding_mode_from_config(config: Dict[str, Any]) -> str:
    feeding = config.get("feeding", {})
    if not isinstance(feeding, dict):
        return "auto_channels"
    mode = feeding.get("mode", "auto_channels")
    if mode not in {"auto_channels", "manual_carousel"}:
        return "auto_channels"
    return cast(str, mode)


def _machine_setup_key_from_config(config: Dict[str, Any]) -> str:
    machine_setup = config.get("machine_setup", {})
    if isinstance(machine_setup, dict):
        setup_key = normalize_machine_setup_key(machine_setup.get("type"))
        if setup_key is not None:
            return setup_key
    return machine_setup_key_from_feeding_mode(_legacy_feeding_mode_from_config(config))


def _machine_setup_payload(setup_key: str) -> dict[str, Any]:
    return get_machine_setup_definition(setup_key).to_dict()


def _feeding_mode_from_config(config: Dict[str, Any]) -> str:
    return get_machine_setup_definition(_machine_setup_key_from_config(config)).feeding_mode


def _persist_machine_setup(config: Dict[str, Any], setup_key: str) -> Dict[str, Any]:
    definition = get_machine_setup_definition(setup_key)

    machine_setup = config.get("machine_setup", {})
    if not isinstance(machine_setup, dict):
        machine_setup = {}
    config["machine_setup"] = {
        **machine_setup,
        "type": definition.key,
    }

    feeding = config.get("feeding", {})
    if not isinstance(feeding, dict):
        feeding = {}
    config["feeding"] = {
        **feeding,
        "mode": definition.feeding_mode,
    }
    return config


def _current_stepper_direction_payload() -> list[dict[str, Any]]:
    _, config = _read_machine_params_config()
    inverts = config.get("stepper_direction_inverts", {})
    if not isinstance(inverts, dict):
        inverts = {}

    active_irl = shared_state.getActiveIRL()
    entries: list[dict[str, Any]] = []
    for logical_name, attr_base in LOGICAL_STEPPER_BINDING_BASES.items():
        attr_name = attr_base if attr_base.endswith("_stepper") else f"{attr_base}_stepper"
        stepper = getattr(active_irl, attr_name, None) if active_irl is not None else None
        live_inverted = (
            bool(getattr(stepper, "direction_inverted"))
            if stepper is not None and hasattr(stepper, "direction_inverted")
            else None
        )
        entries.append(
            {
                "name": logical_name,
                "label": STEPPER_LABELS.get(logical_name, logical_name),
                "inverted": bool(inverts.get(logical_name, False)),
                "live_inverted": live_inverted,
                "available": stepper is not None,
            }
        )
    return entries


def _recommended_layout(config: Dict[str, Any], board_summaries: list[dict[str, Any]]) -> str:
    camera_assignments = _camera_assignments_from_config(config)
    aux_role = public_aux_camera_role(config)
    configured = camera_assignments.get("layout")
    if configured in {"default", "split_feeder"}:
        return configured
    if any(
        camera_assignments.get(role) is not None
        for role in ("c_channel_2", "c_channel_3", aux_role)
    ):
        return "split_feeder"
    if camera_assignments.get("feeder") is not None:
        return "default"

    logical_steppers = {
        logical_name
        for board in board_summaries
        for logical_name in board.get("logical_steppers", [])
        if isinstance(logical_name, str)
    }
    split_feeder_ready = {"c_channel_2_rotor", "c_channel_3_rotor", "carousel"}.issubset(logical_steppers)
    return "split_feeder" if split_feeder_ready else "default"


def _discover_control_board_summary() -> dict[str, Any]:
    active_irl = shared_state.getActiveIRL()
    if active_irl is not None:
        live_boards = getattr(active_irl, "control_boards", {})
        if isinstance(live_boards, dict) and live_boards:
            board_summaries = [_board_summary(board) for board in live_boards.values()]
            return _build_discovery_payload(
                board_summaries=board_summaries,
                mcu_ports=sorted({summary["port"] for summary in board_summaries if summary.get("port")}),
                source="live",
                issue_messages=[],
            )

    # If a hardware worker is in flight (initialize/home), it owns the serial
    # ports — running a fresh scan here would race for the same buses and both
    # sides come up empty. Pause discovery and let the worker finish.
    worker = shared_state.hardware_worker_thread
    if (worker is not None and worker.is_alive()) or shared_state.hardware_state in (
        "homing",
        "initializing",
    ):
        return _build_discovery_payload(
            board_summaries=[],
            mcu_ports=MCUBus.enumerate_buses(),
            source="skipped",
            issue_messages=[
                "Hardware operation in progress; pausing fresh board discovery."
            ],
        )

    gc = shared_state.gc_ref
    if gc is None:
        return _build_discovery_payload(
            board_summaries=[],
            mcu_ports=MCUBus.enumerate_buses(),
            source="unavailable",
            issue_messages=["Global config is not initialized yet."],
        )

    discovered_boards: list[Any] = []
    mcu_ports = MCUBus.enumerate_buses()
    try:
        discovered_boards = discover_control_boards(
            gc,
            required_stepper_names=(),
            attempts=2,
            retry_delay_s=0.2,
        )
        board_summaries = [_board_summary(board) for board in discovered_boards]
        return _build_discovery_payload(
            board_summaries=board_summaries,
            mcu_ports=mcu_ports,
            source="scan",
            issue_messages=[],
        )
    except Exception as exc:
        return _build_discovery_payload(
            board_summaries=[],
            mcu_ports=mcu_ports,
            source="scan_error",
            issue_messages=[str(exc)],
        )
    finally:
        _close_discovered_boards(discovered_boards)


_MCU_VIDS = {0x2E8A}  # Raspberry Pi Pico (Feeder / Distribution controllers)


def _format_vid_pid(vid: int | None, pid: int | None) -> str | None:
    if vid is None or pid is None:
        return None
    return f"{vid:04x}:{pid:04x}"


def _probe_waveshare_servo_count(device_path: str) -> int:
    """Open the serial port as a Waveshare SC servo bus and ping IDs 1..10.

    Returns the number of servos that responded, or 0 if the port cannot be
    opened or nothing on the bus speaks the SC protocol.
    """
    try:
        from hardware.waveshare_bus_service import get_waveshare_bus_service
    except Exception:
        return 0

    try:
        service = get_waveshare_bus_service(device_path, timeout=0.01)
    except Exception:
        return 0
    try:
        return service.probe_servo_count(1, 10)
    except Exception:
        return 0


def _enumerate_usb_devices(
    *, board_summaries: list[dict[str, Any]], probe_servo_buses: bool
) -> list[dict[str, Any]]:
    """List every USB serial device with its classification.

    - Ports that match one of the discovered control boards are marked
      ``controller`` and carry the board family / role / logical steppers.
    - Remaining USB serial ports are probed as Waveshare servo buses (unless
      ``probe_servo_buses`` is False) and labelled ``servo_bus`` if any servo
      answers, or ``unknown`` otherwise.
    """
    boards_by_port: dict[str, dict[str, Any]] = {}
    for board in board_summaries:
        port = board.get("port")
        if isinstance(port, str) and port:
            boards_by_port[port] = board

    comports_by_device: dict[str, Any] = {}
    try:
        for port in serial.tools.list_ports.comports():
            device_path = getattr(port, "device", None)
            if isinstance(device_path, str) and device_path:
                comports_by_device[device_path] = port
    except Exception:
        comports_by_device = {}

    devices: list[dict[str, Any]] = []
    seen_devices: set[str] = set()

    # 1. Always surface every discovered control board, even when pyserial
    #    did not expose a VID for that port (common for CDC-ACM on some hosts).
    for device_path, board in boards_by_port.items():
        meta = comports_by_device.get(device_path)
        devices.append(
            {
                "device": device_path,
                "product": (getattr(meta, "product", None) if meta else None)
                or board.get("device_name")
                or "Control board",
                "serial": getattr(meta, "serial_number", None) if meta else None,
                "vid_pid": _format_vid_pid(
                    getattr(meta, "vid", None) if meta else None,
                    getattr(meta, "pid", None) if meta else None,
                ),
                "category": "controller",
                "use_by_default": True,
                "family": board.get("family"),
                "role": board.get("role"),
                "device_name": board.get("device_name"),
                "logical_steppers": list(board.get("logical_steppers", [])),
                "servo_count": int(board.get("servo_count", 0)),
                "detail": ", ".join(board.get("logical_steppers", []) or [])
                or "No logical steppers",
            }
        )
        seen_devices.add(device_path)

    # 2. Walk every other USB serial port and classify it.
    for device_path, port in comports_by_device.items():
        if device_path in seen_devices:
            continue
        vid = getattr(port, "vid", None)
        if vid is None:
            # Skip non-USB serial endpoints (bluetooth, debug UARTs, ...).
            continue

        entry: dict[str, Any] = {
            "device": device_path,
            "product": getattr(port, "product", None) or "Serial device",
            "serial": getattr(port, "serial_number", None),
            "vid_pid": _format_vid_pid(vid, getattr(port, "pid", None)),
            "category": "unknown",
            "use_by_default": False,
            "detail": "",
        }

        if vid in _MCU_VIDS:
            entry.update(
                {
                    "category": "unrecognised_controller",
                    "detail": "MCU did not respond to SorterInterface probe.",
                }
            )
        elif probe_servo_buses:
            servo_count = _probe_waveshare_servo_count(device_path)
            if servo_count > 0:
                entry.update(
                    {
                        "category": "servo_bus",
                        "use_by_default": True,
                        "servo_count": servo_count,
                        "detail": f"Responded to {servo_count} servo ID(s)",
                    }
                )
            else:
                entry["detail"] = "No response to Waveshare servo ping."
        else:
            entry["detail"] = "Skipped servo probe (hardware busy)."

        devices.append(entry)
        seen_devices.add(device_path)

    devices.sort(key=lambda item: (_device_sort_key(item), item.get("device") or ""))
    return devices


def _device_sort_key(entry: dict[str, Any]) -> int:
    category = entry.get("category")
    if category == "controller":
        return 0
    if category == "servo_bus":
        return 1
    if category == "unrecognised_controller":
        return 2
    return 3


def _build_discovery_payload(
    *,
    board_summaries: list[dict[str, Any]],
    mcu_ports: list[str],
    source: str,
    issue_messages: list[str],
) -> dict[str, Any]:
    available_stepper_names = {
        logical_name
        for board in board_summaries
        for logical_name in board.get("logical_steppers", [])
        if isinstance(logical_name, str)
    }
    missing_required_steppers = sorted(
        stepper_name
        for stepper_name in REQUIRED_STEPPER_NAMES
        if stepper_name not in available_stepper_names
    )
    roles = {
        "feeder": any(board.get("role") == "feeder" for board in board_summaries),
        "distribution": any(board.get("role") == "distribution" for board in board_summaries),
    }
    pca_available = any(int(board.get("servo_count", 0)) > 0 for board in board_summaries)

    active_irl = shared_state.getActiveIRL()
    live_servo_port: str | None = None
    live_servo_count = 0
    if active_irl is not None:
        servo_controller = getattr(active_irl, "servo_controller", None)
        bus_service = getattr(servo_controller, "bus_service", None)
        live_servo_port = getattr(bus_service, "port", None)
        live_servo_count = len(getattr(active_irl, "servos", []))

    probe_servo_buses = shared_state.hardware_state == "standby" and live_servo_port is None
    usb_devices = _enumerate_usb_devices(
        board_summaries=board_summaries,
        probe_servo_buses=probe_servo_buses,
    )

    if live_servo_port is not None:
        matched_live_port = False
        for device in usb_devices:
            if device.get("device") != live_servo_port:
                continue
            device["category"] = "servo_bus"
            device["use_by_default"] = True
            device["servo_count"] = max(int(device.get("servo_count", 0) or 0), live_servo_count)
            device["detail"] = f"Using active controller bus ({live_servo_count} servo(s))"
            matched_live_port = True
            break

        if not matched_live_port:
            port_meta = next(
                (
                    port for port in serial.tools.list_ports.comports()
                    if getattr(port, "device", None) == live_servo_port
                ),
                None,
            )
            usb_devices.append(
                {
                    "device": live_servo_port,
                    "product": getattr(port_meta, "product", None) or "Waveshare servo bus",
                    "serial": getattr(port_meta, "serial_number", None),
                    "vid_pid": _format_vid_pid(
                        getattr(port_meta, "vid", None),
                        getattr(port_meta, "pid", None),
                    ),
                    "category": "servo_bus",
                    "use_by_default": True,
                    "servo_count": live_servo_count,
                    "detail": f"Using active controller bus ({live_servo_count} servo(s))",
                }
            )

    waveshare_ports = [
        {
            "device": device["device"],
            "product": device.get("product") or "Unknown serial device",
            "serial": device.get("serial"),
        }
        for device in usb_devices
        if device.get("category") == "servo_bus"
    ]

    issues = list(issue_messages)
    if not board_summaries and not issue_messages:
        issues.append("No control boards detected.")
    if board_summaries and not roles["feeder"]:
        issues.append("No feeder control board detected.")
    if board_summaries and not roles["distribution"]:
        issues.append("No distribution control board detected.")
    if missing_required_steppers:
        issues.append(
            "Missing required steppers: " + ", ".join(missing_required_steppers)
        )

    return {
        "scanned_at_ms": int(time.time() * 1000),
        "source": source,
        "mcu_ports": mcu_ports,
        "boards": board_summaries,
        "roles": roles,
        "missing_required_steppers": missing_required_steppers,
        "pca_available": pca_available,
        "waveshare_ports": waveshare_ports,
        "usb_devices": usb_devices,
        "issues": issues,
    }


def _serialize_machine_profile(active_irl: Any | None) -> dict[str, Any] | None:
    if active_irl is None:
        return None
    profile = getattr(active_irl, "machine_profile", None)
    if profile is None:
        return None
    if is_dataclass(profile):
        return asdict(cast(Any, profile))
    return None


@router.get("/api/setup-wizard")
def get_setup_wizard_summary() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    camera_assignments = _camera_assignments_from_config(config)
    feeding_mode = _feeding_mode_from_config(config)
    machine_setup_key = _machine_setup_key_from_config(config)
    servo_settings = _servo_settings_from_config(config)
    discovery = _discover_control_board_summary()
    active_irl = shared_state.getActiveIRL()

    readiness = {
        "machine_named": bool(getMachineNickname()),
        "boards_detected": len(discovery["boards"]) > 0,
        "camera_layout_selected": camera_assignments["layout"] in {"default", "split_feeder"},
        "cameras_assigned": _camera_assignments_complete(camera_assignments),
        "servo_configured": (
            servo_settings["backend"] == "waveshare"
            or bool(discovery["pca_available"])
        )
        and int(servo_settings.get("layer_count", 0)) > 0,
        "ready_for_motion_test": shared_state.hardware_state == "ready",
    }

    return {
        "machine": {
            "machine_id": getMachineId(),
            "nickname": getMachineNickname(),
        },
        "hardware": {
            "state": shared_state.hardware_state,
            "error": shared_state.hardware_error,
            "homing_step": shared_state.hardware_homing_step,
            "machine_profile": _serialize_machine_profile(active_irl),
        },
        "config": {
            "camera_assignments": camera_assignments,
            "feeding": {
                "mode": feeding_mode,
            },
            "machine_setup": _machine_setup_payload(machine_setup_key),
            "servo": {
                "backend": servo_settings["backend"],
                "layer_count": servo_settings["layer_count"],
                "port": servo_settings["port"],
            },
            "stepper_directions": _current_stepper_direction_payload(),
        },
        "discovery": {
            **discovery,
            "recommended_camera_layout": _recommended_layout(config, discovery["boards"]),
        },
        "readiness": readiness,
    }


@router.get("/api/feeding-mode")
def get_feeding_mode() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    machine_setup_key = _machine_setup_key_from_config(config)
    return {
        "mode": _feeding_mode_from_config(config),
        "machine_setup": _machine_setup_payload(machine_setup_key),
        "requires_rehome": True,
    }


@router.post("/api/feeding-mode")
def set_feeding_mode(payload: FeedingModePayload) -> Dict[str, Any]:
    params_path, config = _read_machine_params_config()
    current_setup_key = _machine_setup_key_from_config(config)
    if payload.mode == "manual_carousel":
        next_setup_key = MANUAL_CAROUSEL_SETUP
    elif current_setup_key == CLASSIFICATION_CHANNEL_SETUP:
        next_setup_key = CLASSIFICATION_CHANNEL_SETUP
    else:
        next_setup_key = STANDARD_CAROUSEL_SETUP

    config = _persist_machine_setup(config, next_setup_key)

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    return {
        "ok": True,
        "mode": get_machine_setup_definition(next_setup_key).feeding_mode,
        "machine_setup": _machine_setup_payload(next_setup_key),
        "requires_rehome": True,
    }


@router.get("/api/machine-setup")
def get_machine_setup() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    setup_key = _machine_setup_key_from_config(config)
    return {
        "setup": setup_key,
        "machine_setup": _machine_setup_payload(setup_key),
        "options": get_machine_setup_options(),
        "requires_rehome": True,
    }


@router.post("/api/machine-setup")
def set_machine_setup(payload: MachineSetupPayload) -> Dict[str, Any]:
    params_path, config = _read_machine_params_config()
    config = _persist_machine_setup(config, payload.setup)

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    return {
        "ok": True,
        "setup": payload.setup,
        "machine_setup": _machine_setup_payload(payload.setup),
        "options": get_machine_setup_options(),
        "requires_rehome": True,
    }


@router.get("/api/setup-wizard/stepper-directions")
def get_stepper_directions() -> Dict[str, Any]:
    return {"ok": True, "steppers": _current_stepper_direction_payload()}


@router.post("/api/setup-wizard/stepper-directions/{stepper_name}")
def set_stepper_direction(stepper_name: str, payload: StepperDirectionPayload) -> Dict[str, Any]:
    if stepper_name not in LOGICAL_STEPPER_BINDING_BASES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown logical stepper '{stepper_name}'.",
        )

    params_path, config = _read_machine_params_config()
    inverts = config.get("stepper_direction_inverts", {})
    if not isinstance(inverts, dict):
        inverts = {}
    inverts = {**inverts, stepper_name: bool(payload.inverted)}
    config["stepper_direction_inverts"] = inverts

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    applied_live = False
    active_irl = shared_state.getActiveIRL()
    attr_base = LOGICAL_STEPPER_BINDING_BASES[stepper_name]
    attr_name = attr_base if attr_base.endswith("_stepper") else f"{attr_base}_stepper"
    stepper = getattr(active_irl, attr_name, None) if active_irl is not None else None
    if stepper is not None and hasattr(stepper, "set_direction_inverted"):
        try:
            stepper.set_direction_inverted(bool(payload.inverted))
            applied_live = True
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "stepper": stepper_name,
        "inverted": bool(payload.inverted),
        "applied_live": applied_live,
        "steppers": _current_stepper_direction_payload(),
    }


@router.post("/api/setup-wizard/camera-layout")
def set_setup_camera_layout(payload: CameraLayoutPayload) -> Dict[str, Any]:
    params_path, config = _read_machine_params_config()
    cameras = config.get("cameras", {})
    if not isinstance(cameras, dict):
        cameras = {}
    cameras = {**cameras, "layout": payload.layout}
    config["cameras"] = cameras

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    return {
        "ok": True,
        "layout": payload.layout,
        "camera_assignments": _camera_assignments_from_config(config),
    }
