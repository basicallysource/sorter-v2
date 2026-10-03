import os
from dataclasses import dataclass, field
from pathlib import Path

from global_config import GlobalConfig
import machine_toml


# Servos have no hard-coded open/closed angle defaults. A PWM servo must be
# calibrated per layer (its angles locked in via the UI) before it will move.
DEFAULT_STEPPER_IRUN = 16
DEFAULT_STEPPER_IHOLD = 4
DEFAULT_STEPPER_IHOLD_DELAY = 8
# Built-in per-motor current defaults (IRUN, IHOLD, IHOLD_DELAY), keyed by
# canonical (physical) stepper name. Applied when machine.toml has no
# [stepper_current_overrides.*] entry for that motor; motors not listed fall back
# to the global DEFAULT_STEPPER_* values above. The c-channel feeder rotors run
# cool (IRUN=4). "channel 4" is the classification-channel platter, which is
# physically the carousel motor (c_channel_4_rotor aliases carousel), so it's
# keyed under "carousel" and runs a bit warmer (IRUN=8). All hold at IHOLD=1.
DEFAULT_STEPPER_CURRENTS: dict[str, tuple[int, int, int]] = {
    "c_channel_1_rotor": (4, 1, DEFAULT_STEPPER_IHOLD_DELAY),
    "c_channel_2_rotor": (4, 1, DEFAULT_STEPPER_IHOLD_DELAY),
    "c_channel_3_rotor": (4, 1, DEFAULT_STEPPER_IHOLD_DELAY),
    "carousel": (8, 1, DEFAULT_STEPPER_IHOLD_DELAY),
}
DEFAULT_CHUTE_FIRST_BIN_CENTER = 8.25
DEFAULT_CHUTE_PILLAR_WIDTH_DEG = 8.25
# Canonical chute aiming geometry (see subsystems/distribution/chute.py).
# section_width default = 360/6 - 8.25 pillar, to match the legacy geometry.
DEFAULT_CHUTE_NUM_SECTIONS = 6
DEFAULT_CHUTE_SECTION_WIDTH_DEG = 51.75
DEFAULT_CHUTE_FIRST_SECTION_OFFSET_DEG = 8.25
DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC = 3000
# Matches the SKR Pico distribution E0-STOP wiring used by the setup wizard.
DEFAULT_CHUTE_HOME_PIN_CHANNEL = 3
# For boards whose profile does not name a polarity (see BoardProfile).
DEFAULT_CHUTE_ENDSTOP_ACTIVE_HIGH = True

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
ADDITIONAL_PHYSICAL_STEPPER_NAMES = {
    "distribution_aux_1",
    "distribution_aux_2",
    "distribution_aux_3",
    "fifth_stepper",
}
PHYSICAL_STEPPER_BINDING_NAMES = (
    set(LOGICAL_STEPPER_BINDING_BASES.values())
    | set(PHYSICAL_STEPPER_BINDING_ALIASES)
    | ADDITIONAL_PHYSICAL_STEPPER_NAMES
)


def normalizePhysicalStepperBindingName(stepper_name: str) -> str:
    return PHYSICAL_STEPPER_BINDING_ALIASES.get(stepper_name, stepper_name)

@dataclass
class MachineConfig:
    servo_open_speed: int | None = None
    servo_close_speed: int | None = None
    servo_homing_speed: int | None = None
    stepper_current_overrides: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    # canonical stepper name -> (sgthrs, tcoolthrs, enabled). From
    # [stepper_stallguard.*]; consumed by stepper init (irl/config.py) and the stall monitor.
    stepper_stallguard: dict[str, tuple[int, int, bool]] = field(default_factory=dict)


def loadMachineSpecificParams(gc: GlobalConfig) -> dict[str, object]:
    if not machine_toml.machine_toml_path().exists():
        gc.logger.warning(
            f"No machine config at {machine_toml.machine_toml_path()}; using default stepper currents and servo angles."
        )
    return machine_toml.read()


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


# Built-in StallGuard defaults so a fresh machine gets working stall detection on
# the chute and carousel without any machine.toml [stepper_stallguard.*] block.
# Keyed by canonical (physical) stepper name; (sgthrs, tcoolthrs, enabled). A
# machine.toml entry for the same motor overrides its default; other motors get
# nothing unless their TOML adds them. These were tuned on the rev04 bring-up.
DEFAULT_STEPPER_STALLGUARD: dict[str, tuple[int, int, bool]] = {
    "carousel": (148, 150, True),
    "chute_stepper": (55, 150, True),
}


def _parseStepperStallguard(
    gc: GlobalConfig,
    raw: dict[str, object],
) -> dict[str, tuple[int, int, bool]]:
    table: object = raw.get("stepper_stallguard")
    if table is None:
        return dict(DEFAULT_STEPPER_STALLGUARD)

    if not isinstance(table, dict):
        gc.logger.warning("stepper_stallguard must be an object. Ignoring StallGuard config.")
        return dict(DEFAULT_STEPPER_STALLGUARD)

    # Start from the built-in defaults; TOML entries below override per motor.
    configs: dict[str, tuple[int, int, bool]] = dict(DEFAULT_STEPPER_STALLGUARD)
    for stepper_name, value in table.items():
        if not isinstance(stepper_name, str):
            gc.logger.warning(
                f"Ignoring invalid stepper key in stallguard config: {stepper_name!r} (must be string)"
            )
            continue

        if not isinstance(value, dict):
            gc.logger.warning(
                f"Ignoring stallguard config for '{stepper_name}': expected object with sgthrs/tcoolthrs/enabled."
            )
            continue

        sgthrs = value.get("sgthrs", -1)  # -1 => missing; rejected by range check below
        tcoolthrs = value.get("tcoolthrs", 0xFFFFF)
        enabled = value.get("enabled", True)

        fields_valid = (
            type(sgthrs) is int
            and type(tcoolthrs) is int
            and isinstance(enabled, bool)
            and 0 <= sgthrs <= 255
            and 0 <= tcoolthrs <= 0xFFFFF
        )

        if not fields_valid:
            gc.logger.warning(
                f"Ignoring invalid stallguard config for '{stepper_name}': {value!r} "
                f"(requires sgthrs:0-255, tcoolthrs:0-0xFFFFF, enabled:bool)."
            )
            continue

        configs[normalizePhysicalStepperBindingName(stepper_name)] = (
            int(sgthrs),
            int(tcoolthrs),
            bool(enabled),
        )

    return configs


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


def _validateServoSpeed(gc: GlobalConfig, name: str, value: object, default: int | None) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 2000:
        return value
    gc.logger.warning(f"Invalid {name}={value!r}; expected int 1-2000 (°/s). Using {default}.")
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
        if "open_speed" in servo_params:
            config.servo_open_speed = _validateServoSpeed(
                gc, "servo.open_speed", servo_params.get("open_speed"), None
            )
        if "close_speed" in servo_params:
            config.servo_close_speed = _validateServoSpeed(
                gc, "servo.close_speed", servo_params.get("close_speed"), None
            )
        if "homing_speed" in servo_params:
            config.servo_homing_speed = _validateServoSpeed(
                gc, "servo.homing_speed", servo_params.get("homing_speed"), None
            )
    elif servo_params is not None:
        gc.logger.warning("Ignoring invalid servo config: expected object.")

    config.stepper_current_overrides = _parseStepperCurrentOverrides(gc, raw)
    config.stepper_stallguard = _parseStepperStallguard(gc, raw)

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
class ChuteCalibrationConfig:
    home_pin_channel: int = DEFAULT_CHUTE_HOME_PIN_CHANNEL
    num_sections: int = DEFAULT_CHUTE_NUM_SECTIONS
    section_width_deg: float = DEFAULT_CHUTE_SECTION_WIDTH_DEG
    first_section_offset_deg: float = DEFAULT_CHUTE_FIRST_SECTION_OFFSET_DEG
    # Legacy fields, still parsed so old machine.toml files keep working and
    # the legacy /settings/chute page round-trips. When the canonical keys
    # above are absent they are derived from these (see loader below).
    first_bin_center: float = DEFAULT_CHUTE_FIRST_BIN_CENTER
    pillar_width_deg: float = DEFAULT_CHUTE_PILLAR_WIDTH_DEG
    endstop_active_high: bool = DEFAULT_CHUTE_ENDSTOP_ACTIVE_HIGH
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
    board_input_aliases: dict[str, int] | None = None,
    board_endstop_active_high: bool | None = None,
) -> ChuteCalibrationConfig:
    raw = machine_specific_params
    if raw is None:
        raw = loadMachineSpecificParams(gc)

    board_default = (
        board_input_aliases.get("chute_home", DEFAULT_CHUTE_HOME_PIN_CHANNEL)
        if board_input_aliases is not None
        else DEFAULT_CHUTE_HOME_PIN_CHANNEL
    )
    default_active_high = (
        board_endstop_active_high
        if board_endstop_active_high is not None
        else DEFAULT_CHUTE_ENDSTOP_ACTIVE_HIGH
    )

    if not isinstance(raw, dict):
        return ChuteCalibrationConfig(home_pin_channel=board_default, endstop_active_high=default_active_high)

    chute_params = raw.get("chute")
    if chute_params is None:
        return ChuteCalibrationConfig(home_pin_channel=board_default, endstop_active_high=default_active_high)
    if not isinstance(chute_params, dict):
        gc.logger.warning("Ignoring invalid chute config: expected object. Using defaults.")
        return ChuteCalibrationConfig(home_pin_channel=board_default, endstop_active_high=default_active_high)

    home_pin_channel_raw = chute_params.get("home_pin_channel")
    if home_pin_channel_raw is None:
        home_pin_channel = board_default
    elif not isinstance(home_pin_channel_raw, int) or isinstance(home_pin_channel_raw, bool):
        gc.logger.warning(
            "Invalid chute.home_pin_channel=%r; using board default %d."
            % (home_pin_channel_raw, board_default)
        )
        home_pin_channel = board_default
    else:
        home_pin_channel = home_pin_channel_raw

    first_bin_center = chute_params.get(
        "first_bin_center", DEFAULT_CHUTE_FIRST_BIN_CENTER
    )
    pillar_width_deg = chute_params.get(
        "pillar_width_deg", DEFAULT_CHUTE_PILLAR_WIDTH_DEG
    )
    endstop_active_high = chute_params.get("endstop_active_high", default_active_high)
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
            f"Invalid chute.endstop_active_high={endstop_active_high!r}; using default {default_active_high}."
        )
        endstop_active_high = default_active_high

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

    num_sections_raw = chute_params.get("num_sections", DEFAULT_CHUTE_NUM_SECTIONS)
    if not isinstance(num_sections_raw, int) or isinstance(num_sections_raw, bool) or num_sections_raw < 1:
        gc.logger.warning(
            f"Invalid chute.num_sections={num_sections_raw!r}; expected int >= 1. "
            f"Using default {DEFAULT_CHUTE_NUM_SECTIONS}."
        )
        num_sections = DEFAULT_CHUTE_NUM_SECTIONS
    else:
        num_sections = num_sections_raw
    section_pitch = 360.0 / num_sections

    # Canonical keys win. When absent, derive from the legacy geometry so an
    # existing machine.toml keeps aiming sensibly until it is recalibrated via
    # the new flow: usable section width = pitch - pillar, and the legacy
    # first_bin_center is treated as the section-0 start offset.
    if "section_width_deg" in chute_params:
        section_width_deg = chute_params.get("section_width_deg")
        if not isinstance(section_width_deg, (int, float)) or isinstance(section_width_deg, bool):
            gc.logger.warning(
                f"Invalid chute.section_width_deg={section_width_deg!r}; deriving from pillar_width_deg."
            )
            section_width_deg = section_pitch - pillar_width_deg
        else:
            section_width_deg = float(section_width_deg)
    else:
        section_width_deg = section_pitch - pillar_width_deg
        gc.logger.info(
            "chute.section_width_deg not set; derived %.3f° from pillar_width_deg. "
            "Run the chute aiming calibration to set it directly." % section_width_deg
        )

    if section_width_deg <= 0 or section_width_deg >= section_pitch:
        gc.logger.warning(
            f"Invalid chute.section_width_deg={section_width_deg!r}; expected 0 < value < "
            f"{section_pitch}. Using default {DEFAULT_CHUTE_SECTION_WIDTH_DEG}."
        )
        section_width_deg = DEFAULT_CHUTE_SECTION_WIDTH_DEG

    if "first_section_offset_deg" in chute_params:
        first_section_offset_deg = chute_params.get("first_section_offset_deg")
        if not isinstance(first_section_offset_deg, (int, float)) or isinstance(first_section_offset_deg, bool):
            gc.logger.warning(
                f"Invalid chute.first_section_offset_deg={first_section_offset_deg!r}; using first_bin_center."
            )
            first_section_offset_deg = first_bin_center
        else:
            first_section_offset_deg = float(first_section_offset_deg)
    else:
        first_section_offset_deg = first_bin_center

    return ChuteCalibrationConfig(
        home_pin_channel=home_pin_channel,
        num_sections=num_sections,
        section_width_deg=section_width_deg,
        first_section_offset_deg=first_section_offset_deg,
        first_bin_center=first_bin_center,
        pillar_width_deg=pillar_width_deg,
        endstop_active_high=endstop_active_high,
        operating_speed_microsteps_per_second=operating_speed_microsteps_per_second,
    )


