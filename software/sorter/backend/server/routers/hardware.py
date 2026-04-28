"""Router for hardware configuration endpoints (servo, chute, carousel, storage layers)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from local_state import get_bin_categories, set_bin_categories
from irl.bin_layout import (
    getBinLayout,
    saveBinLayout,
    BinLayoutConfig,
    LayerConfig,
    extractCategories,
    applyCategories,
    layoutMatchesCategories,
    mkLayoutFromConfig,
)
from irl.chute import BinAddress
from irl.parse_user_toml import (
    DEFAULT_CAROUSEL_HOME_PIN_CHANNEL,
    DEFAULT_CHUTE_FIRST_BIN_CENTER,
    DEFAULT_CHUTE_HOME_PIN_CHANNEL,
    DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC,
    DEFAULT_CHUTE_PILLAR_WIDTH_DEG,
    DEFAULT_SERVO_CLOSED_ANGLE,
    DEFAULT_SERVO_OPEN_ANGLE,
)
from local_state import clear_current_session_bins, get_current_bin_contents_snapshot
from server import shared_state
from server.routers.steppers import _stepper_mapping, _halt_stepper
from server.services import runtime_stats as runtime_stats_service
from server.waveshare_inventory import get_waveshare_inventory_manager

router = APIRouter()

_PCA9685_CHANNEL_COUNT = 16


def _active_irl() -> Any | None:
    return shared_state.getActiveIRL()


def _ensure_not_homing(action: str) -> None:
    if shared_state.hardware_state == "homing":
        raise HTTPException(status_code=409, detail=f"Cannot {action} while hardware is homing.")


def _active_waveshare_service() -> Any | None:
    active_irl = _active_irl()
    if active_irl is None:
        return None
    servo_controller = getattr(active_irl, "servo_controller", None)
    return getattr(servo_controller, "bus_service", None)


def _configured_waveshare_service(config: Dict[str, Any], *, timeout: float = 0.02) -> Any | None:
    servo = config.get("servo", {})
    port = servo.get("port") if isinstance(servo, dict) else None
    if not isinstance(port, str) or not port.strip():
        return None
    from hardware.waveshare_bus_service import get_waveshare_bus_service

    return get_waveshare_bus_service(port.strip(), timeout=timeout)


def _get_waveshare_service(*, timeout: float = 0.02) -> Any | None:
    service = _active_waveshare_service()
    if service is not None:
        return service

    _, config = _read_machine_params_config()
    return _configured_waveshare_service(config, timeout=timeout)


def _waveshare_inventory_status(*, port: str | None = None, refresh: bool = False) -> Dict[str, Any]:
    manager = get_waveshare_inventory_manager()
    if refresh:
        return manager.refresh(port=port)
    return manager.get_status(port=port)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ServoChannelConfigPayload(BaseModel):
    id: int | None = None
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
    operating_speed_microsteps_per_second: int = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC


class CarouselHardwareSettingsPayload(BaseModel):
    endstop_active_high: bool = False
    stepper_direction_inverted: bool = False


class ServoSetIdPayload(BaseModel):
    new_id: int


class ServoMovePayload(BaseModel):
    position: str  # "open" | "close" | "center"


class ServoNudgePayload(BaseModel):
    degrees: int


class ServoLayerPreviewPayload(BaseModel):
    invert: bool = False
    is_open: bool = False


class MoveToBinPayload(BaseModel):
    layer_index: int
    section_index: int
    bin_index: int


class BinScopePayload(BaseModel):
    scope: str
    layer_index: Optional[int] = None
    section_index: Optional[int] = None
    bin_index: Optional[int] = None


class ClearBinCategoriesPayload(BinScopePayload):
    pass


class ClearBinContentsPayload(BinScopePayload):
    pass


class StorageLayerPayload(BaseModel):
    bin_count: int
    enabled: bool = True
    servo_open_angle: Optional[int] = None
    servo_closed_angle: Optional[int] = None
    max_pieces_per_bin: Optional[int] = None


class StorageLayerSettingsPayload(BaseModel):
    layer_bin_counts: List[int] = []
    layers: List[StorageLayerPayload] = []


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_STORAGE_LAYER_BIN_COUNTS = [12, 18, 30]
DEFAULT_STORAGE_LAYER_SECTION_COUNT = 6
DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH = False
CAROUSEL_CALIBRATE_TIMEOUT_MS = 60000

from server.config_helpers import (
    read_machine_params_config as _read_machine_params_config,
    write_machine_params_config as _write_machine_params_config,
)



# ---------------------------------------------------------------------------
# Hardware query helpers
# ---------------------------------------------------------------------------


def _coerce_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _pin_channel(pin: Any | None) -> int | None:
    channel = getattr(pin, "channel", None)
    if isinstance(channel, int) and not isinstance(channel, bool):
        return channel

    channel = getattr(pin, "_channel", None)
    if isinstance(channel, int) and not isinstance(channel, bool):
        return channel

    return None


def _distribution_layer_count() -> int:
    active_irl = _active_irl()
    if active_irl is not None:
        layout = getattr(active_irl, "distribution_layout", None)
        if layout is not None and hasattr(layout, "layers"):
            return len(layout.layers)
    return len(getBinLayout().layers)


def _pca_available_servo_channels() -> List[int]:
    active_irl = _active_irl()
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

    active_irl = _active_irl()
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
    active_irl = _active_irl()
    if active_irl is None:
        raise HTTPException(status_code=503, detail="Servo controller not initialized.")

    servos = list(getattr(active_irl, "servos", []))
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
        return {
            **base,
            "available": True,
            "position": position,
            "is_open": bool(servo.isOpen()) if hasattr(servo, "isOpen") else None,
        }
    except Exception as e:
        return {**base, "error": str(e)}


def _servo_hardware_issues() -> List[Dict[str, Any]]:
    active_irl = _active_irl()
    if active_irl is None:
        return []
    servo_controller = getattr(active_irl, "servo_controller", None)
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
    operating_speed_microsteps_per_second = chute.get(
        "operating_speed_microsteps_per_second",
        DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC,
    )
    if not isinstance(operating_speed_microsteps_per_second, int) or isinstance(
        operating_speed_microsteps_per_second, bool
    ):
        operating_speed_microsteps_per_second = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC
    if operating_speed_microsteps_per_second <= 0:
        operating_speed_microsteps_per_second = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC

    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        pillar_width_deg = DEFAULT_CHUTE_PILLAR_WIDTH_DEG

    home_pin_channel = _coerce_int(
        chute.get("home_pin_channel"), DEFAULT_CHUTE_HOME_PIN_CHANNEL
    )
    irl = _active_irl()
    live_chute = getattr(irl, "chute", None) if irl is not None else None
    live_home_pin_channel = _pin_channel(getattr(live_chute, "home_pin", None))
    if live_home_pin_channel is not None:
        home_pin_channel = live_home_pin_channel

    return {
        "first_bin_center": first_bin_center,
        "pillar_width_deg": pillar_width_deg,
        "endstop_active_high": endstop_active_high,
        "operating_speed_microsteps_per_second": operating_speed_microsteps_per_second,
        "home_pin_channel": home_pin_channel,
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

    home_pin_channel = _coerce_int(
        carousel.get("home_pin_channel"), DEFAULT_CAROUSEL_HOME_PIN_CHANNEL
    )
    irl = _active_irl()
    carousel_hw = getattr(irl, "carousel_hw", None) if irl is not None else None
    live_home_pin_channel = _pin_channel(getattr(carousel_hw, "home_pin", None))
    if live_home_pin_channel is not None:
        home_pin_channel = live_home_pin_channel

    return {
        "endstop_active_high": endstop_active_high,
        "stepper_direction_inverted": stepper_direction_inverted,
        "home_pin_channel": home_pin_channel,
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

        layer_entry: Dict[str, Any] = {
            "index": index,
            "bin_count": bin_count,
            "section_count": section_count,
            "bin_size": bin_size,
            "enabled": enabled,
        }
        servo_open = getattr(layer, "servo_open_angle", None)
        servo_closed = getattr(layer, "servo_closed_angle", None)
        max_per_bin = getattr(layer, "max_pieces_per_bin", None)
        if isinstance(servo_open, int):
            layer_entry["servo_open_angle"] = servo_open
        if isinstance(servo_closed, int):
            layer_entry["servo_closed_angle"] = servo_closed
        layer_entry["max_pieces_per_bin"] = max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None
        layers.append(layer_entry)

    return {
        "allowed_bin_counts": ALLOWED_STORAGE_LAYER_BIN_COUNTS,
        "layers": layers,
    }


def _apply_live_storage_layer_enabled(layers: List[Dict[str, Any]]) -> bool:
    active_irl = _active_irl()
    if active_irl is None:
        return False

    distribution_layout = getattr(active_irl, "distribution_layout", None)
    runtime_layers = list(getattr(distribution_layout, "layers", [])) if distribution_layout is not None else []
    if len(runtime_layers) != len(layers):
        return False

    for runtime_layer, layer in zip(runtime_layers, layers):
        runtime_layer.enabled = bool(layer.get("enabled", True))
        max_per_bin = layer.get("max_pieces_per_bin")
        runtime_layer.max_pieces_per_bin = (
            max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None
        )
    return True


def _live_chute_status() -> Dict[str, Any]:
    irl = _active_irl()
    if irl is None:
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
            "home_pin_channel": None,
        }

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
            "home_pin_channel": None,
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
        "home_pin_channel": _pin_channel(getattr(chute, "home_pin", None)),
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

    irl = _active_irl()
    if irl is None:
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": endstop_active_high,
            "stepper_direction_inverted": stepper_direction_inverted,
            "current_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_enabled": None,
            "stepper_current": None,
            "stepper_stopped": None,
            "bound_stepper_name": None,
            "bound_stepper_channel": None,
            "home_pin_channel": None,
        }

    carousel_hw = getattr(irl, "carousel_hw", None)
    stepper = getattr(irl, "carousel_stepper", None)
    home_pin_channel = _pin_channel(getattr(carousel_hw, "home_pin", None))

    if stepper is None or carousel_hw is None:
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": endstop_active_high,
            "stepper_direction_inverted": stepper_direction_inverted,
            "current_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_enabled": None,
            "stepper_current": None,
            "stepper_stopped": None,
            "bound_stepper_name": getattr(stepper, "hardware_name", None) if stepper else None,
            "bound_stepper_channel": getattr(stepper, "channel", None) if stepper else None,
            "home_pin_channel": home_pin_channel,
        }

    status: Dict[str, Any] = {
        "live_available": True,
        "endstop_triggered": None,
        "raw_endstop_high": None,
        "endstop_active_high": endstop_active_high,
        "stepper_direction_inverted": stepper_direction_inverted,
        "current_position_degrees": None,
        "stepper_microsteps": None,
        "stepper_enabled": None,
        "stepper_current": None,
        "stepper_stopped": None,
        "bound_stepper_name": getattr(stepper, "hardware_name", None),
        "bound_stepper_channel": getattr(stepper, "channel", None),
        "home_pin_channel": home_pin_channel,
    }

    try:
        status["raw_endstop_high"] = carousel_hw.raw_endstop_active
        status["endstop_triggered"] = carousel_hw.endstop_triggered
    except Exception as e:
        status["endstop_error"] = str(e)

    try:
        status["current_position_degrees"] = float(stepper.position_degrees)
        status["stepper_microsteps"] = int(stepper.position)
    except Exception as e:
        status["stepper_position_error"] = str(e)

    try:
        status["stepper_enabled"] = bool(stepper.enabled)
    except Exception as e:
        status["stepper_enabled_error"] = str(e)

    try:
        last_current = getattr(stepper, "last_set_current", None)
        status["stepper_current"] = last_current() if callable(last_current) else last_current
    except Exception as e:
        status["stepper_current_error"] = str(e)

    try:
        status["stepper_stopped"] = bool(stepper.stopped)
    except Exception as e:
        status["stepper_stopped_error"] = str(e)

    return status


def _stop_all_steppers() -> None:
    """Stop all known steppers. Raises HTTPException on failure."""
    halted: list[str] = []
    errors: Dict[str, str] = {}

    for name, stepper in _stepper_mapping().items():
        if stepper is None:
            continue
        try:
            _halt_stepper(stepper, stepper_name=name)
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
    layout = getBinLayout()
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
    active_irl = _active_irl()

    if active_irl is None:
        return {
            "ok": True,
            "backend": servo_settings["backend"],
            "live_available": False,
            "layers": [],
        }

    servos = list(getattr(active_irl, "servos", []))
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
    layout = getBinLayout()
    current_storage_layers = _storage_layer_settings_from_layout(layout)["layers"]

    if len(payload.channels) != layer_count:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {layer_count} layer servo assignments, got {len(payload.channels)}.",
        )

    channels: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, channel in enumerate(payload.channels):
        channel_id = int(channel.id) if channel.id is not None else None
        layer_enabled = bool(current_storage_layers[index].get("enabled", True))

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

    previous_ids = [int(channel["id"]) if channel["id"] is not None else None for channel in previous["channels"]]
    channel_ids = [int(channel["id"]) if channel["id"] is not None else None for channel in channels]
    channel_inverts = [bool(channel["invert"]) for channel in channels]

    structural_change = (
        backend != previous["backend"]
        or channel_ids != previous_ids
        or (backend == "waveshare" and port != previous["port"])
    )

    active_irl = _active_irl()
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
                    elif hasattr(servo, "set_preset_angles"):
                        if invert:
                            servo.set_preset_angles(closed_angle, open_angle)
                        else:
                            servo.set_preset_angles(open_angle, closed_angle)
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


@router.post("/api/hardware-config/servo/layers/{layer_index}/toggle")
def toggle_layer_servo(layer_index: int) -> Dict[str, Any]:
    _ensure_not_homing("toggle a servo")
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
        active_irl = shared_state.getActiveIRL()
        if active_irl is not None and shared_state.gc_ref is not None:
            servos = getattr(active_irl, "servos", [])
            save_servo_states(servos, shared_state.gc_ref)
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
    _ensure_not_homing("preview a servo")
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
    _ensure_not_homing("calibrate a servo")
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


@router.post("/api/hardware-config/servo/layers/{layer_index}/nudge")
def nudge_layer_servo(layer_index: int, payload: ServoNudgePayload) -> Dict[str, Any]:
    _ensure_not_homing("nudge a servo")
    servo = _live_servo_for_layer(layer_index)

    if not hasattr(servo, "move_to") or not hasattr(servo, "position"):
        raise HTTPException(status_code=500, detail="Servo does not support position-based movement.")

    try:
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


@router.get("/api/hardware/servo-status")
def get_servo_status() -> Dict[str, Any]:
    """Per-layer servo online state for debugging the red
    "Servo bus offline" banner. Returns one entry per layer with its
    live ``available`` flag plus the aggregate ``bus_online`` status —
    useful when the operator has reconnected the Waveshare USB and
    wants to verify the bus is back before pressing Resume.
    """
    active_irl = _active_irl()
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
    return {
        "ok": True,
        "bus_online": any_online,
        "layers": layers,
        "offline_since_ts": runtime_stats_service.servo_bus_offline_since_ts(),
    }


@router.get("/api/hardware-config/waveshare/ports")
def get_waveshare_ports() -> Dict[str, Any]:
    status = _waveshare_inventory_status()
    return {"ok": True, "ports": status.get("ports", [])}


@router.get("/api/hardware-config/waveshare/status")
def get_waveshare_inventory_status(port: str | None = None) -> Dict[str, Any]:
    return _waveshare_inventory_status(port=port)


@router.post("/api/hardware-config/waveshare/rescan")
def rescan_waveshare_inventory(port: str | None = None) -> Dict[str, Any]:
    _ensure_not_homing("scan Waveshare servos")
    return _waveshare_inventory_status(port=port, refresh=True)


@router.get("/api/hardware-config/waveshare/servos")
def get_waveshare_servos(port: str | None = None) -> Dict[str, Any]:
    status = _waveshare_inventory_status(port=port)
    return {
        "ok": True,
        "servos": status.get("servos", []),
        "highest_seen_id": status.get("highest_seen_id", 0),
        "suggested_next_id": status.get("suggested_next_id"),
    }


@router.post("/api/hardware-config/waveshare/servos/{servo_id}/set-id")
def set_waveshare_servo_id(servo_id: int, payload: ServoSetIdPayload) -> Dict[str, Any]:
    """Change a servo's ID on the bus."""
    _ensure_not_homing("change a Waveshare servo ID")
    new_id = payload.new_id
    if new_id < 1 or new_id > 253:
        raise HTTPException(status_code=400, detail="New ID must be between 1 and 253.")
    if new_id == servo_id:
        raise HTTPException(status_code=400, detail="New ID is the same as the current ID.")

    service = _get_waveshare_service(timeout=0.02)
    if service is None:
        raise HTTPException(status_code=503, detail="No Waveshare bus available.")

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
            get_waveshare_inventory_manager().refresh(port=getattr(service, "port", None))
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

    service = _get_waveshare_service(timeout=0.02)
    if service is None:
        raise HTTPException(status_code=503, detail="No Waveshare bus available.")

    try:
        if not service.ping(servo_id):
            raise HTTPException(status_code=404, detail=f"No servo with ID {servo_id} found on the bus.")

        try:
            safe_min, safe_max = service.calibrate_servo(servo_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Calibration failed: {exc}")

        info = service.read_servo_info(servo_id)
        try:
            get_waveshare_inventory_manager().refresh(port=getattr(service, "port", None))
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

    service = _get_waveshare_service(timeout=0.02)
    if service is None:
        raise HTTPException(status_code=503, detail="No Waveshare bus available.")

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

    service = _get_waveshare_service(timeout=0.02)
    if service is None:
        raise HTTPException(status_code=503, detail="No Waveshare bus available.")

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
    operating_speed_microsteps_per_second = int(payload.operating_speed_microsteps_per_second)
    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        raise HTTPException(
            status_code=400,
            detail="pillar_width_deg must be between 0 and less than 60 degrees",
        )
    if operating_speed_microsteps_per_second <= 0:
        raise HTTPException(
            status_code=400,
            detail="operating_speed_microsteps_per_second must be greater than 0",
        )

    params_path, config = _read_machine_params_config()
    chute_config = config.get("chute", {})
    if not isinstance(chute_config, dict):
        chute_config = {}
    config["chute"] = {
        **chute_config,
        "first_bin_center": first_bin_center,
        "pillar_width_deg": pillar_width_deg,
        "endstop_active_high": endstop_active_high,
        "operating_speed_microsteps_per_second": operating_speed_microsteps_per_second,
    }

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live = False
    active_irl = shared_state.getActiveIRL()
    if active_irl is not None:
        chute = getattr(active_irl, "chute", None)
        if chute is not None and hasattr(chute, "setCalibration"):
            try:
                chute.setCalibration(first_bin_center, pillar_width_deg, endstop_active_high)
                if hasattr(chute, "setOperatingSpeed"):
                    chute.setOperatingSpeed(operating_speed_microsteps_per_second)
                stepper = getattr(active_irl, "chute_stepper", None)
                if stepper is not None:
                    stepper.set_speed_limits(16, operating_speed_microsteps_per_second)
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
    irl = _active_irl()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Open the Motion or Endstops step to power on the steppers first.")

    chute = getattr(irl, "chute", None)
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
        "message": "Step 1 complete. Chute moved slowly until the endstop was found and then moved to bin 1.",
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

    live_irl = _active_irl()
    if live_irl is not None:
        stepper = getattr(live_irl, "carousel_stepper", None)
        if stepper is not None and hasattr(stepper, "set_direction_inverted"):
            try:
                stepper.set_direction_inverted(stepper_direction_inverted)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Settings were saved, but live direction inversion could not be applied: {e}",
                )
        carousel_hw = getattr(live_irl, "carousel_hw", None)
        if carousel_hw is not None:
            try:
                carousel_hw.endstop_active_high = endstop_active_high
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Settings were saved, but live carousel endstop polarity could not be applied: {e}",
                )

    return {
        "ok": True,
        "settings": _carousel_settings_from_config(config),
        "status": _live_carousel_status(),
        "message": "Carousel settings saved.",
    }


@router.post("/api/hardware-config/carousel/home")
def home_carousel_to_endstop() -> Dict[str, Any]:
    irl = _active_irl()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Open the Motion or Endstops step to power on the steppers first.")

    carousel_hw = getattr(irl, "carousel_hw", None)
    if carousel_hw is None:
        raise HTTPException(status_code=503, detail="Carousel hardware not initialized.")

    success = carousel_hw.home()
    if not success:
        raise HTTPException(status_code=500, detail="Carousel homing failed.")

    return {
        "ok": True,
        "status": _live_carousel_status(),
        "message": "Carousel homed and zeroed.",
    }


@router.post("/api/hardware-config/carousel/calibrate")
def calibrate_carousel() -> Dict[str, Any]:
    """Calibrate carousel by measuring steps for one full revolution."""
    irl = _active_irl()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Open the Motion or Endstops step to power on the steppers first.")

    carousel_hw = getattr(irl, "carousel_hw", None)
    if carousel_hw is None:
        raise HTTPException(status_code=503, detail="Carousel hardware not initialized.")

    if not carousel_hw.endstop_triggered:
        raise HTTPException(
            status_code=409,
            detail="Carousel must be homed first (endstop not currently triggered).",
        )

    # Defaults mirror the pre-cutover ``subsystems.classification.carousel_hardware``
    # values — 200 microsteps backoff before re-homing, 1500 microsteps/s
    # home approach. Live wiring on the machine should be verified.
    BACKOFF_STEPS = 200
    HOME_SPEED_MICROSTEPS_PER_SEC = 1500

    stepper = carousel_hw.stepper
    home_pin = carousel_hw.home_pin

    try:
        stepper.enabled = True

        stepper.move_steps_blocking(-BACKOFF_STEPS, timeout_ms=5000)

        stepper.position = 0

        stepper.home(
            HOME_SPEED_MICROSTEPS_PER_SEC,
            home_pin,
            home_pin_active_high=carousel_hw.endstop_active_high,
        )
        start = time.monotonic()
        while not stepper.stopped:
            if (time.monotonic() - start) * 1000 > CAROUSEL_CALIBRATE_TIMEOUT_MS:
                stepper.move_at_speed(0)
                raise TimeoutError("Carousel calibration timed out.")
            time.sleep(0.01)

        if not carousel_hw.endstop_triggered:
            raise HTTPException(
                status_code=409,
                detail="Calibration failed: endstop did not trigger after full rotation.",
            )

        measured_steps = abs(stepper.position)

        params_path, config = _read_machine_params_config()
        carousel_config = config.get("carousel", {})
        if not isinstance(carousel_config, dict):
            carousel_config = {}
        carousel_config["steps_per_revolution"] = measured_steps
        config["carousel"] = carousel_config
        _write_machine_params_config(params_path, config)

        stepper.steps_per_revolution = measured_steps
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
    layout = getBinLayout()
    current = _storage_layer_settings_from_layout(layout)
    requested_layers = list(payload.layers)
    if requested_layers:
        layer_updates = [
            {
                "bin_count": int(layer.bin_count),
                "enabled": bool(layer.enabled),
                "servo_open_angle": layer.servo_open_angle,
                "servo_closed_angle": layer.servo_closed_angle,
                "max_pieces_per_bin": layer.max_pieces_per_bin,
            }
            for layer in requested_layers
        ]
    else:
        layer_updates = [
            {
                "bin_count": int(count),
                "enabled": bool(layer.get("enabled", True)),
                "servo_open_angle": layer.get("servo_open_angle"),
                "servo_closed_angle": layer.get("servo_closed_angle"),
                "max_pieces_per_bin": layer.get("max_pieces_per_bin"),
            }
            for count, layer in zip(payload.layer_bin_counts, current["layers"])
        ]

    new_layer_configs: List[LayerConfig] = []
    layout_changed = len(layer_updates) != len(current["layers"])
    enabled_changed = False
    default_section_count = int(current["layers"][0]["section_count"]) if current["layers"] else DEFAULT_STORAGE_LAYER_SECTION_COUNT
    default_bin_size = current["layers"][0]["bin_size"] if current["layers"] else "medium"

    for i, layer_update in enumerate(layer_updates):
        count = int(layer_update["bin_count"])
        enabled = bool(layer_update["enabled"])
        if count not in ALLOWED_STORAGE_LAYER_BIN_COUNTS:
            raise HTTPException(
                status_code=400,
                detail=f"Each layer bin count must be one of {ALLOWED_STORAGE_LAYER_BIN_COUNTS}.",
            )

        cur_layer = current["layers"][i] if i < len(current["layers"]) else None
        section_count = int(cur_layer["section_count"]) if cur_layer else default_section_count
        if section_count <= 0 or count % section_count != 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Layer {i + 1} cannot be configured to {count} bins "
                    f"with {section_count} sections."
                ),
            )

        bins_per_section = count // section_count
        bin_size = cur_layer["bin_size"] if cur_layer else default_bin_size
        sections = [[bin_size] * bins_per_section for _ in range(section_count)]

        servo_open = layer_update.get("servo_open_angle")
        servo_closed = layer_update.get("servo_closed_angle")
        max_per_bin = layer_update.get("max_pieces_per_bin")
        max_per_bin_value = max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None

        new_layer_configs.append(LayerConfig(
            sections=sections,
            enabled=enabled,
            servo_open_angle=servo_open if isinstance(servo_open, int) else None,
            servo_closed_angle=servo_closed if isinstance(servo_closed, int) else None,
            max_pieces_per_bin=max_per_bin_value,
        ))
        if cur_layer:
            layout_changed = layout_changed or count != int(cur_layer["bin_count"])
            enabled_changed = enabled_changed or enabled != bool(cur_layer.get("enabled", True))
            if max_per_bin_value != cur_layer.get("max_pieces_per_bin"):
                enabled_changed = True
        else:
            layout_changed = True

    if not layout_changed and not enabled_changed:
        return {
            "ok": True,
            "settings": current,
            "applied_live": False,
            "restart_required": False,
            "message": "Storage layer layout unchanged.",
        }

    try:
        saveBinLayout(BinLayoutConfig(layers=new_layer_configs))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write bin layout: {e}")

    saved_layout = getBinLayout()
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


# ---------------------------------------------------------------------------
# Bin grid – layout + move-to-bin
# ---------------------------------------------------------------------------


def _runtime_distribution_layout() -> Any | None:
    irl = _active_irl()
    if irl is None:
        return None
    return getattr(irl, "distribution_layout", None)


def _empty_categories_from_config() -> list[list[list[list[str]]]]:
    layout_config = getBinLayout()
    return [
        [[[] for _ in section] for section in layer.sections]
        for layer in layout_config.layers
    ]


def _current_bin_categories() -> list[list[list[list[str]]]]:
    runtime_layout = _runtime_distribution_layout()
    if runtime_layout is not None:
        return extractCategories(runtime_layout)

    saved = get_bin_categories()
    if saved is not None:
        layout_config = getBinLayout()
        reference_layout = mkLayoutFromConfig(layout_config)
        if layoutMatchesCategories(reference_layout, saved):
            return saved

    return _empty_categories_from_config()


def _apply_and_persist_bin_categories(categories: list[list[list[list[str]]]]) -> None:
    runtime_layout = _runtime_distribution_layout()
    if runtime_layout is not None and layoutMatchesCategories(runtime_layout, categories):
        applyCategories(runtime_layout, categories)
        set_bin_categories(extractCategories(runtime_layout))
        return

    set_bin_categories(categories)


def _clear_passthrough_alert_if_owned() -> None:
    """Clear the bins-full / misc-passthrough banner when the operator
    explicitly resets or empties bins. Otherwise the alert sticks around
    (it only auto-clears on the next successful bin assignment).

    Post-cutover: the legacy positioning subsystem no longer emits these
    specific banners, but we still scrub any lingering hardware_error
    matching the historical prefixes so stale UI state clears.
    """
    _LEGACY_BINS_FULL_PREFIX = "All bins are full"
    _LEGACY_MISC_PASSTHROUGH_PREFIX = "Misc category is passing through"
    try:
        with shared_state.hardware_lifecycle_lock:
            err = shared_state.hardware_error
            if isinstance(err, str) and (
                err.startswith(_LEGACY_BINS_FULL_PREFIX)
                or err.startswith(_LEGACY_MISC_PASSTHROUGH_PREFIX)
            ):
                shared_state.setHardwareStatus(clear_error=True)
    except Exception:
        pass


def clear_bin_category_assignments(
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
) -> dict[str, Any]:
    categories = _current_bin_categories()

    if scope == "all":
        cleared_bins = 0
        for layer in categories:
            for section in layer:
                for category_ids in section:
                    if category_ids:
                        cleared_bins += 1
                    category_ids.clear()
        _apply_and_persist_bin_categories(categories)
        runtime_stats_service.clear_bin_contents(scope=scope)
        clear_current_session_bins(scope=scope)
        return {
            "ok": True,
            "scope": scope,
            "cleared_bins": cleared_bins,
            "message": "Reset all bins and cleared their assignments.",
        }

    if layer_index is None or layer_index < 0 or layer_index >= len(categories):
        raise HTTPException(status_code=400, detail="Invalid layer index.")

    if scope == "layer":
        cleared_bins = 0
        for section in categories[layer_index]:
            for category_ids in section:
                if category_ids:
                    cleared_bins += 1
                category_ids.clear()
        _apply_and_persist_bin_categories(categories)
        runtime_stats_service.clear_bin_contents(scope=scope, layer_index=layer_index)
        clear_current_session_bins(scope=scope, layer_index=layer_index)
        return {
            "ok": True,
            "scope": scope,
            "layer_index": layer_index,
            "cleared_bins": cleared_bins,
            "message": f"Reset all bins on layer {layer_index + 1} and cleared their assignments.",
        }

    if scope != "bin":
        raise HTTPException(status_code=400, detail="Unsupported clear scope.")

    if section_index is None or section_index < 0 or section_index >= len(categories[layer_index]):
        raise HTTPException(status_code=400, detail="Invalid section index.")
    if bin_index is None or bin_index < 0 or bin_index >= len(categories[layer_index][section_index]):
        raise HTTPException(status_code=400, detail="Invalid bin index.")

    had_categories = bool(categories[layer_index][section_index][bin_index])
    categories[layer_index][section_index][bin_index] = []
    _apply_and_persist_bin_categories(categories)
    runtime_stats_service.clear_bin_contents(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
    )
    clear_current_session_bins(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
    )
    return {
        "ok": True,
        "scope": scope,
        "layer_index": layer_index,
        "section_index": section_index,
        "bin_index": bin_index,
        "cleared_bins": 1 if had_categories else 0,
        "message": f"Reset bin {bin_index + 1} on layer {layer_index + 1} and cleared its assignment.",
    }


def clear_bin_contents(
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
) -> dict[str, Any]:
    if scope == "all":
        runtime_stats_service.clear_bin_contents(scope=scope)
        cleared = clear_current_session_bins(scope=scope)
        return {
            "ok": True,
            "scope": scope,
            "cleared_bins": int(cleared.get("cleared_bins", 0)),
            "message": "Emptied all bins without changing their assignments.",
        }

    categories = _current_bin_categories()
    if layer_index is None or layer_index < 0 or layer_index >= len(categories):
        raise HTTPException(status_code=400, detail="Invalid layer index.")

    if scope == "layer":
        runtime_stats_service.clear_bin_contents(scope=scope, layer_index=layer_index)
        cleared = clear_current_session_bins(scope=scope, layer_index=layer_index)
        return {
            "ok": True,
            "scope": scope,
            "layer_index": layer_index,
            "cleared_bins": int(cleared.get("cleared_bins", 0)),
            "message": f"Emptied all bins on layer {layer_index + 1} without changing assignments.",
        }

    if scope != "bin":
        raise HTTPException(status_code=400, detail="Unsupported clear scope.")

    if section_index is None or section_index < 0 or section_index >= len(categories[layer_index]):
        raise HTTPException(status_code=400, detail="Invalid section index.")
    if bin_index is None or bin_index < 0 or bin_index >= len(categories[layer_index][section_index]):
        raise HTTPException(status_code=400, detail="Invalid bin index.")

    cleared = clear_current_session_bins(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
    )
    runtime_stats_service.clear_bin_contents(
        scope=scope,
        layer_index=layer_index,
        section_index=section_index,
        bin_index=bin_index,
    )
    return {
        "ok": True,
        "scope": scope,
        "layer_index": layer_index,
        "section_index": section_index,
        "bin_index": bin_index,
        "cleared_bins": int(cleared.get("cleared_bins", 0)),
        "message": f"Emptied bin {bin_index + 1} on layer {layer_index + 1} without changing its assignment.",
    }


@router.get("/api/bins/layout")
def get_bins_layout() -> Dict[str, Any]:
    """Return the full bin grid: layers → sections → bins, with chute angles."""
    layout_config = getBinLayout()
    _, config = _read_machine_params_config()
    chute_cfg = _chute_settings_from_config(config)
    first_bin_center = float(chute_cfg.get("first_bin_center", DEFAULT_CHUTE_FIRST_BIN_CENTER))
    pillar_width_deg = float(chute_cfg.get("pillar_width_deg", DEFAULT_CHUTE_PILLAR_WIDTH_DEG))
    usable_per_section = 60.0 - pillar_width_deg

    layers_out = []
    for layer_idx, layer in enumerate(layout_config.layers):
        sections = layer.sections
        bins_flat = []
        global_bin = 0
        for section_idx, section_bins in enumerate(sections):
            num_bins = len(section_bins)
            bin_width = usable_per_section / num_bins if num_bins else 0
            for bin_idx, bin_size in enumerate(section_bins):
                angle = first_bin_center + section_idx * 60 + bin_idx * bin_width
                bins_flat.append({
                    "section_index": section_idx,
                    "bin_index": bin_idx,
                    "global_index": global_bin,
                    "size": bin_size,
                    "angle": round(angle, 2),
                })
                global_bin += 1
        max_per_bin = getattr(layer, "max_pieces_per_bin", None)
        layers_out.append({
            "layer_index": layer_idx,
            "enabled": layer.enabled,
            "section_count": len(sections),
            "bin_count": global_bin,
            "max_pieces_per_bin": max_per_bin if isinstance(max_per_bin, int) and max_per_bin > 0 else None,
            "bins": bins_flat,
        })

    # Overlay category assignments from live layout if available
    current_angle = None
    active_layer = None
    runtime_overlay_applied = False
    active_irl = shared_state.getActiveIRL()
    if active_irl is not None:
        chute = getattr(active_irl, "chute", None)
        if chute is not None:
            try:
                current_angle = round(float(chute.current_angle), 2)
            except Exception:
                pass
        servos = list(getattr(active_irl, "servos", []))
        for i, servo in enumerate(servos):
            try:
                if hasattr(servo, "isOpen") and servo.isOpen():
                    active_layer = i
                    break
            except Exception:
                pass

        # Read category assignments from the live distribution layout
        dist_layout = getattr(active_irl, "distribution_layout", None)
        if dist_layout is not None:
            runtime_layers = list(getattr(dist_layout, "layers", []))
            for layer_out in layers_out:
                li = layer_out["layer_index"]
                if li < len(runtime_layers):
                    runtime_overlay_applied = True
                    rt_layer = runtime_layers[li]
                    rt_sections = list(rt_layer.sections)
                    for bin_out in layer_out["bins"]:
                        si = bin_out["section_index"]
                        bi = bin_out["bin_index"]
                        if si < len(rt_sections) and bi < len(rt_sections[si].bins):
                            bin_out["category_ids"] = list(rt_sections[si].bins[bi].category_ids)

    if not runtime_overlay_applied:
        saved_categories = get_bin_categories()
        reference_layout = mkLayoutFromConfig(layout_config)
        if saved_categories is not None and layoutMatchesCategories(reference_layout, saved_categories):
            for layer_out in layers_out:
                li = layer_out["layer_index"]
                for bin_out in layer_out["bins"]:
                    si = bin_out["section_index"]
                    bi = bin_out["bin_index"]
                    bin_out["category_ids"] = list(saved_categories[li][si][bi])

    # Ensure every bin has category_ids even if live layout wasn't available
    for layer_out in layers_out:
        for bin_out in layer_out["bins"]:
            bin_out.setdefault("category_ids", [])

    return {
        "ok": True,
        "layers": layers_out,
        "current_angle": current_angle,
        "active_layer": active_layer,
    }


@router.post("/api/bins/move-to")
def move_to_bin(payload: MoveToBinPayload) -> Dict[str, Any]:
    """Move chute to a specific bin and open the correct layer servo."""
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized.")
    chute = getattr(irl, "chute", None)
    if chute is None:
        raise HTTPException(status_code=503, detail="Chute subsystem not available.")

    servos = list(getattr(irl, "servos", []))
    if payload.layer_index < 0 or payload.layer_index >= len(servos):
        raise HTTPException(status_code=400, detail=f"Invalid layer index {payload.layer_index}.")

    address = BinAddress(
        layer_index=payload.layer_index,
        section_index=payload.section_index,
        bin_index=payload.bin_index,
    )

    target_angle = chute.getAngleForBin(address)
    if target_angle is None:
        raise HTTPException(status_code=400, detail="Bin is unreachable (angle out of range).")

    # Close all servos first, then open the target layer
    for i, servo in enumerate(servos):
        try:
            if hasattr(servo, "isOpen") and servo.isOpen():
                servo.close()
        except Exception:
            pass

    try:
        estimated_ms = chute.moveToBin(address)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chute move failed: {e}")

    # Open the target layer servo
    target_servo = servos[payload.layer_index]
    try:
        if hasattr(target_servo, "open"):
            target_servo.open()
    except Exception:
        pass

    return {
        "ok": True,
        "target_angle": round(target_angle, 2),
        "estimated_ms": estimated_ms,
        "layer_index": payload.layer_index,
        "section_index": payload.section_index,
        "bin_index": payload.bin_index,
    }


@router.post("/api/bins/categories/clear")
def clear_bins_categories(payload: ClearBinCategoriesPayload) -> Dict[str, Any]:
    return clear_bin_category_assignments(
        scope=payload.scope,
        layer_index=payload.layer_index,
        section_index=payload.section_index,
        bin_index=payload.bin_index,
    )


@router.post("/api/bins/contents/clear")
def clear_bins_contents(payload: ClearBinContentsPayload) -> Dict[str, Any]:
    return clear_bin_contents(
        scope=payload.scope,
        layer_index=payload.layer_index,
        section_index=payload.section_index,
        bin_index=payload.bin_index,
    )


@router.get("/api/bins/contents")
def get_bin_contents() -> Dict[str, Any]:
    persisted = get_current_bin_contents_snapshot()
    if persisted.get("bins"):
        return persisted

    try:
        snapshot = runtime_stats_service.bin_contents_snapshot()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to build bin contents: {exc}")
    return snapshot if snapshot is not None else persisted
