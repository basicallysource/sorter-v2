"""Layer servos, on PCA9685 channels or the Waveshare bus: settings, speeds, calibration and moves."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import machine_toml
from hardware.waveshare_bus_service import get_waveshare_bus_service
from bin_layout_store import set_servo_channel_angle
from irl.bin_layout import channelIdForLayer, getBinLayout
from server import shared_state
from server.routers.steppers import _ensure_not_homing
from server.waveshare_inventory import (
    _active_waveshare_service,
    _configured_waveshare_port,
    get_waveshare_inventory_manager,
)

router = APIRouter()

_PCA9685_CHANNEL_COUNT = 16


def _get_waveshare_service() -> Any:
    service = _active_waveshare_service()
    if service is not None:
        return service
    port = _configured_waveshare_port()
    if port is None:
        raise HTTPException(status_code=503, detail="No Waveshare bus available.")
    return get_waveshare_bus_service(port, timeout=0.02)


def _waveshare_inventory_status(*, port: str | None = None, refresh: bool = False) -> Dict[str, Any]:
    manager = get_waveshare_inventory_manager()
    if refresh:
        return manager.refresh(port=port, allow_active_runtime_scan=True)
    return manager.get_status(port=port)


class ServoChannelConfigPayload(BaseModel):
    id: int | None = None
    invert: bool = False


class ServoHardwareSettingsPayload(BaseModel):
    backend: str = "pca9685"
    open_speed: Optional[int] = None
    close_speed: Optional[int] = None
    homing_speed: Optional[int] = None
    port: Optional[str] = None
    channels: List[ServoChannelConfigPayload] = []


class ServoSetIdPayload(BaseModel):
    new_id: int


class ServoMovePayload(BaseModel):
    position: str  # "open" | "close" | "center"


class ServoNudgePayload(BaseModel):
    degrees: int


class ServoLayerMovePayload(BaseModel):
    angle: int


class ServoLayerLockPayload(BaseModel):
    which: str  # "open" | "closed"
    angle: Optional[int] = None


class ServoLayerClearPayload(BaseModel):
    which: str = "both"  # "open" | "closed" | "both"


def _distribution_layer_count() -> int:
    active_irl = shared_state.getActiveIRL()
    if active_irl is not None:
        layout = getattr(active_irl, "distribution_layout", None)
        if layout is not None and hasattr(layout, "layers"):
            return len(layout.layers)
    return len(getBinLayout().layers)


def _pca_available_servo_channels() -> List[int]:
    active_irl = shared_state.getActiveIRL()
    if active_irl is not None:
        interfaces = getattr(active_irl, "interfaces", {})
        channels: set[int] = set()
        if isinstance(interfaces, dict):
            for interface in interfaces.values():
                for servo in getattr(interface, "servos", []):
                    channel = getattr(servo, "channel", None)
                    if isinstance(channel, int) and not isinstance(channel, bool):
                        channels.add(channel)
        if channels:
            return sorted(channels)
    return list(range(_PCA9685_CHANNEL_COUNT))


def _waveshare_available_servo_ids(config: Dict[str, Any]) -> List[int]:
    found_ids: set[int] = set()

    servo = config.get("servo", {})
    if isinstance(servo, dict):
        channels_raw = servo.get("channels", [])
        if isinstance(channels_raw, list):
            for item in channels_raw:
                if not isinstance(item, dict):
                    continue
                channel_id = item.get("id")
                if isinstance(channel_id, int) and not isinstance(channel_id, bool) and channel_id > 0:
                    found_ids.add(channel_id)

    active_irl = shared_state.getActiveIRL()
    live_servos = []
    if active_irl is not None:
        live_servos = list(getattr(active_irl, "servos", []))
        for servo_obj in live_servos:
            channel = getattr(servo_obj, "channel", None)
            if isinstance(channel, int) and not isinstance(channel, bool) and channel > 0:
                found_ids.add(channel)

    port = None
    servo = config.get("servo", {})
    if isinstance(servo, dict):
        port = servo.get("port") if isinstance(servo.get("port"), str) else None
    try:
        found_ids.update(get_waveshare_inventory_manager().get_known_servo_ids(port=port))
    except Exception:
        pass

    return sorted(found_ids)


def _live_servo_for_layer(layer_index: int) -> Any:
    active_irl = shared_state.getActiveIRL()
    if active_irl is None:
        raise HTTPException(status_code=503, detail="Servo controller not initialized.")

    servos = list(getattr(active_irl, "servos", []))
    if layer_index < 0:
        raise HTTPException(status_code=404, detail=f"Unknown storage layer {layer_index + 1}.")
    if layer_index >= len(servos):
        # The live servos are built when the machine homes, so a layer added
        # since then has none yet.
        raise HTTPException(
            status_code=409,
            detail=f"Layer {layer_index + 1} has no servo running yet. Save the layers, then home the machine.",
        )
    return servos[layer_index]


def _live_servo_feedback_for_layer(layer_index: int, servo: Any | None = None) -> Dict[str, Any]:
    servo = servo if servo is not None else _live_servo_for_layer(layer_index)
    channel = getattr(servo, "channel", None)
    base: Dict[str, Any] = {
        "layer_index": layer_index,
        "channel": channel,
        "available": False,
    }

    if servo is None:
        return base

    if hasattr(servo, "feedback"):
        try:
            feedback = servo.feedback()
            if isinstance(feedback, dict):
                return {
                    "layer_index": layer_index,
                    **feedback,
                }
        except Exception as e:
            return {**base, "error": str(e)}

    if not hasattr(servo, "position"):
        return base

    try:
        position = int(servo.position)
        result = {
            **base,
            "available": True,
            "position": position,
            "angle": position // 10,
            "is_open": bool(servo.isOpen()) if hasattr(servo, "isOpen") else None,
        }
        if hasattr(servo, "is_calibrated"):
            result.update(_servo_calibration_state(servo))
        return result
    except Exception as e:
        return {**base, "error": str(e)}


_SERVO_SPEED_FLOOR_TENTHS = 10  # 1°/s minimum floor sent to firmware


def _apply_pca_servo_speed(servo: Any, speed_deg_per_sec: int | None) -> None:
    if speed_deg_per_sec is None:
        return
    if not hasattr(servo, "set_speed_limits"):
        return
    try:
        servo.set_speed_limits(_SERVO_SPEED_FLOOR_TENTHS, speed_deg_per_sec * 10)
    except Exception:
        pass


_SERVO_SPEED_RANGE = (1, 2000)


def _clamp_servo_speed(value: int | None) -> int | None:
    if value is None:
        return None
    return max(_SERVO_SPEED_RANGE[0], min(_SERVO_SPEED_RANGE[1], int(value)))


def _servo_hardware_issues() -> List[Dict[str, Any]]:
    active_irl = shared_state.getActiveIRL()
    if active_irl is None:
        return []
    servo_controller = getattr(active_irl, "servo_controller", None)
    issues = getattr(servo_controller, "issues", None)
    if not isinstance(issues, list):
        return []
    return [issue for issue in issues if isinstance(issue, dict)]


def _servo_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    servo = config.get("servo", {})
    if not isinstance(servo, dict):
        servo = {}

    backend = servo.get("backend", "pca9685")
    if backend not in {"pca9685", "waveshare"}:
        backend = "pca9685"

    port = servo.get("port")
    if port is not None and not isinstance(port, str):
        port = None

    layer_count = _distribution_layer_count()
    parsed_channels: List[Dict[str, Any]] = []
    channels_raw = servo.get("channels", [])
    if isinstance(channels_raw, list):
        for item in channels_raw:
            if not isinstance(item, dict):
                continue
            channel_id = item.get("id")
            if channel_id is None:
                parsed_channels.append({"id": None, "invert": bool(item.get("invert", False))})
                continue
            if not isinstance(channel_id, int) or isinstance(channel_id, bool):
                parsed_channels.append({"id": None, "invert": bool(item.get("invert", False))})
                continue
            parsed_channels.append(
                {
                    "id": channel_id,
                    "invert": bool(item.get("invert", False)),
                }
            )

    channels: List[Dict[str, Any]] = []
    for index in range(layer_count):
        existing = parsed_channels[index] if index < len(parsed_channels) else None
        default_id = index + 1 if backend == "waveshare" else index
        channels.append(
            {
                "id": (int(existing["id"]) if existing is not None and existing["id"] is not None else None)
                if existing is not None
                else default_id,
                "invert": bool(existing["invert"]) if existing is not None else False,
            }
        )

    speeds: Dict[str, int | None] = {}
    for key in ("open_speed", "close_speed", "homing_speed"):
        value = servo.get(key)
        valid = isinstance(value, int) and not isinstance(value, bool) and value > 0
        speeds[key] = _clamp_servo_speed(value) if valid else None

    return {
        "backend": backend,
        **speeds,
        "port": port.strip() if isinstance(port, str) and port.strip() else None,
        "channels": channels,
        "layer_count": layer_count,
        "available_channel_ids": (
            _pca_available_servo_channels()
            if backend == "pca9685"
            else _waveshare_available_servo_ids(config)
        ),
        "supports_calibration": backend == "waveshare",
        "issues": _servo_hardware_issues(),
    }


@router.post("/api/hardware-config/servo")
def save_servo_hardware_config(
    payload: ServoHardwareSettingsPayload,
) -> Dict[str, Any]:
    backend = payload.backend if payload.backend in {"pca9685", "waveshare"} else "pca9685"
    open_speed = _clamp_servo_speed(payload.open_speed)
    close_speed = _clamp_servo_speed(payload.close_speed)
    homing_speed = _clamp_servo_speed(payload.homing_speed)
    port = payload.port.strip() if isinstance(payload.port, str) and payload.port.strip() else None
    available_pca_channels = _pca_available_servo_channels()
    # Validate against the persisted layout we actually index into below, not the
    # live distribution layout. After a layer add/remove the storage-layers save
    # has already rewritten the config, but the running hardware still carries the
    # old layer count until a restart — trusting it here rejected valid saves.
    current_layers = getBinLayout().layers
    layer_count = len(current_layers)

    if len(payload.channels) != layer_count:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {layer_count} layer servo assignments, got {len(payload.channels)}.",
        )

    channels: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, channel in enumerate(payload.channels):
        channel_id = int(channel.id) if channel.id is not None else None
        layer_enabled = bool(getattr(current_layers[index], "enabled", True))

        if channel_id is None:
            if layer_enabled:
                raise HTTPException(
                    status_code=400,
                    detail=f"Layer {index + 1} needs a servo assignment while the layer is active.",
                )
            channels.append({"id": None, "invert": bool(channel.invert)})
            continue

        if backend == "waveshare":
            valid = 1 <= channel_id <= 253
            help_text = "an SC servo ID between 1 and 253"
        else:
            valid = channel_id >= 0 and (
                not available_pca_channels or channel_id in available_pca_channels
            )
            help_text = "a valid PCA servo channel"

        if not valid:
            raise HTTPException(
                status_code=400,
                detail=f"Layer {index + 1} needs {help_text}.",
            )
        if channel_id in seen_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Servo assignment {channel_id} is used more than once.",
            )
        seen_ids.add(channel_id)
        channels.append({"id": channel_id, "invert": bool(channel.invert)})

    with machine_toml.edit() as config:
        previous = _servo_settings_from_config(config)

        servo_table: Dict[str, Any] = {"backend": backend, "channels": channels}
        if backend == "pca9685":
            if open_speed is not None:
                servo_table["open_speed"] = open_speed
            if close_speed is not None:
                servo_table["close_speed"] = close_speed
            if homing_speed is not None:
                servo_table["homing_speed"] = homing_speed
        if backend == "waveshare":
            if port is not None:
                servo_table["port"] = port
            existing_servo_table = config.get("servo", {})
            previous_highest_seen = (
                existing_servo_table.get("highest_seen_id")
                if isinstance(existing_servo_table, dict)
                else None
            )
            if (
                isinstance(previous_highest_seen, int)
                and not isinstance(previous_highest_seen, bool)
                and previous_highest_seen > 0
            ):
                servo_table["highest_seen_id"] = previous_highest_seen

        config["servo"] = servo_table

    previous_ids = [int(channel["id"]) if channel["id"] is not None else None for channel in previous["channels"]]
    channel_ids = [int(channel["id"]) if channel["id"] is not None else None for channel in channels]
    channel_inverts = [bool(channel["invert"]) for channel in channels]

    structural_change = (
        backend != previous["backend"]
        or channel_ids != previous_ids
        or (backend == "waveshare" and port != previous["port"])
    )

    active_irl = shared_state.getActiveIRL()
    has_live_hardware = active_irl is not None

    applied_live = False
    if not structural_change and has_live_hardware:
        try:
            live_servos = list(getattr(active_irl, "servos", [])) if active_irl is not None else []
            if len(live_servos) == len(channels):
                for index, servo in enumerate(live_servos):
                    invert = channel_inverts[index]
                    if backend == "waveshare":
                        if hasattr(servo, "set_invert"):
                            servo.set_invert(invert)
                    else:
                        # PCA open/closed angles are calibrated per-layer via the
                        # Servo Layer Calibrator, not here — only apply speed.
                        if hasattr(servo, "set_motion_speeds"):
                            servo.set_motion_speeds(open_speed, close_speed, homing_speed)
                        _apply_pca_servo_speed(servo, homing_speed)
                applied_live = True
        except Exception:
            applied_live = False

    restart_required = structural_change and has_live_hardware

    if applied_live:
        message = "Servo settings saved and applied live."
    elif structural_change and has_live_hardware:
        message = "Servo settings saved. Re-home hardware to apply changes."
    else:
        message = "Servo settings saved."

    return {
        "ok": True,
        "settings": _servo_settings_from_config(config),
        "applied_live": applied_live,
        "restart_required": restart_required,
        "message": message,
    }


class ServoSpeedSettingsPayload(BaseModel):
    open_speed: Optional[int] = None
    close_speed: Optional[int] = None
    homing_speed: Optional[int] = None


@router.post("/api/hardware-config/servo/speeds")
def save_servo_speeds(payload: ServoSpeedSettingsPayload) -> Dict[str, Any]:
    open_speed = _clamp_servo_speed(payload.open_speed)
    close_speed = _clamp_servo_speed(payload.close_speed)
    homing_speed = _clamp_servo_speed(payload.homing_speed)

    with machine_toml.edit() as config:
        servo = config.get("servo", {})
        if not isinstance(servo, dict):
            servo = {}

        for key, val in [("open_speed", open_speed), ("close_speed", close_speed), ("homing_speed", homing_speed)]:
            if val is not None:
                servo[key] = val
            else:
                servo.pop(key, None)

        config["servo"] = servo

    active_irl = shared_state.getActiveIRL()
    if active_irl is not None:
        try:
            for srv in getattr(active_irl, "servos", []):
                if hasattr(srv, "set_motion_speeds"):
                    srv.set_motion_speeds(open_speed, close_speed, homing_speed)
                # Leave the firmware at the standard speed between moves;
                # sorting re-applies open/close speed per move.
                _apply_pca_servo_speed(srv, homing_speed)
        except Exception:
            pass

    return {"ok": True, "open_speed": open_speed, "close_speed": close_speed, "homing_speed": homing_speed}


@router.post("/api/hardware-config/servo/layers/{layer_index}/nudge")
def nudge_layer_servo(layer_index: int, payload: ServoNudgePayload) -> Dict[str, Any]:
    _ensure_not_homing("nudge a servo")
    servo = _live_servo_for_layer(layer_index)

    if not hasattr(servo, "move_to") or not hasattr(servo, "position"):
        raise HTTPException(status_code=500, detail="Servo does not support position-based movement.")

    try:
        _cfg = machine_toml.read()
        _apply_pca_servo_speed(servo, _servo_settings_from_config(_cfg).get("homing_speed"))

        current_pos = int(servo.position)
        # PCA ServoMotor.position returns tenths-of-degrees, move_to takes degrees 0-180
        # Waveshare BusServo.position returns raw 0-1023, move_to takes angle 0-180
        # Use move_to(angle) which handles mapping internally
        if hasattr(servo, '_angle_to_position'):
            # waveshare bus servo: position is raw, convert to angle space
            limits = getattr(servo, '_min_limit', 0), getattr(servo, '_max_limit', 1023)
            range_size = limits[1] - limits[0]
            if range_size > 0:
                current_angle = int((current_pos - limits[0]) * 180 / range_size)
            else:
                current_angle = 90
        else:
            # PCA servo: position is tenths of degrees
            current_angle = current_pos // 10

        new_angle = max(0, min(180, current_angle + payload.degrees))
        servo.move_to(new_angle)
        feedback = _live_servo_feedback_for_layer(layer_index, servo)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to nudge layer {layer_index + 1} servo: {e}")

    return {
        "ok": True,
        "layer_index": layer_index,
        "degrees": payload.degrees,
        "new_angle": new_angle,
        "feedback": feedback,
    }


@router.post("/api/hardware-config/servo/layers/{layer_index}/move-to")
def move_to_layer_servo(layer_index: int, payload: ServoLayerMovePayload) -> Dict[str, Any]:
    _ensure_not_homing("move a servo")
    servo = _live_servo_for_layer(layer_index)
    if not hasattr(servo, "move_to"):
        raise HTTPException(status_code=500, detail="Servo does not support position-based movement.")

    angle = max(0, min(180, int(payload.angle)))
    try:
        _cfg = machine_toml.read()
        _apply_pca_servo_speed(servo, _servo_settings_from_config(_cfg).get("homing_speed"))
        servo.move_to(angle)
        feedback = _live_servo_feedback_for_layer(layer_index, servo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to move layer {layer_index + 1} servo: {e}")

    return {
        "ok": True,
        "layer_index": layer_index,
        "new_angle": angle,
        "feedback": feedback,
    }


def _servo_calibration_state(servo: Any) -> Dict[str, Any]:
    open_angle = getattr(servo, "open_angle", None)
    closed_angle = getattr(servo, "closed_angle", None)
    return {
        "open_angle": open_angle if isinstance(open_angle, int) else None,
        "closed_angle": closed_angle if isinstance(closed_angle, int) else None,
        "calibrated": bool(getattr(servo, "is_calibrated", True)),
    }


@router.post("/api/hardware-config/servo/layers/{layer_index}/lock")
def lock_layer_servo_angle(layer_index: int, payload: ServoLayerLockPayload) -> Dict[str, Any]:
    _ensure_not_homing("lock a servo angle")
    if payload.which not in {"open", "closed"}:
        raise HTTPException(status_code=400, detail="which must be 'open' or 'closed'.")
    servo = _live_servo_for_layer(layer_index)

    if payload.angle is not None:
        angle = max(0, min(180, int(payload.angle)))
    else:
        current = getattr(servo, "angle", None)
        if current is None:
            position = getattr(servo, "position", None)
            current = int(position) // 10 if position is not None else None
        if current is None:
            raise HTTPException(
                status_code=400,
                detail="Could not read the servo's current angle to lock in.",
            )
        angle = max(0, min(180, int(current)))

    layout = getBinLayout()
    if layer_index < 0 or layer_index >= len(layout.layers):
        raise HTTPException(status_code=404, detail=f"Unknown storage layer {layer_index + 1}.")
    # Calibration is per-channel (machine-level), not stored on the layout — so
    # locking an angle never touches bin_layout / geometry.
    channel_id = channelIdForLayer(layout, layer_index)
    if payload.which == "open":
        set_servo_channel_angle(channel_id, "open", angle)
        if hasattr(servo, "set_open_angle"):
            servo.set_open_angle(angle)
    else:
        set_servo_channel_angle(channel_id, "closed", angle)
        if hasattr(servo, "set_closed_angle"):
            servo.set_closed_angle(angle)

    state = _servo_calibration_state(servo)
    return {
        "ok": True,
        "layer_index": layer_index,
        "channel_id": channel_id,
        "which": payload.which,
        "angle": angle,
        **state,
        "feedback": _live_servo_feedback_for_layer(layer_index, servo),
        "message": (
            f"Layer {layer_index + 1} {payload.which} angle locked at {angle}°."
        ),
    }


@router.post("/api/hardware-config/servo/layers/{layer_index}/clear")
def clear_layer_servo_angle(layer_index: int, payload: ServoLayerClearPayload) -> Dict[str, Any]:
    _ensure_not_homing("clear a servo angle")
    if payload.which not in {"open", "closed", "both"}:
        raise HTTPException(status_code=400, detail="which must be 'open', 'closed' or 'both'.")
    servo = _live_servo_for_layer(layer_index)

    layout = getBinLayout()
    if layer_index < 0 or layer_index >= len(layout.layers):
        raise HTTPException(status_code=404, detail=f"Unknown storage layer {layer_index + 1}.")

    channel_id = channelIdForLayer(layout, layer_index)
    if payload.which in {"open", "both"}:
        set_servo_channel_angle(channel_id, "open", None)
        if hasattr(servo, "set_open_angle"):
            servo.set_open_angle(None)
    if payload.which in {"closed", "both"}:
        set_servo_channel_angle(channel_id, "closed", None)
        if hasattr(servo, "set_closed_angle"):
            servo.set_closed_angle(None)

    state = _servo_calibration_state(servo)
    return {
        "ok": True,
        "layer_index": layer_index,
        "which": payload.which,
        **state,
        "feedback": _live_servo_feedback_for_layer(layer_index, servo),
        "message": (
            f"Layer {layer_index + 1} calibration cleared."
            if payload.which == "both"
            else f"Layer {layer_index + 1} {payload.which} angle cleared."
        ),
    }


@router.get("/api/hardware/servo-status")
def get_servo_status() -> Dict[str, Any]:
    """Per-layer servo online state for debugging the red
    "Servo bus offline" banner. Returns one entry per layer with its
    live ``available`` flag plus the aggregate ``bus_online`` status —
    useful when the operator has reconnected the Waveshare USB and
    wants to verify the bus is back before pressing Resume.
    """
    active_irl = shared_state.getActiveIRL()
    layers: list[dict[str, Any]] = []
    any_online = False
    if active_irl is not None:
        servos = list(getattr(active_irl, "servos", []) or [])
        for index, servo in enumerate(servos):
            available = bool(getattr(servo, "available", True))
            if available:
                any_online = True
            layers.append(
                {
                    "layer_index": index,
                    "available": available,
                    "channel": getattr(servo, "channel", None),
                    "name": getattr(servo, "_name", f"layer_{index}_servo"),
                }
            )
    stats = None
    try:
        if shared_state.gc_ref is not None:
            stats = getattr(
                shared_state.gc_ref.runtime_stats, "servo_bus_offline_since_ts", None
            )
    except Exception:
        stats = None
    return {
        "ok": True,
        "bus_online": any_online,
        "layers": layers,
        "offline_since_ts": stats,
    }


@router.get("/api/hardware-config/waveshare/status")
def get_waveshare_inventory_status(port: str | None = None) -> Dict[str, Any]:
    return _waveshare_inventory_status(port=port)


@router.post("/api/hardware-config/waveshare/rescan")
def rescan_waveshare_inventory(port: str | None = None) -> Dict[str, Any]:
    _ensure_not_homing("scan Waveshare servos")
    return _waveshare_inventory_status(port=port, refresh=True)


@router.post("/api/hardware-config/waveshare/servos/{servo_id}/set-id")
def set_waveshare_servo_id(servo_id: int, payload: ServoSetIdPayload) -> Dict[str, Any]:
    """Change a servo's ID on the bus."""
    _ensure_not_homing("change a Waveshare servo ID")
    new_id = payload.new_id
    if new_id < 1 or new_id > 253:
        raise HTTPException(status_code=400, detail="New ID must be between 1 and 253.")
    if new_id == servo_id:
        raise HTTPException(status_code=400, detail="New ID is the same as the current ID.")

    service = _get_waveshare_service()

    try:
        if not service.ping(servo_id):
            raise HTTPException(status_code=404, detail=f"No servo with ID {servo_id} found on the bus.")
        if service.ping(new_id):
            raise HTTPException(status_code=409, detail=f"A servo with ID {new_id} already exists on the bus.")

        if not service.set_id(servo_id, new_id):
            raise HTTPException(status_code=500, detail="set_id command failed.")

        time.sleep(0.05)
        if not service.ping(new_id):
            raise HTTPException(
                status_code=500,
                detail=f"ID change sent but servo does not respond at new ID {new_id}. Power-cycle may be needed.",
            )

        info = service.read_servo_info(new_id)
        try:
            get_waveshare_inventory_manager().refresh(
                port=getattr(service, "port", None),
                allow_active_runtime_scan=True,
            )
        except Exception:
            pass
        return {
            "ok": True,
            "old_id": servo_id,
            "new_id": new_id,
            "servo": info,
            "message": f"Servo ID changed from {servo_id} to {new_id}.",
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to change servo ID: {e}")


@router.post("/api/hardware-config/waveshare/servos/{servo_id}/calibrate")
def calibrate_waveshare_servo(servo_id: int) -> Dict[str, Any]:
    """Auto-calibrate the open/close range of a single servo on the bus."""
    _ensure_not_homing("calibrate a Waveshare servo")
    if servo_id < 1 or servo_id > 253:
        raise HTTPException(status_code=400, detail="Servo ID must be between 1 and 253.")

    service = _get_waveshare_service()

    try:
        if not service.ping(servo_id):
            raise HTTPException(status_code=404, detail=f"No servo with ID {servo_id} found on the bus.")

        try:
            safe_min, safe_max = service.calibrate_servo(servo_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Calibration failed: {exc}")

        info = service.read_servo_info(servo_id)
        try:
            get_waveshare_inventory_manager().refresh(
                port=getattr(service, "port", None),
                allow_active_runtime_scan=True,
            )
        except Exception:
            pass
        return {
            "ok": True,
            "servo_id": servo_id,
            "limits": {"min": safe_min, "max": safe_max},
            "servo": info,
            "message": f"Servo {servo_id} calibrated. Range {safe_min}–{safe_max} saved to EEPROM.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to calibrate servo: {exc}")


@router.post("/api/hardware-config/waveshare/servos/{servo_id}/move")
def move_waveshare_servo(servo_id: int, payload: ServoMovePayload) -> Dict[str, Any]:
    """Move a single servo to its open/close/center position based on EEPROM limits."""
    _ensure_not_homing("move a Waveshare servo")
    if servo_id < 1 or servo_id > 253:
        raise HTTPException(status_code=400, detail="Servo ID must be between 1 and 253.")

    target = (payload.position or "").lower().strip()
    if target not in {"open", "close", "center"}:
        raise HTTPException(
            status_code=400,
            detail="position must be one of: open, close, center.",
        )

    service = _get_waveshare_service()

    try:
        if not service.ping(servo_id):
            raise HTTPException(status_code=404, detail=f"No servo with ID {servo_id} found on the bus.")

        limits = service.read_angle_limits(servo_id)
        if limits is None:
            raise HTTPException(status_code=500, detail="Could not read servo angle limits.")
        min_lim, max_lim = limits
        if max_lim - min_lim < 20:
            raise HTTPException(
                status_code=409,
                detail="Servo has no calibrated range. Run auto-calibration first.",
            )

        if target == "open":
            position = min_lim
        elif target == "close":
            position = max_lim
        else:
            position = (min_lim + max_lim) // 2

        service.set_torque(servo_id, True)
        time.sleep(0.01)
        if not service.move_to(servo_id, position, 400):
            raise HTTPException(status_code=500, detail="move_to command failed.")
        try:
            get_waveshare_inventory_manager().trigger_refresh()
        except Exception:
            pass

        return {
            "ok": True,
            "servo_id": servo_id,
            "position": target,
            "raw_position": position,
            "limits": {"min": min_lim, "max": max_lim},
            "message": f"Servo {servo_id} moved to {target} ({position}).",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to move servo: {exc}")


@router.post("/api/hardware-config/waveshare/servos/{servo_id}/nudge")
def nudge_waveshare_servo(servo_id: int, payload: ServoNudgePayload) -> Dict[str, Any]:
    _ensure_not_homing("nudge a Waveshare servo")
    if servo_id < 1 or servo_id > 253:
        raise HTTPException(status_code=400, detail="Servo ID must be between 1 and 253.")

    service = _get_waveshare_service()

    try:
        if not service.ping(servo_id):
            raise HTTPException(status_code=404, detail=f"No servo with ID {servo_id} found on the bus.")

        limits = service.read_angle_limits(servo_id)
        if limits is None:
            raise HTTPException(status_code=500, detail="Could not read servo angle limits.")
        min_lim, max_lim = limits
        range_size = max_lim - min_lim
        if range_size < 20:
            raise HTTPException(status_code=409, detail="Servo has no calibrated range. Run auto-calibration first.")

        current_pos = service.read_position(servo_id)
        if current_pos is None:
            raise HTTPException(status_code=500, detail="Could not read current servo position.")

        raw_delta = int(payload.degrees * range_size / 180)
        new_pos = max(0, min(1023, current_pos + raw_delta))

        service.set_torque(servo_id, True)
        time.sleep(0.01)
        if not service.move_to(servo_id, new_pos, 200):
            raise HTTPException(status_code=500, detail="move_to command failed.")
        try:
            get_waveshare_inventory_manager().trigger_refresh()
        except Exception:
            pass

        return {
            "ok": True,
            "servo_id": servo_id,
            "degrees": payload.degrees,
            "raw_position": new_pos,
            "previous_position": current_pos,
            "limits": {"min": min_lim, "max": max_lim},
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to nudge servo: {exc}")
