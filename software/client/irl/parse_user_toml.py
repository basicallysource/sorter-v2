import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import tomllib

from global_config import GlobalConfig
from hardware.bus import MCUBusError

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor

MACHINE_SPECIFIC_PARAMS_ENV_VAR = "MACHINE_SPECIFIC_PARAMS_PATH"

# User may override these defaults by setting MACHINE_SPECIFIC_PARAMS_PATH to a TOML file.
DEFAULT_SERVO_OPEN_ANGLE = 10
DEFAULT_SERVO_CLOSED_ANGLE = 83
DEFAULT_STEPPER_IRUN = 16
DEFAULT_STEPPER_IHOLD = 16
DEFAULT_STEPPER_IHOLD_DELAY = 8

VALID_BIN_SIZES = {"small", "medium", "big"}

DEFAULT_LAYER_SECTIONS: list[list[str]] = [
    ["medium", "medium"],
    ["medium", "medium"],
    ["medium", "medium"],
    ["medium", "medium"],
    ["medium", "medium"],
    ["medium", "medium"],
]


@dataclass
class MachineConfig:
    servo_open_angle: int = DEFAULT_SERVO_OPEN_ANGLE
    servo_closed_angle: int = DEFAULT_SERVO_CLOSED_ANGLE
    layer_sections: list[list[list[str]]] = field(default_factory=list)
    servo_open_angle_overrides: dict[int, int] = field(default_factory=dict)
    servo_closed_angle_overrides: dict[int, int] = field(default_factory=dict)
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

    raw: object
    try:
        raw = tomllib.loads(raw_text)
    except Exception as e:
        gc.logger.warning(
            f"Failed to parse machine-specific params TOML at {stepper_current_config_path}: {e}. Using defaults."
        )
        return {}

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

        overrides[stepper_name] = (irun, ihold, ihold_delay)

    return overrides


def _validateAngle(gc: GlobalConfig, name: str, value: object, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 180:
        return value
    gc.logger.warning(f"Invalid {name}={value!r}; expected int 0-180. Using default {default}.")
    return default


def _validateLayerSections(gc: GlobalConfig, raw_sections: object, layer_idx: int) -> list[list[str]] | None:
    if not isinstance(raw_sections, list):
        gc.logger.warning(f"Layer {layer_idx} sections must be a list. Skipping layer.")
        return None
    sections: list[list[str]] = []
    for section in raw_sections:
        if not isinstance(section, list):
            gc.logger.warning(f"Layer {layer_idx} section must be a list of bin sizes. Skipping layer.")
            return None
        for bin_size in section:
            if bin_size not in VALID_BIN_SIZES:
                gc.logger.warning(
                    f"Invalid bin size '{bin_size}' in layer {layer_idx}. Must be one of: {VALID_BIN_SIZES}"
                )
                return None
        sections.append(section)
    return sections


def _parseAngleOverrides(gc: GlobalConfig, raw: object, name: str, default: int) -> dict[int, int]:
    if not isinstance(raw, dict):
        gc.logger.warning(f"{name} must be a table. Ignoring.")
        return {}
    overrides: dict[int, int] = {}
    for key, value in raw.items():
        try:
            idx = int(key)
        except (ValueError, TypeError):
            gc.logger.warning(f"Invalid layer index '{key}' in {name}. Skipping.")
            continue
        overrides[idx] = _validateAngle(gc, f"{name}.{key}", value, default)
    return overrides


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

    layers_table = raw.get("layers")
    if isinstance(layers_table, dict):
        raw_sections = layers_table.get("sections")
        if isinstance(raw_sections, list):
            for i, layer_sections in enumerate(raw_sections):
                validated = _validateLayerSections(gc, layer_sections, i)
                if validated is not None:
                    config.layer_sections.append(validated)

        raw_open = layers_table.get("servo_open_angles")
        if raw_open is not None:
            config.servo_open_angle_overrides = _parseAngleOverrides(gc, raw_open, "layers.servo_open_angles", config.servo_open_angle)

        raw_closed = layers_table.get("servo_closed_angles")
        if raw_closed is not None:
            config.servo_closed_angle_overrides = _parseAngleOverrides(gc, raw_closed, "layers.servo_closed_angles", config.servo_closed_angle)

    config.stepper_current_overrides = _parseStepperCurrentOverrides(gc, raw)

    return config


def applyStepperCurrentOverride(
    stepper: "StepperMotor",
    stepper_name: str,
    overrides: dict[str, tuple[int, int, int]],
    gc: GlobalConfig,
) -> None:
    override = overrides.get(stepper_name)
    if override is None:
        return

    irun, ihold, ihold_delay = override
    try:
        stepper.set_current(irun, ihold, ihold_delay)
    except (MCUBusError, OSError) as e:
        gc.logger.warning(
            f"Failed to apply optional current override for '{stepper_name}' (IRUN={irun}, IHOLD={ihold}, IHOLD_DELAY={ihold_delay}): {e}. Continuing with firmware defaults."
        )
        return

    gc.logger.info(
        f"Stepper '{stepper_name}' current override applied: IRUN={irun}, IHOLD={ihold}, IHOLD_DELAY={ihold_delay}"
    )
