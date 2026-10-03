from __future__ import annotations

import threading
import time
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import serial.tools.list_ports

from hardware.bus import MCUBus
from hardware.firmware_flash import bootloaderPresent
from irl.config import _requiredCanonicalStepperNames
from irl.parse_user_toml import (
    LOGICAL_STEPPER_BINDING_BASES,
    loadStepperBindingOverrides,
)
from local_state import get_or_create_machine_id
from machine_platform.control_board import discover_control_boards
from server import shared_state
import machine_toml
from server.routers.cameras import CAMERA_SETUP_ROLES, _camera_source_for_role
from server.routers.servos import _servo_settings_from_config
from toml_config import getMachineNickname

router = APIRouter()

STEPPER_LABELS: dict[str, str] = {
    "c_channel_1": "C-Channel 1",
    "c_channel_2": "C-Channel 2",
    "c_channel_3": "C-Channel 3",
    "c_channel_4": "C-Channel 4",
    "carousel": "Carousel",
    "chute": "Chute",
}

C4_LOGICAL_STEPPER = "c_channel_4"
C4_BACKING_STEPPER = "carousel"


class StepperDirectionPayload(BaseModel):
    inverted: bool


def _board_summary(board: Any) -> dict[str, Any]:
    interface = getattr(board, "interface", None)
    return {
        "family": getattr(board.identity, "family", "unknown"),
        "role": getattr(board.identity, "role", "unknown"),
        "hw_id": getattr(interface, "hw_id", "unknown"),
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
    return {role: _camera_source_for_role(config, role) for role in CAMERA_SETUP_ROLES}


def _camera_assignments_complete(camera_assignments: dict[str, Any]) -> bool:
    return all(
        camera_assignments.get(role) is not None
        for role in ("c_channel_2", "c_channel_3", "classification_channel")
    )


def _current_stepper_direction_payload() -> list[dict[str, Any]]:
    config = machine_toml.read()
    inverts = config.get("stepper_direction_inverts", {})
    if not isinstance(inverts, dict):
        inverts = {}

    active_irl = shared_state.getActiveIRL()
    entries: list[dict[str, Any]] = []
    logical_names = [
        C4_LOGICAL_STEPPER if name == C4_BACKING_STEPPER else name
        for name in LOGICAL_STEPPER_BINDING_BASES
    ]

    for logical_name in logical_names:
        attr_base = _stepper_attr_base(logical_name)
        attr_name = attr_base if attr_base.endswith("_stepper") else f"{attr_base}_stepper"
        stepper = getattr(active_irl, attr_name, None) if active_irl is not None else None
        config_key = _stepper_config_key(logical_name)
        live_inverted = (
            bool(getattr(stepper, "direction_inverted"))
            if stepper is not None and hasattr(stepper, "direction_inverted")
            else None
        )
        entries.append(
            {
                "name": logical_name,
                "label": STEPPER_LABELS.get(logical_name, logical_name),
                "inverted": bool(inverts.get(config_key, False)),
                "live_inverted": live_inverted,
                "available": stepper is not None,
            }
        )
    return entries


def _stepper_config_key(stepper_name: str) -> str:
    return C4_BACKING_STEPPER if stepper_name == C4_LOGICAL_STEPPER else stepper_name


def _stepper_attr_base(stepper_name: str) -> str:
    config_key = _stepper_config_key(stepper_name)
    return LOGICAL_STEPPER_BINDING_BASES[config_key]


# The boards the last scan or live machine reported. While a hardware worker
# owns the serial ports the wizard shows these instead of an empty list, so a
# step does not read as "no boards" for the seconds the motors power up.
_last_board_summaries: list[dict[str, Any]] = []
# One scan at a time: two scans open the same serial ports and each can come
# back empty. A request that arrives while one runs takes that scan's result.
_scan_lock = threading.Lock()
_last_scan: tuple[float, dict[str, Any]] | None = None
_SCAN_REUSE_S = 2.0


def _discover_control_board_summary() -> dict[str, Any]:
    global _last_board_summaries, _last_scan
    active_irl = shared_state.getActiveIRL()
    if active_irl is not None:
        live_boards = getattr(active_irl, "control_boards", {})
        if isinstance(live_boards, dict) and live_boards:
            board_summaries = [_board_summary(board) for board in live_boards.values()]
            _last_board_summaries = board_summaries
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
        if _last_board_summaries:
            return _build_discovery_payload(
                board_summaries=_last_board_summaries,
                mcu_ports=sorted({s["port"] for s in _last_board_summaries if s.get("port")}),
                source="cached",
                issue_messages=[],
            )
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

    with _scan_lock:
        if _last_scan is not None and time.monotonic() - _last_scan[0] < _SCAN_REUSE_S:
            return _last_scan[1]
        payload = _scan_control_boards(gc)
        _last_scan = (time.monotonic(), payload)
        return payload


def _scan_control_boards(gc: Any) -> dict[str, Any]:
    global _last_board_summaries
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
        _last_board_summaries = board_summaries
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
    gc = shared_state.gc_ref
    try:
        binding_overrides = loadStepperBindingOverrides(gc) if gc is not None else {}
    except Exception:
        binding_overrides = {}
    required_stepper_names = _requiredCanonicalStepperNames(binding_overrides)
    missing_required_steppers = sorted(
        stepper_name
        for stepper_name in required_stepper_names
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

    # A Pico with no firmware never answers on serial; it shows up as the RPI-RP2
    # drive instead, and only a recovery flash from Settings brings it up.
    bootloader_board = not board_summaries and bootloaderPresent()
    issues = list(issue_messages)
    if not board_summaries and not issue_messages:
        issues.append("No control boards detected.")
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
        "bootloader_board": bootloader_board,
        "issues": issues,
    }


@router.get("/api/setup-wizard/needed")
def get_setup_wizard_needed() -> Dict[str, bool]:
    # A machine that has never been through the wizard has neither a name nor a
    # single camera (first boot writes -1 or nothing). Cheap on purpose: the
    # Dashboard asks on every first load, and the full summary probes the USB buses.
    config = machine_toml.read()
    assignments = _camera_assignments_from_config(config)
    any_camera = any(
        value is not None and value != -1
        for role, value in assignments.items()
    )
    return {"needed": not getMachineNickname() and not any_camera}


@router.get("/api/setup-wizard")
def get_setup_wizard_summary() -> Dict[str, Any]:
    config = machine_toml.read()
    camera_assignments = _camera_assignments_from_config(config)
    servo_settings = _servo_settings_from_config(config)
    discovery = _discover_control_board_summary()

    readiness = {
        "machine_named": bool(getMachineNickname()),
        "boards_detected": bool(discovery["boards"]) and not discovery["missing_required_steppers"],
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
            "machine_id": shared_state.gc_ref.machine_id if shared_state.gc_ref is not None else get_or_create_machine_id(),
            "nickname": getMachineNickname(),
        },
        "hardware": {
            "state": shared_state.hardware_state,
            "error": shared_state.hardware_error,
            "homing_step": shared_state.hardware_homing_step,
        },
        "config": {
            "camera_assignments": camera_assignments,
            "servo": {
                "backend": servo_settings["backend"],
                "layer_count": servo_settings["layer_count"],
                "port": servo_settings["port"],
            },
            "stepper_directions": _current_stepper_direction_payload(),
        },
        "discovery": discovery,
        "readiness": readiness,
    }


@router.get("/api/setup-wizard/stepper-directions")
def get_stepper_directions() -> Dict[str, Any]:
    return {"ok": True, "steppers": _current_stepper_direction_payload()}


@router.post("/api/setup-wizard/stepper-directions/{stepper_name}")
def set_stepper_direction(stepper_name: str, payload: StepperDirectionPayload) -> Dict[str, Any]:
    if stepper_name not in LOGICAL_STEPPER_BINDING_BASES and stepper_name != C4_LOGICAL_STEPPER:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown logical stepper '{stepper_name}'.",
        )
    config_key = _stepper_config_key(stepper_name)

    with machine_toml.edit() as config:
        inverts = config.get("stepper_direction_inverts", {})
        if not isinstance(inverts, dict):
            inverts = {}
        inverts = {**inverts, config_key: bool(payload.inverted)}
        config["stepper_direction_inverts"] = inverts

    applied_live = False
    active_irl = shared_state.getActiveIRL()
    attr_base = _stepper_attr_base(stepper_name)
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
