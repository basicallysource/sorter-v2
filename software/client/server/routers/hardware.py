"""Router for hardware configuration endpoints (servo, chute, carousel, storage layers)."""

from __future__ import annotations

import json
import os
import time
import threading
import tomllib
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from irl.bin_layout import getBinLayout
from irl.parse_user_toml import (
    DEFAULT_CHUTE_FIRST_BIN_CENTER,
    DEFAULT_CHUTE_PILLAR_WIDTH_DEG,
    DEFAULT_SERVO_CLOSED_ANGLE,
    DEFAULT_SERVO_OPEN_ANGLE,
)
from server import shared_state
from server.routers.steppers import _stepper_mapping, _halt_stepper

router = APIRouter()

# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ServoChannelConfigPayload(BaseModel):
    id: int
    invert: bool = False


class ServoHardwareSettingsPayload(BaseModel):
    backend: str = "pca9685"
    open_angle: int = DEFAULT_SERVO_OPEN_ANGLE
    closed_angle: int = DEFAULT_SERVO_CLOSED_ANGLE
    port: Optional[str] = None
    channels: List[ServoChannelConfigPayload] = []


class ChuteHardwareSettingsPayload(BaseModel):
    first_bin_center: float = DEFAULT_CHUTE_FIRST_BIN_CENTER
    pillar_width_deg: float = DEFAULT_CHUTE_PILLAR_WIDTH_DEG
    endstop_active_high: bool = True


class CarouselHardwareSettingsPayload(BaseModel):
    endstop_active_high: bool = False
    stepper_direction_inverted: bool = False


class ServoLayerPreviewPayload(BaseModel):
    invert: bool = False
    is_open: bool = False


class StorageLayerPayload(BaseModel):
    bin_count: int
    enabled: bool = True


class StorageLayerSettingsPayload(BaseModel):
    layer_bin_counts: List[int] = []
    layers: List[StorageLayerPayload] = []


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_STORAGE_LAYER_BIN_COUNTS = [12, 18, 30]
DEFAULT_STORAGE_LAYER_SECTION_COUNT = 6
CAROUSEL_HOME_PIN_CHANNEL = 2
DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH = False
CAROUSEL_HOME_SPEED_MICROSTEPS_PER_SEC = 400
CAROUSEL_HOME_SPEED_SLOW_MICROSTEPS_PER_SEC = 100
CAROUSEL_BACKOFF_STEPS = 200
CAROUSEL_HOME_PASSES = 3
CAROUSEL_HOME_TIMEOUT_MS = 30000
CAROUSEL_CALIBRATE_TIMEOUT_MS = 60000

from server.config_helpers import (
    machine_params_path as _camera_params_path,
    bin_layout_path as _bin_layout_path,
    read_machine_params_config as _read_machine_params_config,
    read_bin_layout_config as _read_bin_layout_config,
    toml_value as _toml_value,
    write_machine_params_config as _write_machine_params_config,
    write_bin_layout_config as _write_bin_layout_config,
)


# ---------------------------------------------------------------------------
# Hardware query helpers
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Hardware query helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _distribution_layer_count() -> int:
    if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        layout = getattr(shared_state.controller_ref.irl, "distribution_layout", None)
        if layout is not None and hasattr(layout, "layers"):
            return len(layout.layers)
    return len(getBinLayout().layers)


def _pca_available_servo_channels() -> List[int]:
    if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        interfaces = getattr(shared_state.controller_ref.irl, "interfaces", {})
        channels: set[int] = set()
        if isinstance(interfaces, dict):
            for interface in interfaces.values():
                for servo in getattr(interface, "servos", []):
                    channel = getattr(servo, "channel", None)
                    if isinstance(channel, int) and not isinstance(channel, bool):
                        channels.add(channel)
        if channels:
            return sorted(channels)
    return list(range(_distribution_layer_count()))


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

    live_servos = []
    if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        live_servos = list(getattr(shared_state.controller_ref.irl, "servos", []))
        for servo_obj in live_servos:
            channel = getattr(servo_obj, "channel", None)
            if isinstance(channel, int) and not isinstance(channel, bool) and channel > 0:
                found_ids.add(channel)

    scan_bus = None
    if live_servos:
        for servo_obj in live_servos:
            candidate_bus = getattr(servo_obj, "_bus", None)
            if candidate_bus is not None and hasattr(candidate_bus, "scan"):
                scan_bus = candidate_bus
                break

    if scan_bus is not None:
        try:
            found_ids.update(int(servo_id) for servo_id in scan_bus.scan(1, 32))
        except Exception:
            pass
        return sorted(found_ids)

    port = servo.get("port")
    if isinstance(port, str) and port.strip():
        try:
            from hardware.waveshare_servo import ScServoBus

            bus = ScServoBus(port.strip(), timeout=0.01)
            try:
                found_ids.update(int(servo_id) for servo_id in bus.scan(1, 32))
            finally:
                bus.close()
        except Exception:
            pass

    return sorted(found_ids)


def _live_servo_for_layer(layer_index: int) -> Any:
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Servo controller not initialized.")

    servos = list(getattr(shared_state.controller_ref.irl, "servos", []))
    if layer_index < 0 or layer_index >= len(servos):
        raise HTTPException(status_code=404, detail=f"Unknown storage layer {layer_index + 1}.")
    return servos[layer_index]


def _live_servo_feedback_for_layer(layer_index: int, servo: Any | None = None) -> Dict[str, Any]:
    servo = servo if servo is not None else _live_servo_for_layer(layer_index)
    channel = getattr(servo, "channel", None)
    base: Dict[str, Any] = {
        "layer_index": layer_index,
        "channel": channel,
        "available": False,
    }

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
        return {
            **base,
            "available": True,
            "position": position,
            "is_open": bool(servo.isOpen()) if hasattr(servo, "isOpen") else None,
        }
    except Exception as e:
        return {**base, "error": str(e)}


def _servo_hardware_issues() -> List[Dict[str, Any]]:
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        return []
    servo_controller = getattr(shared_state.controller_ref.irl, "servo_controller", None)
    issues = getattr(servo_controller, "issues", None)
    if not isinstance(issues, list):
        return []
    return [issue for issue in issues if isinstance(issue, dict)]


def _hardware_issues() -> List[Dict[str, Any]]:
    return _servo_hardware_issues()


def _servo_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    servo = config.get("servo", {})
    if not isinstance(servo, dict):
        servo = {}

    backend = servo.get("backend", "pca9685")
    if backend not in {"pca9685", "waveshare"}:
        backend = "pca9685"

    open_angle = servo.get("open_angle", DEFAULT_SERVO_OPEN_ANGLE)
    if not isinstance(open_angle, int) or isinstance(open_angle, bool):
        open_angle = DEFAULT_SERVO_OPEN_ANGLE

    closed_angle = servo.get("closed_angle", DEFAULT_SERVO_CLOSED_ANGLE)
    if not isinstance(closed_angle, int) or isinstance(closed_angle, bool):
        closed_angle = DEFAULT_SERVO_CLOSED_ANGLE

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
            if not isinstance(channel_id, int) or isinstance(channel_id, bool):
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
                "id": int(existing["id"]) if existing is not None else default_id,
                "invert": bool(existing["invert"]) if existing is not None else False,
            }
        )

    return {
        "backend": backend,
        "open_angle": max(0, min(180, open_angle)),
        "closed_angle": max(0, min(180, closed_angle)),
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


def _chute_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    chute = config.get("chute", {})
    if not isinstance(chute, dict):
        chute = {}

    first_bin_center = _coerce_float(
        chute.get("first_bin_center"),
        DEFAULT_CHUTE_FIRST_BIN_CENTER,
    )
    pillar_width_deg = _coerce_float(
        chute.get("pillar_width_deg"),
        DEFAULT_CHUTE_PILLAR_WIDTH_DEG,
    )
    endstop_active_high = chute.get("endstop_active_high", True)
    if not isinstance(endstop_active_high, bool):
        endstop_active_high = True

    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        pillar_width_deg = DEFAULT_CHUTE_PILLAR_WIDTH_DEG

    return {
        "first_bin_center": first_bin_center,
        "pillar_width_deg": pillar_width_deg,
        "endstop_active_high": endstop_active_high,
    }


def _carousel_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    carousel = config.get("carousel", {})
    if not isinstance(carousel, dict):
        carousel = {}

    endstop_active_high = carousel.get(
        "endstop_active_high",
        DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH,
    )
    if not isinstance(endstop_active_high, bool):
        endstop_active_high = DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH

    stepper_direction_inverts = config.get("stepper_direction_inverts", {})
    if not isinstance(stepper_direction_inverts, dict):
        stepper_direction_inverts = {}
    stepper_direction_inverted = stepper_direction_inverts.get("carousel", False)
    if not isinstance(stepper_direction_inverted, bool):
        stepper_direction_inverted = False

    return {
        "endstop_active_high": endstop_active_high,
        "stepper_direction_inverted": stepper_direction_inverted,
        "home_pin_channel": CAROUSEL_HOME_PIN_CHANNEL,
    }


def _storage_layer_settings_from_layout(layout: Any) -> Dict[str, Any]:
    layers: List[Dict[str, Any]] = []
    for index, layer in enumerate(getattr(layout, "layers", []), start=1):
        sections = getattr(layer, "sections", [])
        bin_count = sum(len(section) for section in sections)
        section_count = len(sections) or DEFAULT_STORAGE_LAYER_SECTION_COUNT
        enabled = bool(getattr(layer, "enabled", True))

        bin_size = "medium"
        for section in sections:
            for value in section:
                if isinstance(value, str) and value:
                    bin_size = value
                    break
            if bin_size != "medium":
                break

        layers.append(
            {
                "index": index,
                "bin_count": bin_count,
                "section_count": section_count,
                "bin_size": bin_size,
                "enabled": enabled,
            }
        )

    return {
        "allowed_bin_counts": ALLOWED_STORAGE_LAYER_BIN_COUNTS,
        "layers": layers,
    }


def _apply_live_storage_layer_enabled(layers: List[Dict[str, Any]]) -> bool:
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        return False

    distribution_layout = getattr(shared_state.controller_ref.irl, "distribution_layout", None)
    runtime_layers = list(getattr(distribution_layout, "layers", [])) if distribution_layout is not None else []
    if len(runtime_layers) != len(layers):
        return False

    # Config order is mirrored into runtime order during mkLayoutFromConfig.
    for runtime_layer, layer in zip(runtime_layers, reversed(layers)):
        setattr(runtime_layer, "enabled", bool(layer.get("enabled", True)))
    return True


def _live_chute_status() -> Dict[str, Any]:
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": None,
            "current_angle": None,
            "stepper_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "digital_inputs": [],
        }

    irl = shared_state.controller_ref.irl
    chute = getattr(irl, "chute", None)
    stepper = getattr(irl, "chute_stepper", None)
    interfaces = getattr(irl, "interfaces", {})
    distribution_board = interfaces.get("DISTRIBUTION MB") if isinstance(interfaces, dict) else None
    if chute is None or stepper is None:
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": None,
            "current_angle": None,
            "stepper_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "digital_inputs": [],
        }

    status: Dict[str, Any] = {
        "live_available": True,
        "endstop_triggered": None,
        "raw_endstop_high": None,
        "endstop_active_high": getattr(chute, "endstop_active_high", True),
        "current_angle": None,
        "stepper_position_degrees": None,
        "stepper_microsteps": None,
        "stepper_stopped": None,
        "digital_inputs": [],
    }

    try:
        status["raw_endstop_high"] = bool(chute.home_pin.value)
        if hasattr(chute, "endstop_triggered"):
            status["endstop_triggered"] = bool(chute.endstop_triggered)
        elif status["raw_endstop_high"] is not None:
            active_high = bool(status["endstop_active_high"])
            status["endstop_triggered"] = (
                bool(status["raw_endstop_high"])
                if active_high
                else not bool(status["raw_endstop_high"])
            )
        status["home_pin_channel"] = getattr(chute.home_pin, "channel", None)
    except Exception as e:
        status["endstop_error"] = str(e)

    try:
        status["current_angle"] = float(chute.current_angle)
    except Exception as e:
        status["current_angle_error"] = str(e)

    try:
        status["stepper_position_degrees"] = float(stepper.position_degrees)
        status["stepper_microsteps"] = int(stepper.position)
    except Exception as e:
        status["stepper_position_error"] = str(e)

    try:
        status["stepper_stopped"] = bool(stepper.stopped)
    except Exception as e:
        status["stepper_stopped_error"] = str(e)

    if distribution_board is not None:
        try:
            status["digital_inputs"] = [
                {
                    "channel": index,
                    "raw_high": bool(pin.value),
                }
                for index, pin in enumerate(getattr(distribution_board, "digital_inputs", []))
            ]
        except Exception as e:
            status["digital_inputs_error"] = str(e)

    return status


def _live_carousel_status() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    carousel_settings = _carousel_settings_from_config(config)
    endstop_active_high = bool(
        carousel_settings.get("endstop_active_high", DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH)
    )
    stepper_direction_inverted = bool(
        carousel_settings.get("stepper_direction_inverted", False)
    )

    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": endstop_active_high,
            "stepper_direction_inverted": stepper_direction_inverted,
            "current_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "bound_stepper_name": None,
            "bound_stepper_channel": None,
            "digital_inputs": [],
            "home_pin_channel": CAROUSEL_HOME_PIN_CHANNEL,
        }

    irl = shared_state.controller_ref.irl
    stepper = getattr(irl, "carousel_stepper", None)
    interfaces = getattr(irl, "interfaces", {})
    feeder_board = interfaces.get("FEEDER MB") if isinstance(interfaces, dict) else None

    if stepper is None or feeder_board is None:
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": endstop_active_high,
            "stepper_direction_inverted": stepper_direction_inverted,
            "current_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "bound_stepper_name": getattr(stepper, "hardware_name", None) if stepper is not None else None,
            "bound_stepper_channel": getattr(stepper, "channel", None) if stepper is not None else None,
            "digital_inputs": [],
            "home_pin_channel": CAROUSEL_HOME_PIN_CHANNEL,
        }

    status: Dict[str, Any] = {
        "live_available": True,
        "endstop_triggered": None,
        "raw_endstop_high": None,
        "endstop_active_high": endstop_active_high,
        "stepper_direction_inverted": stepper_direction_inverted,
        "current_position_degrees": None,
        "stepper_microsteps": None,
        "stepper_stopped": None,
        "bound_stepper_name": getattr(stepper, "hardware_name", None),
        "bound_stepper_channel": getattr(stepper, "channel", None),
        "digital_inputs": [],
        "home_pin_channel": CAROUSEL_HOME_PIN_CHANNEL,
    }

    digital_inputs = list(getattr(feeder_board, "digital_inputs", []))
    if 0 <= CAROUSEL_HOME_PIN_CHANNEL < len(digital_inputs):
        try:
            raw_high = bool(digital_inputs[CAROUSEL_HOME_PIN_CHANNEL].value)
            status["raw_endstop_high"] = raw_high
            status["endstop_triggered"] = raw_high if endstop_active_high else not raw_high
        except Exception as e:
            status["endstop_error"] = str(e)

    try:
        status["current_position_degrees"] = float(stepper.position_degrees)
        status["stepper_microsteps"] = int(stepper.position)
    except Exception as e:
        status["stepper_position_error"] = str(e)

    try:
        status["stepper_stopped"] = bool(stepper.stopped)
    except Exception as e:
        status["stepper_stopped_error"] = str(e)

    try:
        status["digital_inputs"] = [
            {
                "channel": index,
                "raw_high": bool(pin.value),
            }
            for index, pin in enumerate(digital_inputs)
        ]
    except Exception as e:
        status["digital_inputs_error"] = str(e)

    return status


def _stop_all_steppers() -> None:
    """Stop all known steppers. Raises HTTPException on failure."""
    halted: list[str] = []
    errors: Dict[str, str] = {}

    for name, stepper in _stepper_mapping().items():
        if stepper is None:
            continue
        try:
            _halt_stepper(stepper)
            halted.append(name)
        except Exception as e:
            errors[name] = str(e)

    if errors:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "One or more steppers failed to stop.",
                "errors": errors,
                "stopped": halted,
            },
        )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/api/hardware-config")
def get_hardware_config() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    _, layout = _read_bin_layout_config()
    return {
        "storage_layers": _storage_layer_settings_from_layout(layout),
        "servo": _servo_settings_from_config(config),
        "chute": _chute_settings_from_config(config),
        "carousel": _carousel_settings_from_config(config),
        "issues": _hardware_issues(),
    }


@router.get("/api/hardware-config/servo/live")
def get_live_servo_feedback() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    servo_settings = _servo_settings_from_config(config)
    layer_count = int(servo_settings.get("layer_count", 0))

    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        return {
            "ok": True,
            "backend": servo_settings["backend"],
            "live_available": False,
            "layers": [],
        }

    servos = list(getattr(shared_state.controller_ref.irl, "servos", []))
    return {
        "ok": True,
        "backend": servo_settings["backend"],
        "live_available": len(servos) > 0,
        "layers": [
            _live_servo_feedback_for_layer(index, servos[index] if index < len(servos) else None)
            for index in range(layer_count)
        ],
    }


@router.post("/api/hardware-config/servo")
def save_servo_hardware_config(
    payload: ServoHardwareSettingsPayload,
) -> Dict[str, Any]:
    backend = payload.backend if payload.backend in {"pca9685", "waveshare"} else "pca9685"
    open_angle = max(0, min(180, int(payload.open_angle)))
    closed_angle = max(0, min(180, int(payload.closed_angle)))
    port = payload.port.strip() if isinstance(payload.port, str) and payload.port.strip() else None
    layer_count = _distribution_layer_count()
    available_pca_channels = _pca_available_servo_channels()

    if len(payload.channels) != layer_count:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {layer_count} layer servo assignments, got {len(payload.channels)}.",
        )

    channels: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, channel in enumerate(payload.channels):
        channel_id = int(channel.id)
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

    params_path, config = _read_machine_params_config()
    previous = _servo_settings_from_config(config)

    servo_table: Dict[str, Any] = {"backend": backend, "channels": channels}
    if backend == "pca9685":
        servo_table["open_angle"] = open_angle
        servo_table["closed_angle"] = closed_angle
    if backend == "waveshare":
        if port is not None:
            servo_table["port"] = port

    config["servo"] = servo_table

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    previous_ids = [int(channel["id"]) for channel in previous["channels"]]
    previous_inverts = [bool(channel["invert"]) for channel in previous["channels"]]
    channel_ids = [int(channel["id"]) for channel in channels]
    channel_inverts = [bool(channel["invert"]) for channel in channels]

    restart_required = (
        backend != previous["backend"]
        or channel_ids != previous_ids
        or (backend == "waveshare" and port != previous["port"])
    )

    applied_live = False
    if not restart_required and shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        try:
            live_servos = list(getattr(shared_state.controller_ref.irl, "servos", []))
            if len(live_servos) == len(channels):
                for index, servo in enumerate(live_servos):
                    invert = channel_inverts[index]
                    if backend == "waveshare":
                        if hasattr(servo, "set_invert"):
                            servo.set_invert(invert)
                    elif hasattr(servo, "set_preset_angles"):
                        if invert:
                            servo.set_preset_angles(closed_angle, open_angle)
                        else:
                            servo.set_preset_angles(open_angle, closed_angle)
                applied_live = True
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "settings": _servo_settings_from_config(config),
        "applied_live": applied_live,
        "restart_required": restart_required,
        "message": (
            "Servo settings saved and applied live."
            if applied_live
            else "Servo settings saved. Restart backend to apply backend or bus changes."
        ),
    }


@router.post("/api/hardware-config/servo/layers/{layer_index}/toggle")
def toggle_layer_servo(layer_index: int) -> Dict[str, Any]:
    servo = _live_servo_for_layer(layer_index)
    if not hasattr(servo, "toggle"):
        raise HTTPException(status_code=500, detail="Selected servo does not support test toggling.")

    try:
        servo.toggle()
        feedback = _live_servo_feedback_for_layer(layer_index, servo)
        is_open = bool(feedback.get("is_open")) if feedback.get("available") else False
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle layer {layer_index + 1} servo: {e}")

    # Persist servo states so they survive restarts
    try:
        from irl.config import save_servo_states
        if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
            servos = getattr(shared_state.controller_ref.irl, "servos", [])
            save_servo_states(servos, shared_state.controller_ref.gc)
    except Exception:
        pass

    return {
        "ok": True,
        "layer_index": layer_index,
        "is_open": is_open,
        "feedback": feedback,
        "message": (
            f"Layer {layer_index + 1} servo opened."
            if is_open
            else f"Layer {layer_index + 1} servo closed."
        ),
    }


@router.post("/api/hardware-config/servo/layers/{layer_index}/preview")
def preview_layer_servo(
    layer_index: int,
    payload: ServoLayerPreviewPayload,
) -> Dict[str, Any]:
    servo = _live_servo_for_layer(layer_index)
    _, config = _read_machine_params_config()
    servo_settings = _servo_settings_from_config(config)
    backend = servo_settings["backend"]
    open_angle = int(servo_settings["open_angle"])
    closed_angle = int(servo_settings["closed_angle"])
    desired_open = bool(payload.is_open)
    invert = bool(payload.invert)

    try:
        if backend == "waveshare":
            if hasattr(servo, "set_invert"):
                servo.set_invert(invert)
        elif hasattr(servo, "set_preset_angles"):
            if invert:
                servo.set_preset_angles(closed_angle, open_angle)
            else:
                servo.set_preset_angles(open_angle, closed_angle)

        if desired_open:
            if hasattr(servo, "open"):
                servo.open()
        else:
            if hasattr(servo, "close"):
                servo.close()
        feedback = _live_servo_feedback_for_layer(layer_index, servo)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview invert on layer {layer_index + 1}: {e}",
        )

    return {
        "ok": True,
        "layer_index": layer_index,
        "is_open": desired_open,
        "invert": invert,
        "feedback": feedback,
        "message": (
            f"Layer {layer_index + 1} preview updated to {'open' if desired_open else 'closed'} "
            f"with invert {'on' if invert else 'off'}."
        ),
    }


@router.post("/api/hardware-config/servo/layers/{layer_index}/calibrate")
def calibrate_layer_servo(layer_index: int) -> Dict[str, Any]:
    servo = _live_servo_for_layer(layer_index)
    if not hasattr(servo, "recalibrate"):
        raise HTTPException(
            status_code=400,
            detail="Calibration is only supported for Waveshare storage-layer servos.",
        )

    try:
        min_limit, max_limit = servo.recalibrate()
        feedback = _live_servo_feedback_for_layer(layer_index, servo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calibrate layer {layer_index + 1} servo: {e}")

    return {
        "ok": True,
        "layer_index": layer_index,
        "limits": {"min": min_limit, "max": max_limit},
        "feedback": feedback,
        "message": f"Layer {layer_index + 1} servo calibrated.",
    }


@router.get("/api/hardware-config/chute")
def get_chute_hardware_config() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    return _chute_settings_from_config(config)


@router.post("/api/hardware-config/chute")
def save_chute_hardware_config(
    payload: ChuteHardwareSettingsPayload,
) -> Dict[str, Any]:
    first_bin_center = float(payload.first_bin_center)
    pillar_width_deg = float(payload.pillar_width_deg)
    endstop_active_high = bool(payload.endstop_active_high)
    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        raise HTTPException(
            status_code=400,
            detail="pillar_width_deg must be between 0 and less than 60 degrees",
        )

    params_path, config = _read_machine_params_config()
    config["chute"] = {
        "first_bin_center": first_bin_center,
        "pillar_width_deg": pillar_width_deg,
        "endstop_active_high": endstop_active_high,
    }

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live = False
    if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        chute = getattr(shared_state.controller_ref.irl, "chute", None)
        if chute is not None and hasattr(chute, "setCalibration"):
            try:
                chute.setCalibration(first_bin_center, pillar_width_deg, endstop_active_high)
                applied_live = True
            except Exception:
                applied_live = False

    return {
        "ok": True,
        "settings": _chute_settings_from_config(config),
        "applied_live": applied_live,
        "message": (
            "Chute settings saved and applied live."
            if applied_live
            else "Chute settings saved."
        ),
    }


@router.get("/api/hardware-config/chute/live")
def get_live_chute_status() -> Dict[str, Any]:
    return _live_chute_status()


@router.post("/api/hardware-config/chute/calibrate/find-endstop")
def calibrate_chute_find_endstop() -> Dict[str, Any]:
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Chute controller not initialized.")

    chute = getattr(shared_state.controller_ref.irl, "chute", None)
    if chute is None or not hasattr(chute, "home"):
        raise HTTPException(status_code=503, detail="Chute subsystem unavailable.")

    try:
        homed = bool(chute.home())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find chute endstop: {e}")
    if not homed:
        raise HTTPException(
            status_code=409,
            detail="Chute homing stopped before the endstop triggered.",
        )

    return {
        "ok": True,
        "status": _live_chute_status(),
        "message": "Step 1 complete. Chute moved slowly until the endstop was found and re-homed.",
    }


@router.post("/api/hardware-config/chute/calibrate/cancel")
def cancel_chute_find_endstop() -> Dict[str, Any]:
    try:
        _stop_all_steppers()
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return {
        "ok": True,
        "status": _live_chute_status(),
        "message": "Chute homing canceled. All steppers were stopped for safety.",
    }


@router.get("/api/hardware-config/carousel/live")
def get_live_carousel_status() -> Dict[str, Any]:
    return _live_carousel_status()


@router.get("/api/hardware-config/carousel")
def get_carousel_hardware_config() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    return _carousel_settings_from_config(config)


@router.post("/api/hardware-config/carousel")
def save_carousel_hardware_config(
    payload: CarouselHardwareSettingsPayload,
) -> Dict[str, Any]:
    endstop_active_high = bool(payload.endstop_active_high)
    stepper_direction_inverted = bool(payload.stepper_direction_inverted)

    params_path, config = _read_machine_params_config()
    carousel_config = config.get("carousel", {})
    if not isinstance(carousel_config, dict):
        carousel_config = {}
    carousel_config = {**carousel_config, "endstop_active_high": endstop_active_high}
    config["carousel"] = carousel_config

    stepper_direction_inverts = config.get("stepper_direction_inverts", {})
    if not isinstance(stepper_direction_inverts, dict):
        stepper_direction_inverts = {}
    stepper_direction_inverts = {
        **stepper_direction_inverts,
        "carousel": stepper_direction_inverted,
    }
    config["stepper_direction_inverts"] = stepper_direction_inverts

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    if shared_state.controller_ref is not None and hasattr(shared_state.controller_ref, "irl"):
        stepper = getattr(shared_state.controller_ref.irl, "carousel_stepper", None)
        if stepper is not None and hasattr(stepper, "set_direction_inverted"):
            try:
                stepper.set_direction_inverted(stepper_direction_inverted)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Settings were saved, but live direction inversion could not be applied: {e}",
                )

    return {
        "ok": True,
        "settings": _carousel_settings_from_config(config),
        "status": _live_carousel_status(),
        "message": "Carousel settings saved.",
    }


@router.post("/api/hardware-config/carousel/home")
def home_carousel_to_endstop() -> Dict[str, Any]:
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Carousel controller not initialized.")

    irl = shared_state.controller_ref.irl
    interfaces = getattr(irl, "interfaces", {})
    feeder_board = interfaces.get("FEEDER MB") if isinstance(interfaces, dict) else None
    if feeder_board is None:
        raise HTTPException(status_code=503, detail="Feeder board not initialized.")

    digital_inputs = list(getattr(feeder_board, "digital_inputs", []))
    if CAROUSEL_HOME_PIN_CHANNEL < 0 or CAROUSEL_HOME_PIN_CHANNEL >= len(digital_inputs):
        raise HTTPException(
            status_code=503,
            detail=f"Carousel home input channel {CAROUSEL_HOME_PIN_CHANNEL} is unavailable.",
        )

    _, config = _read_machine_params_config()
    endstop_active_high = bool(
        _carousel_settings_from_config(config).get("endstop_active_high", DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH)
    )

    stepper = getattr(irl, "carousel_stepper", None)
    if stepper is None:
        raise HTTPException(status_code=503, detail="Carousel stepper unavailable.")

    home_pin = digital_inputs[CAROUSEL_HOME_PIN_CHANNEL]

    def _read_endstop() -> bool:
        raw = bool(home_pin.value)
        return raw if endstop_active_high else not raw

    def _home_and_wait(speed: int, timeout_ms: int) -> None:
        """Issue firmware home command, wait for stop, verify endstop."""
        stepper.home(speed, home_pin, home_pin_active_high=endstop_active_high)
        start = time.monotonic()
        while not stepper.stopped:
            if (time.monotonic() - start) * 1000 > timeout_ms:
                stepper.move_at_speed(0)
                raise TimeoutError("Carousel homing timed out.")
            time.sleep(0.01)
        if not _read_endstop():
            raise HTTPException(
                status_code=409,
                detail="Carousel homing stopped before the endstop triggered.",
            )

    try:
        stepper.enabled = True

        # Pass 1: fast approach
        _home_and_wait(CAROUSEL_HOME_SPEED_MICROSTEPS_PER_SEC, CAROUSEL_HOME_TIMEOUT_MS)

        # Passes 2..N: back off then slow approach for precision
        for _ in range(CAROUSEL_HOME_PASSES - 1):
            stepper.move_steps_blocking(-CAROUSEL_BACKOFF_STEPS, timeout_ms=5000)
            _home_and_wait(CAROUSEL_HOME_SPEED_SLOW_MICROSTEPS_PER_SEC, CAROUSEL_HOME_TIMEOUT_MS)

        stepper.position_degrees = 0.0
        # Keep stepper enabled to hold position
    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to home carousel to endstop: {e}")

    return {
        "ok": True,
        "status": _live_carousel_status(),
        "message": f"Carousel homed ({CAROUSEL_HOME_PASSES}-pass) and zeroed.",
    }


@router.post("/api/hardware-config/carousel/calibrate")
def calibrate_carousel() -> Dict[str, Any]:
    """Calibrate carousel by measuring steps for one full revolution."""
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Carousel controller not initialized.")

    irl = shared_state.controller_ref.irl
    interfaces = getattr(irl, "interfaces", {})
    feeder_board = interfaces.get("FEEDER MB") if isinstance(interfaces, dict) else None
    if feeder_board is None:
        raise HTTPException(status_code=503, detail="Feeder board not initialized.")

    digital_inputs = list(getattr(feeder_board, "digital_inputs", []))
    if CAROUSEL_HOME_PIN_CHANNEL < 0 or CAROUSEL_HOME_PIN_CHANNEL >= len(digital_inputs):
        raise HTTPException(
            status_code=503,
            detail=f"Carousel home input channel {CAROUSEL_HOME_PIN_CHANNEL} is unavailable.",
        )

    _, config = _read_machine_params_config()
    endstop_active_high = bool(
        _carousel_settings_from_config(config).get("endstop_active_high", DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH)
    )

    stepper = getattr(irl, "carousel_stepper", None)
    if stepper is None:
        raise HTTPException(status_code=503, detail="Carousel stepper unavailable.")

    home_pin_obj = digital_inputs[CAROUSEL_HOME_PIN_CHANNEL]

    def _read_endstop() -> bool:
        raw = bool(home_pin_obj.value)
        return raw if endstop_active_high else not raw

    if not _read_endstop():
        raise HTTPException(
            status_code=409,
            detail="Carousel must be homed first (endstop not currently triggered).",
        )

    try:
        stepper.enabled = True

        # Back off the endstop
        stepper.move_steps_blocking(-CAROUSEL_BACKOFF_STEPS, timeout_ms=5000)

        # Zero position counter at this point
        stepper.position = 0

        # Move CW until endstop triggers again (full rotation) using firmware home
        stepper.home(
            CAROUSEL_HOME_SPEED_MICROSTEPS_PER_SEC,
            home_pin_obj,
            home_pin_active_high=endstop_active_high,
        )
        start = time.monotonic()
        while not stepper.stopped:
            if (time.monotonic() - start) * 1000 > CAROUSEL_CALIBRATE_TIMEOUT_MS:
                stepper.move_at_speed(0)
                raise TimeoutError("Carousel calibration timed out.")
            time.sleep(0.01)

        if not _read_endstop():
            raise HTTPException(
                status_code=409,
                detail="Calibration failed: endstop did not trigger after full rotation.",
            )

        measured_steps = abs(stepper.position)

        # Save to config
        params_path, config = _read_machine_params_config()
        carousel_config = config.get("carousel", {})
        if not isinstance(carousel_config, dict):
            carousel_config = {}
        carousel_config["steps_per_revolution"] = measured_steps
        config["carousel"] = carousel_config
        _write_machine_params_config(params_path, config)

        # Update stepper in-memory
        stepper.steps_per_revolution = measured_steps

        # Re-zero position at the endstop
        stepper.position_degrees = 0.0

    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calibration failed: {e}")

    return {
        "ok": True,
        "steps_per_revolution": measured_steps,
        "degrees": 360,
        "status": _live_carousel_status(),
        "message": f"Calibrated: {measured_steps} steps/revolution.",
    }


@router.post("/api/hardware-config/carousel/home/cancel")
def cancel_carousel_home_to_endstop() -> Dict[str, Any]:
    try:
        _stop_all_steppers()
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return {
        "ok": True,
        "status": _live_carousel_status(),
        "message": "Carousel homing canceled. All steppers were stopped for safety.",
    }


@router.post("/api/hardware-config/storage-layers")
def save_storage_layer_hardware_config(
    payload: StorageLayerSettingsPayload,
) -> Dict[str, Any]:
    layout_path, layout = _read_bin_layout_config()
    current = _storage_layer_settings_from_layout(layout)
    requested_layers = list(payload.layers)
    if requested_layers:
        layer_updates = [
            {"bin_count": int(layer.bin_count), "enabled": bool(layer.enabled)}
            for layer in requested_layers
        ]
    else:
        layer_updates = [
            {
                "bin_count": int(count),
                "enabled": bool(layer.get("enabled", True)),
            }
            for count, layer in zip(payload.layer_bin_counts, current["layers"])
        ]

    if len(layer_updates) != len(current["layers"]):
        raise HTTPException(
            status_code=400,
            detail=f"Expected {len(current['layers'])} storage layers, got {len(layer_updates)}.",
        )

    updated_layers: List[Dict[str, Any]] = []
    layout_changed = False
    enabled_changed = False
    for layer_update, layer in zip(layer_updates, current["layers"]):
        count = int(layer_update["bin_count"])
        enabled = bool(layer_update["enabled"])
        if count not in ALLOWED_STORAGE_LAYER_BIN_COUNTS:
            raise HTTPException(
                status_code=400,
                detail=f"Each layer bin count must be one of {ALLOWED_STORAGE_LAYER_BIN_COUNTS}.",
            )

        section_count = int(layer["section_count"])
        if section_count <= 0 or count % section_count != 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Layer {layer['index']} cannot be configured to {count} bins "
                    f"with its current {section_count} sections."
                ),
            )

        updated_layers.append(
            {
                "section_count": section_count,
                "bin_size": layer["bin_size"],
                "bins_per_section": count // section_count,
                "enabled": enabled,
            }
        )
        layout_changed = layout_changed or count != int(layer["bin_count"])
        enabled_changed = enabled_changed or enabled != bool(layer.get("enabled", True))

    if not layout_changed and not enabled_changed:
        return {
            "ok": True,
            "settings": current,
            "applied_live": False,
            "restart_required": False,
            "message": "Storage layer layout unchanged.",
        }

    try:
        _write_bin_layout_config(layout_path, updated_layers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write bin layout: {e}")

    _, saved_layout = _read_bin_layout_config()
    saved_settings = _storage_layer_settings_from_layout(saved_layout)
    applied_live = False
    restart_required = layout_changed
    if enabled_changed and not layout_changed:
        applied_live = _apply_live_storage_layer_enabled(saved_settings["layers"])

    return {
        "ok": True,
        "settings": saved_settings,
        "applied_live": applied_live,
        "restart_required": restart_required,
        "message": (
            "Storage layer status saved and applied live."
            if applied_live
            else (
                "Storage layer status saved."
                if enabled_changed and not layout_changed
                else "Storage layer layout saved. Restart backend to apply layer changes."
            )
        ),
    }
