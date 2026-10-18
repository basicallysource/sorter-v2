"""The layer servos' speeds in °/s, kept in [servo]: opening, closing, and the
standard speed used at start-up, for homing and for jogging.

A speed left unset is the firmware's default. readServoSpeeds is the only
reader (start-up and the routes), saveServoSpeeds the only writer, and
applyServoSpeeds puts them on a servo the same way at start and live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import machine_toml

SERVO = "servo"
SPEEDS = ("open_speed", "close_speed", "homing_speed")
SPEED_RANGE = (1, 2000)
# The firmware's own speed limits for a servo (Servo.cpp), in 0.1°/s: the
# standard speed when none is set.
FIRMWARE_SPEED_LIMITS_TENTHS = (10, 15000)


@dataclass(frozen=True)
class ServoSpeeds:
    open_speed: int | None = None
    close_speed: int | None = None
    homing_speed: int | None = None

    def describe(self) -> str:
        return ", ".join(
            f"{label} {'firmware default' if value is None else f'{value}°/s'}"
            for label, value in (
                ("opening", self.open_speed),
                ("closing", self.close_speed),
                ("standard", self.homing_speed),
            )
        )


def readServoSpeeds(config: Mapping[str, Any] | None = None, logger: Any = None) -> ServoSpeeds:
    if config is None:
        config = machine_toml.read()
    table = config.get(SERVO)
    if not isinstance(table, dict):
        return ServoSpeeds()
    speeds: dict[str, int] = {}
    for key in SPEEDS:
        if key not in table:
            continue
        value = table[key]
        if type(value) is int and SPEED_RANGE[0] <= value <= SPEED_RANGE[1]:
            speeds[key] = value
        elif logger is not None:
            logger.warning(
                f"Ignoring servo.{key} = {value!r}: expected a whole number of °/s from "
                f"{SPEED_RANGE[0]} to {SPEED_RANGE[1]}. Using the firmware default."
            )
    return ServoSpeeds(**speeds)


def saveServoSpeeds(changes: Mapping[str, int | None]) -> ServoSpeeds:
    """Save some speeds: None goes back to the firmware default, and a number
    is held to SPEED_RANGE. Raises ValueError for anything else."""
    for key, value in changes.items():
        if key not in SPEEDS:
            raise ValueError(f"There is no servo speed '{key}'.")
        if value is not None and type(value) is not int:
            raise ValueError(f"{key} must be a whole number of °/s or null.")
    with machine_toml.edit() as config:
        table = config.get(SERVO)
        if not isinstance(table, dict):
            table = {}
            config[SERVO] = table
        for key, value in changes.items():
            if value is None:
                table.pop(key, None)
            else:
                table[key] = max(SPEED_RANGE[0], min(SPEED_RANGE[1], value))
    return readServoSpeeds(config)


def applyServoSpeeds(servo: Any, speeds: ServoSpeeds) -> None:
    """Give a servo its speeds and put it at the standard one. Opening and
    closing apply theirs before each such move."""
    if not hasattr(servo, "set_motion_speeds"):
        return
    servo.set_motion_speeds(speeds.open_speed, speeds.close_speed, speeds.homing_speed)
    if speeds.homing_speed is None:
        # The firmware keeps the last speed it was given until the board itself
        # restarts, so "unset" is sent as its default, or it would stay at
        # whatever this or an earlier run left it at.
        servo.set_speed_limits(*FIRMWARE_SPEED_LIMITS_TENTHS)
    else:
        servo.apply_homing_speed()
