import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

from global_config import GlobalConfig
from hardware.bus import MCUBusError
from hardware.cobs import DecodeError
from machine_setup import (
    get_machine_setup_definition,
    machine_setup_key_from_feeding_mode,
    normalize_machine_setup_key,
)

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor

MACHINE_SPECIFIC_PARAMS_ENV_VAR = "MACHINE_SPECIFIC_PARAMS_PATH"

# User may override these defaults by setting MACHINE_SPECIFIC_PARAMS_PATH to a TOML file.
DEFAULT_SERVO_OPEN_ANGLE = 10
DEFAULT_SERVO_CLOSED_ANGLE = 83
DEFAULT_STEPPER_IRUN = 16
DEFAULT_STEPPER_IHOLD = 4
DEFAULT_STEPPER_IHOLD_DELAY = 8
DEFAULT_CHUTE_FIRST_BIN_CENTER = 8.25
DEFAULT_CHUTE_PILLAR_WIDTH_DEG = 8.25
DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC = 3000
# Matches the long-running carousel homing wiring used by the stable
# pre-setup-wizard backend path.
DEFAULT_CAROUSEL_HOME_PIN_CHANNEL = 2
# Matches the SKR Pico distribution E0-STOP wiring used by the setup wizard.
DEFAULT_CHUTE_HOME_PIN_CHANNEL = 3
HARDWARE_INIT_COMMAND_ATTEMPTS = 4
HARDWARE_INIT_RETRY_DELAY_S = 0.2

LOGICAL_STEPPER_BINDING_BASES = {
    "c_channel_1": "c_channel_1_rotor",
    "c_channel_2": "c_channel_2_rotor",
    "c_channel_3": "c_channel_3_rotor",
    "carousel": "carousel",
    "chute": "chute_stepper",
}
PHYSICAL_STEPPER_BINDING_ALIASES = {
    "first_c_channel_rotor": "c_channel_1_rotor",
    "second_c_channel_rotor": "c_channel_2_rotor",
    "third_c_channel_rotor": "c_channel_3_rotor",
}
PHYSICAL_STEPPER_BINDING_NAMES = set(LOGICAL_STEPPER_BINDING_BASES.values()) | set(
    PHYSICAL_STEPPER_BINDING_ALIASES
)


def normalizePhysicalStepperBindingName(stepper_name: str) -> str:
    return PHYSICAL_STEPPER_BINDING_ALIASES.get(stepper_name, stepper_name)

VALID_FEEDING_MODES = {"auto_channels", "manual_carousel"}


def _loadLegacyFeedingModeConfig(
    gc: GlobalConfig,
    raw: dict[str, object],
) -> str:
    feeding_params = raw.get("feeding")
    if feeding_params is None:
        return "auto_channels"
    if not isinstance(feeding_params, dict):
        gc.logger.warning("Ignoring invalid feeding config: expected object. Using auto channel feeding.")
        return "auto_channels"

    mode = feeding_params.get("mode", "auto_channels")
    if not isinstance(mode, str) or mode not in VALID_FEEDING_MODES:
        gc.logger.warning(
            "Ignoring invalid feeding.mode=%r; expected one of %s. Using auto channel feeding."
            % (mode, sorted(VALID_FEEDING_MODES))
        )
        return "auto_channels"

    return mode


def loadMachineSetupConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> str:
    raw: object = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return machine_setup_key_from_feeding_mode("auto_channels")

    machine_setup_params = raw.get("machine_setup")
    if machine_setup_params is None:
        return machine_setup_key_from_feeding_mode(_loadLegacyFeedingModeConfig(gc, raw))
    if not isinstance(machine_setup_params, dict):
        gc.logger.warning(
            "Ignoring invalid machine_setup config: expected object. Falling back to feeding mode."
        )
        return machine_setup_key_from_feeding_mode(_loadLegacyFeedingModeConfig(gc, raw))

    setup_key = normalize_machine_setup_key(machine_setup_params.get("type"))
    if setup_key is None:
        fallback_key = machine_setup_key_from_feeding_mode(_loadLegacyFeedingModeConfig(gc, raw))
        gc.logger.warning(
            "Ignoring invalid machine_setup.type=%r; falling back to %r."
            % (machine_setup_params.get("type"), fallback_key)
        )
        return fallback_key

    return setup_key


def loadFeedingModeConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> str:
    raw: object = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return "auto_channels"

    machine_setup_params = raw.get("machine_setup")
    if machine_setup_params is not None:
        if not isinstance(machine_setup_params, dict):
            gc.logger.warning(
                "Ignoring invalid machine_setup config for feeding mode: expected object."
            )
        else:
            setup_key = normalize_machine_setup_key(machine_setup_params.get("type"))
            if setup_key is not None:
                return get_machine_setup_definition(setup_key).feeding_mode

    return _loadLegacyFeedingModeConfig(gc, raw)


@dataclass
class MachineConfig:
    servo_open_angle: int = DEFAULT_SERVO_OPEN_ANGLE
    servo_closed_angle: int = DEFAULT_SERVO_CLOSED_ANGLE
    stepper_current_overrides: dict[str, tuple[int, int, int]] = field(default_factory=dict)


def loadMachineSpecificParams(gc: GlobalConfig) -> dict[str, object]:
    current_override_env_path = os.getenv(MACHINE_SPECIFIC_PARAMS_ENV_VAR)

    if not current_override_env_path:
        gc.logger.info(
            f"No {MACHINE_SPECIFIC_PARAMS_ENV_VAR} set; using default stepper currents and servo angles."
        )
        return {}

    stepper_current_config_path = Path(current_override_env_path).expanduser()
    if not stepper_current_config_path.exists():
        gc.logger.warning(
            f"{MACHINE_SPECIFIC_PARAMS_ENV_VAR} is set to '{stepper_current_config_path}', but file does not exist. Using defaults."
        )
        return {}

    try:
        raw_text = stepper_current_config_path.read_text(encoding="utf-8")
    except Exception as e:
        gc.logger.warning(
            f"Failed to read machine-specific params at {stepper_current_config_path}: {e}. Using defaults."
        )
        return {}

    if tomllib is None:
        gc.logger.warning(
            "TOML parser unavailable in this Python runtime. Using defaults."
        )
        return {}

    raw: object = tomllib.loads(raw_text)

    if not isinstance(raw, dict):
        gc.logger.warning(
            f"Machine-specific params at {stepper_current_config_path} must be an object. Using defaults."
        )
        return {}

    return raw


def _parseStepperCurrentOverrides(
    gc: GlobalConfig,
    raw: dict[str, object],
) -> dict[str, tuple[int, int, int]]:
    overrides_table: object = raw.get("stepper_current_overrides")
    if overrides_table is None:
        # No explicit stepper_current_overrides table; no overrides to apply.
        return {}

    if not isinstance(overrides_table, dict):
        gc.logger.warning(
            "Stepper current overrides must be an object. Using defaults."
        )
        return {}

    overrides: dict[str, tuple[int, int, int]] = {}
    for stepper_name, value in overrides_table.items():
        if not isinstance(stepper_name, str):
            gc.logger.warning(
                f"Ignoring invalid stepper key in current config: {stepper_name!r} (must be string)"
            )
            continue

        if not isinstance(value, dict):
            gc.logger.warning(
                f"Ignoring override for '{stepper_name}': expected object with irun/ihold/ihold_delay. Using firmware current defaults."
            )
            continue

        has_irun = "irun" in value
        has_ihold = "ihold" in value
        has_ihold_delay = "ihold_delay" in value

        if not (has_irun or has_ihold or has_ihold_delay):
            gc.logger.warning(
                f"Ignoring override for '{stepper_name}': expected at least one of irun/ihold/ihold_delay. Using firmware current defaults."
            )
            continue

        irun = value.get("irun", DEFAULT_STEPPER_IRUN)
        ihold = value.get("ihold", DEFAULT_STEPPER_IHOLD)
        ihold_delay = value.get("ihold_delay", DEFAULT_STEPPER_IHOLD_DELAY)

        fields_valid = (
            type(irun) is int
            and type(ihold) is int
            and type(ihold_delay) is int
            and 0 <= irun <= 31
            and 0 <= ihold <= 31
            and 0 <= ihold_delay <= 15
        )

        if not fields_valid:
            gc.logger.warning(
                f"Ignoring invalid current override for '{stepper_name}': {value!r} (requires irun:0-31, ihold:0-31, ihold_delay:0-15). Using firmware current defaults."
            )
            continue

        missing_fields: list[str] = []
        if not has_irun:
            missing_fields.append(f"irun={DEFAULT_STEPPER_IRUN}")
        if not has_ihold:
            missing_fields.append(f"ihold={DEFAULT_STEPPER_IHOLD}")
        if not has_ihold_delay:
            missing_fields.append(f"ihold_delay={DEFAULT_STEPPER_IHOLD_DELAY}")
        if missing_fields:
            gc.logger.info(
                f"Stepper '{stepper_name}' current override missing fields; using defaults for {', '.join(missing_fields)}."
            )

        overrides[normalizePhysicalStepperBindingName(stepper_name)] = (
            irun,
            ihold,
            ihold_delay,
        )

    return overrides


def loadStepperBindingOverrides(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> dict[str, str]:
    raw: object = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return {}

    bindings_table: object = raw.get("stepper_bindings")
    if bindings_table is None:
        return {}

    if not isinstance(bindings_table, dict):
        gc.logger.warning("stepper_bindings must be an object. Ignoring stepper binding overrides.")
        return {}

    overrides: dict[str, str] = {}
    for logical_name, physical_name in bindings_table.items():
        if not isinstance(logical_name, str):
            gc.logger.warning(
                f"Ignoring invalid stepper_bindings key {logical_name!r}: must be a string."
            )
            continue
        if logical_name not in LOGICAL_STEPPER_BINDING_BASES:
            gc.logger.warning(
                f"Ignoring stepper_bindings.{logical_name}: unknown logical stepper. "
                f"Expected one of {sorted(LOGICAL_STEPPER_BINDING_BASES)}."
            )
            continue
        if not isinstance(physical_name, str):
            gc.logger.warning(
                f"Ignoring stepper_bindings.{logical_name}: expected physical stepper name string, got {physical_name!r}."
            )
            continue
        if physical_name not in PHYSICAL_STEPPER_BINDING_NAMES:
            gc.logger.warning(
                f"Ignoring stepper_bindings.{logical_name}={physical_name!r}: "
                f"expected one of {sorted(PHYSICAL_STEPPER_BINDING_NAMES)}."
            )
            continue
        overrides[logical_name] = normalizePhysicalStepperBindingName(physical_name)

    return overrides


def loadStepperCurrentOverrides(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> dict[str, tuple[int, int, int]]:
    raw: object = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return {}

    return _parseStepperCurrentOverrides(gc, raw)


def loadStepperDirectionInverts(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> dict[str, bool]:
    raw: object = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return {}

    invert_table: object = raw.get("stepper_direction_inverts")
    if invert_table is None:
        return {}

    if not isinstance(invert_table, dict):
        gc.logger.warning(
            "stepper_direction_inverts must be an object. Ignoring stepper direction overrides."
        )
        return {}

    overrides: dict[str, bool] = {}
    for logical_name, inverted in invert_table.items():
        if not isinstance(logical_name, str):
            gc.logger.warning(
                f"Ignoring invalid stepper_direction_inverts key {logical_name!r}: must be a string."
            )
            continue
        if logical_name not in LOGICAL_STEPPER_BINDING_BASES:
            gc.logger.warning(
                f"Ignoring stepper_direction_inverts.{logical_name}: unknown logical stepper. "
                f"Expected one of {sorted(LOGICAL_STEPPER_BINDING_BASES)}."
            )
            continue
        if not isinstance(inverted, bool):
            gc.logger.warning(
                f"Ignoring stepper_direction_inverts.{logical_name}={inverted!r}: expected true/false."
            )
            continue
        overrides[logical_name] = inverted

    return overrides


def _validateAngle(gc: GlobalConfig, name: str, value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 180:
        return value
    gc.logger.warning(f"Invalid {name}={value!r}; expected int 0-180. Using default {default}.")
    return default


def loadMachineConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> MachineConfig:
    raw: object = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    config = MachineConfig()

    if not isinstance(raw, dict):
        return config

    servo_params = raw.get("servo")
    if isinstance(servo_params, dict):
        config.servo_open_angle = _validateAngle(
            gc, "servo.open_angle",
            servo_params.get("open_angle", DEFAULT_SERVO_OPEN_ANGLE),
            DEFAULT_SERVO_OPEN_ANGLE,
        )
        config.servo_closed_angle = _validateAngle(
            gc, "servo.closed_angle",
            servo_params.get("closed_angle", DEFAULT_SERVO_CLOSED_ANGLE),
            DEFAULT_SERVO_CLOSED_ANGLE,
        )
    elif servo_params is not None:
        gc.logger.warning("Ignoring invalid servo config: expected object. Using defaults.")

    config.stepper_current_overrides = _parseStepperCurrentOverrides(gc, raw)

    return config


@dataclass
class ServoChannelConfig:
    id: int | None
    invert: bool = False


@dataclass
class WaveshareServoConfig:
    port: str | None  # None = auto-detect
    channels: list[ServoChannelConfig]


@dataclass
class CarouselCalibrationConfig:
    home_pin_channel: int = DEFAULT_CAROUSEL_HOME_PIN_CHANNEL
    endstop_active_high: bool = False


@dataclass
class ChuteCalibrationConfig:
    home_pin_channel: int = DEFAULT_CHUTE_HOME_PIN_CHANNEL
    first_bin_center: float = DEFAULT_CHUTE_FIRST_BIN_CENTER
    pillar_width_deg: float = DEFAULT_CHUTE_PILLAR_WIDTH_DEG
    endstop_active_high: bool = True
    operating_speed_microsteps_per_second: int = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC


def loadServoChannelConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
    *,
    backend: str | None = None,
) -> list[ServoChannelConfig]:
    raw = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return []

    servo_params = raw.get("servo")
    if not isinstance(servo_params, dict):
        return []

    channels_raw = servo_params.get("channels", [])
    if not isinstance(channels_raw, list):
        gc.logger.warning("servo.channels must be a list of {id, invert} objects.")
        return []

    backend_name = backend
    if backend_name is None:
        raw_backend = servo_params.get("backend", "pca9685")
        backend_name = raw_backend if isinstance(raw_backend, str) else "pca9685"

    channels: list[ServoChannelConfig] = []
    for i, ch in enumerate(channels_raw):
        if not isinstance(ch, dict):
            gc.logger.warning(f"Ignoring invalid servo.channels[{i}]: expected object.")
            continue

        ch_id = ch.get("id")
        if ch_id is None:
            channels.append(ServoChannelConfig(id=None, invert=bool(ch.get("invert", False))))
            continue

        if not isinstance(ch_id, int) or isinstance(ch_id, bool):
            gc.logger.warning(f"Ignoring servo.channels[{i}]: id must be an integer or null, got {ch_id!r}")
            channels.append(ServoChannelConfig(id=None, invert=bool(ch.get("invert", False))))
            continue

        if backend_name == "waveshare":
            valid = 1 <= ch_id <= 253
            valid_text = "int 1-253"
        else:
            valid = ch_id >= 0
            valid_text = "non-negative int"

        if not valid:
            gc.logger.warning(
                f"Ignoring servo.channels[{i}]: id must be {valid_text}, got {ch_id!r}"
            )
            continue

        channels.append(ServoChannelConfig(id=ch_id, invert=bool(ch.get("invert", False))))

    return channels


def loadWaveshareServoConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> WaveshareServoConfig | None:
    """Parse waveshare servo config from TOML. Returns None if backend is not 'waveshare'."""
    raw = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return None

    servo_params = raw.get("servo")
    if not isinstance(servo_params, dict):
        return None

    backend = servo_params.get("backend", "pca9685")
    if backend != "waveshare":
        return None

    port = servo_params.get("port")  # None = auto-detect
    if port is not None and not isinstance(port, str):
        gc.logger.warning(f"Invalid servo.port={port!r}; expected string. Will auto-detect.")
        port = None

    return WaveshareServoConfig(
        port=port,
        channels=loadServoChannelConfig(gc, raw, backend="waveshare"),
    )


def loadChuteCalibrationConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> ChuteCalibrationConfig:
    raw = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return ChuteCalibrationConfig()

    chute_params = raw.get("chute")
    if chute_params is None:
        return ChuteCalibrationConfig()
    if not isinstance(chute_params, dict):
        gc.logger.warning("Ignoring invalid chute config: expected object. Using defaults.")
        return ChuteCalibrationConfig()

    home_pin_channel = chute_params.get(
        "home_pin_channel", DEFAULT_CHUTE_HOME_PIN_CHANNEL
    )
    if not isinstance(home_pin_channel, int) or isinstance(home_pin_channel, bool):
        gc.logger.warning(
            "Invalid chute.home_pin_channel=%r; using default %d."
            % (home_pin_channel, DEFAULT_CHUTE_HOME_PIN_CHANNEL)
        )
        home_pin_channel = DEFAULT_CHUTE_HOME_PIN_CHANNEL

    first_bin_center = chute_params.get(
        "first_bin_center", DEFAULT_CHUTE_FIRST_BIN_CENTER
    )
    pillar_width_deg = chute_params.get(
        "pillar_width_deg", DEFAULT_CHUTE_PILLAR_WIDTH_DEG
    )
    endstop_active_high = chute_params.get("endstop_active_high", True)
    operating_speed_microsteps_per_second = chute_params.get(
        "operating_speed_microsteps_per_second",
        DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC,
    )

    if not isinstance(first_bin_center, (int, float)) or isinstance(first_bin_center, bool):
        gc.logger.warning(
            f"Invalid chute.first_bin_center={first_bin_center!r}; using default {DEFAULT_CHUTE_FIRST_BIN_CENTER}."
        )
        first_bin_center = DEFAULT_CHUTE_FIRST_BIN_CENTER
    else:
        first_bin_center = float(first_bin_center)

    if not isinstance(pillar_width_deg, (int, float)) or isinstance(pillar_width_deg, bool):
        gc.logger.warning(
            f"Invalid chute.pillar_width_deg={pillar_width_deg!r}; using default {DEFAULT_CHUTE_PILLAR_WIDTH_DEG}."
        )
        pillar_width_deg = DEFAULT_CHUTE_PILLAR_WIDTH_DEG
    else:
        pillar_width_deg = float(pillar_width_deg)

    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        gc.logger.warning(
            f"Invalid chute.pillar_width_deg={pillar_width_deg!r}; expected 0 <= value < 60. Using default {DEFAULT_CHUTE_PILLAR_WIDTH_DEG}."
        )
        pillar_width_deg = DEFAULT_CHUTE_PILLAR_WIDTH_DEG

    if not isinstance(endstop_active_high, bool):
        gc.logger.warning(
            f"Invalid chute.endstop_active_high={endstop_active_high!r}; using default True."
        )
        endstop_active_high = True

    if not isinstance(operating_speed_microsteps_per_second, int) or isinstance(
        operating_speed_microsteps_per_second, bool
    ):
        gc.logger.warning(
            "Invalid chute.operating_speed_microsteps_per_second="
            f"{operating_speed_microsteps_per_second!r}; using default "
            f"{DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC}."
        )
        operating_speed_microsteps_per_second = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC

    if operating_speed_microsteps_per_second <= 0:
        gc.logger.warning(
            "Invalid chute.operating_speed_microsteps_per_second="
            f"{operating_speed_microsteps_per_second!r}; expected > 0. Using default "
            f"{DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC}."
        )
        operating_speed_microsteps_per_second = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC

    return ChuteCalibrationConfig(
        home_pin_channel=home_pin_channel,
        first_bin_center=first_bin_center,
        pillar_width_deg=pillar_width_deg,
        endstop_active_high=endstop_active_high,
        operating_speed_microsteps_per_second=operating_speed_microsteps_per_second,
    )


def loadCarouselCalibrationConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> CarouselCalibrationConfig:
    raw = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return CarouselCalibrationConfig()

    carousel_params = raw.get("carousel")
    if carousel_params is None:
        return CarouselCalibrationConfig()
    if not isinstance(carousel_params, dict):
        gc.logger.warning("Ignoring invalid carousel config: expected object. Using defaults.")
        return CarouselCalibrationConfig()

    home_pin_channel = carousel_params.get(
        "home_pin_channel", DEFAULT_CAROUSEL_HOME_PIN_CHANNEL
    )
    if not isinstance(home_pin_channel, int) or isinstance(home_pin_channel, bool):
        gc.logger.warning(
            "Invalid carousel.home_pin_channel=%r; using default %d."
            % (home_pin_channel, DEFAULT_CAROUSEL_HOME_PIN_CHANNEL)
        )
        home_pin_channel = DEFAULT_CAROUSEL_HOME_PIN_CHANNEL

    endstop_active_high = carousel_params.get("endstop_active_high", False)
    if not isinstance(endstop_active_high, bool):
        gc.logger.warning(
            f"Invalid carousel.endstop_active_high={endstop_active_high!r}; using default False."
        )
        endstop_active_high = False

    return CarouselCalibrationConfig(
        home_pin_channel=home_pin_channel,
        endstop_active_high=endstop_active_high,
    )


@dataclass
class CameraLayoutConfig:
    """Camera layout from TOML [cameras] section.

    layout = "default" (single feeder camera + classification cameras)
    layout = "split_feeder" (separate cameras per c-channel + carousel)
    """
    layout: str = "default"
    # split_feeder cameras: c-channels are indices, carousel may be index or URL
    c_channel_2: int | None = None
    c_channel_3: int | None = None
    carousel: int | str | None = None
    # classification cameras — int (device index) or str (URL, e.g. MJPEG stream)
    classification_top: int | str | None = None
    classification_bottom: int | str | None = None


def loadCameraLayoutConfig(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> CameraLayoutConfig | None:
    """Parse camera layout config from TOML. Returns None if no [cameras] section."""
    raw = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return None

    cameras_params = raw.get("cameras")
    if not isinstance(cameras_params, dict):
        return None

    layout = cameras_params.get("layout", "default")
    if layout not in ("default", "split_feeder"):
        gc.logger.warning(f"Unknown cameras.layout={layout!r}; expected 'default' or 'split_feeder'. Using default.")
        return CameraLayoutConfig(layout="default")

    if layout == "split_feeder":
        c_channel_2 = cameras_params.get("c_channel_2")
        c_channel_3 = cameras_params.get("c_channel_3")
        carousel = cameras_params.get("carousel")

        for name, val in [("c_channel_2", c_channel_2), ("c_channel_3", c_channel_3)]:
            if val is not None and not isinstance(val, int):
                gc.logger.warning(f"cameras.{name}={val!r} must be an integer camera index.")

        if carousel is not None and not isinstance(carousel, (int, str)):
            gc.logger.warning("cameras.carousel must be an integer index or URL string.")

        # Classification cameras: int (device index) or str (URL)
        classification_top = cameras_params.get("classification_top")
        classification_bottom = cameras_params.get("classification_bottom")
        for name, val in [("classification_top", classification_top), ("classification_bottom", classification_bottom)]:
            if val is not None and not isinstance(val, (int, str)):
                gc.logger.warning(f"cameras.{name}={val!r} must be an integer index or URL string.")

        return CameraLayoutConfig(
            layout="split_feeder",
            c_channel_2=c_channel_2 if isinstance(c_channel_2, int) else None,
            c_channel_3=c_channel_3 if isinstance(c_channel_3, int) else None,
            carousel=carousel if isinstance(carousel, (int, str)) else None,
            classification_top=classification_top if isinstance(classification_top, (int, str)) else None,
            classification_bottom=classification_bottom if isinstance(classification_bottom, (int, str)) else None,
        )

    return CameraLayoutConfig(layout="default")


def applyStepperCurrentOverride(
    stepper: "StepperMotor",
    stepper_name: str,
    overrides: dict[str, tuple[int, int, int]],
    gc: GlobalConfig,
) -> None:
    override = overrides.get(stepper_name)
    if override is None:
        irun, ihold, ihold_delay = (
            DEFAULT_STEPPER_IRUN,
            DEFAULT_STEPPER_IHOLD,
            DEFAULT_STEPPER_IHOLD_DELAY,
        )
        source = "defaults"
    else:
        irun, ihold, ihold_delay = override
        source = "override"

    for attempt in range(1, HARDWARE_INIT_COMMAND_ATTEMPTS + 1):
        try:
            stepper.set_current(irun, ihold, ihold_delay)
            break
        except (MCUBusError, OSError, DecodeError) as e:
            if attempt == HARDWARE_INIT_COMMAND_ATTEMPTS:
                gc.logger.warning(
                    f"Failed to apply stepper current config for '{stepper_name}' from {source} "
                    f"(IRUN={irun}, IHOLD={ihold}, IHOLD_DELAY={ihold_delay}) after "
                    f"{HARDWARE_INIT_COMMAND_ATTEMPTS} attempts: {e}. Continuing."
                )
                return
            gc.logger.warning(
                f"Failed to apply stepper current config for '{stepper_name}' from {source} "
                f"on attempt {attempt}/{HARDWARE_INIT_COMMAND_ATTEMPTS}: {e}. "
                f"Retrying in {HARDWARE_INIT_RETRY_DELAY_S:.2f}s..."
            )
            time.sleep(HARDWARE_INIT_RETRY_DELAY_S)

    gc.logger.info(
        f"Stepper '{stepper_name}' current config applied from {source}: "
        f"IRUN={irun}, IHOLD={ihold}, IHOLD_DELAY={ihold_delay}"
    )
