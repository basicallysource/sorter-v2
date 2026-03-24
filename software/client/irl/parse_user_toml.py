import os
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


def loadStepperCurrentOverrides(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> dict[str, tuple[int, int, int]]:
    raw: object = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        gc.logger.warning("Stepper current config must be an object. Using defaults.")
        return {}

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


def loadServoPresetAngles(
    gc: GlobalConfig,
    machine_specific_params: dict[str, object] | None = None,
) -> tuple[int, int]:
    raw: object = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    if not isinstance(raw, dict):
        return (DEFAULT_SERVO_OPEN_ANGLE, DEFAULT_SERVO_CLOSED_ANGLE)

    servo_params = raw.get("servo")
    if servo_params is None:
        return (DEFAULT_SERVO_OPEN_ANGLE, DEFAULT_SERVO_CLOSED_ANGLE)

    if not isinstance(servo_params, dict):
        gc.logger.warning("Ignoring invalid servo config: expected object. Using defaults.")
        return (DEFAULT_SERVO_OPEN_ANGLE, DEFAULT_SERVO_CLOSED_ANGLE)

    open_angle = servo_params.get("open_angle", DEFAULT_SERVO_OPEN_ANGLE)
    closed_angle = servo_params.get("closed_angle", DEFAULT_SERVO_CLOSED_ANGLE)

    if not (isinstance(open_angle, int) and not isinstance(open_angle, bool) and 0 <= open_angle <= 180):
        gc.logger.warning(
            f"Invalid servo.open_angle={open_angle!r}; expected int in range 0-180. Using default {DEFAULT_SERVO_OPEN_ANGLE}."
        )
        open_angle = DEFAULT_SERVO_OPEN_ANGLE

    if not (isinstance(closed_angle, int) and not isinstance(closed_angle, bool) and 0 <= closed_angle <= 180):
        gc.logger.warning(
            f"Invalid servo.closed_angle={closed_angle!r}; expected int in range 0-180. Using default {DEFAULT_SERVO_CLOSED_ANGLE}."
        )
        closed_angle = DEFAULT_SERVO_CLOSED_ANGLE

    return (open_angle, closed_angle)


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
