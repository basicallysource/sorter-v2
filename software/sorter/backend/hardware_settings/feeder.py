"""How the C-channels' motors (1 to 3, the feeder, and 4, the classification
channel) turn their channels.

A geared machine turns each C-channel through a 130:12 gear. A direct-drive
one has each motor turn its channel itself. machine.toml says which; it is
set by hand, not from the UI:

    [feeder]
    drive = "direct"

No [feeder] table is the drive the machine's generation is built with
(hardware_settings/generation.py): the geared feeder on a Sorter V2. A board made for one feeder (the
Sorter V3's, machine_platform/control_board.py) writes its drive down the
first time the hardware starts on it, as it does its kind of chute.

The C-channels' motor speeds and accelerations were tuned on the geared ones,
in motor microsteps. On another drive their built-in defaults are scaled so the
channels turn just as fast (`FeederDrive.motorRate`), and the drive can give
its motors other built-in settings, current and direction (`stepper_defaults`,
which steppers.py layers over its own). A value saved in machine.toml is
always taken as it is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import machine_toml

from .generation import machineGeneration

FEEDER = "feeder"
GEARED = "geared"
DIRECT = "direct"
# Motor turns per channel turn on the geared feeder, the one every built-in
# feeder speed was tuned on.
GEARED_RATIO = 130.0 / 12.0
# The motors (hardware_settings.motors names) that turn the feeder's channels,
# and with the classification channel's (C4, named carousel) every C-channel.
FEEDER_MOTORS = ("c_channel_1", "c_channel_2", "c_channel_3")
C_CHANNEL_MOTORS = (*FEEDER_MOTORS, "carousel")


@dataclass(frozen=True)
class FeederDrive:
    name: str
    # Motor turns per channel turn.
    gear_ratio: float
    # Built-in settings of each feeder motor on this drive, by motor name, over
    # the motor's own (steppers.MOTOR_DEFAULTS). Its direction included: a gear
    # turns the channel the other way from its motor.
    stepper_defaults: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)

    def motorRate(self, geared_rate: float) -> int:
        """A motor speed or acceleration tuned on the geared feeder, for this
        drive: the one that turns the channel as fast."""
        return max(1, round(geared_rate * self.gear_ratio / GEARED_RATIO))

    def motorDegrees(self, geared_motor_deg: float) -> float:
        """A motor angle tuned on the geared channels, for this drive: the one
        that turns the channel as far."""
        return geared_motor_deg * self.gear_ratio / GEARED_RATIO


DRIVES: dict[str, FeederDrive] = {
    GEARED: FeederDrive(GEARED, GEARED_RATIO),
    # With no gear each motor takes its channel's whole load, and C1's motor
    # sits the other way round from the geared feeder's.
    DIRECT: FeederDrive(
        DIRECT,
        1.0,
        {
            "c_channel_1": {"irun": 16, "inverted": True},
            "c_channel_2": {"irun": 16},
            "c_channel_3": {"irun": 16},
            "carousel": {"irun": 16},
        },
    ),
}


def driveSaved(config: Mapping[str, Any] | None = None) -> bool:
    """Whether machine.toml names the feeder's drive."""
    if config is None:
        config = machine_toml.read()
    table = config.get(FEEDER)
    return isinstance(table, dict) and "drive" in table


def saveFeederDrive(name: str) -> FeederDrive:
    """Write down the feeder's drive. Raises ValueError for an unknown one."""
    if name not in DRIVES:
        raise ValueError(f"A feeder's drive is one of {', '.join(sorted(DRIVES))}, not {name!r}.")
    with machine_toml.edit() as config:
        table = config.get(FEEDER)
        if not isinstance(table, dict):
            table = {}
            config[FEEDER] = table
        table["drive"] = name
    return DRIVES[name]


def feederDrive(config: Mapping[str, Any] | None = None, logger: Any = None) -> FeederDrive:
    """The machine's feeder drive: the one saved, else its generation's. An
    unknown one is taken as geared, with a warning."""
    if config is None:
        config = machine_toml.read()
    table = config.get(FEEDER)
    built_with = machineGeneration(config).feeder_drive
    name = table.get("drive", built_with) if isinstance(table, dict) else built_with
    drive = DRIVES.get(name) if isinstance(name, str) else None
    if drive is None:
        if logger is not None:
            logger.warning(
                f"Ignoring {FEEDER}.drive = {name!r}: expected one of {', '.join(sorted(DRIVES))}. "
                "Taking the feeder as geared."
            )
        return DRIVES[GEARED]
    return drive
