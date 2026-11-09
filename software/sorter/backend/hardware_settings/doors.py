"""The layer doors' serial servos, kept in [servo]: which servo turns each
layer's door, and the two positions it turns between.

    [servo]
    backend = "bus"

    [[servo.channels]]      # one entry a layer, the top layer first
    id = 3                  # the servo's ID on the bus
    closed = 641            # where the door is shut, in the servo's own counts
    open = 362              # where it is out of the way

A layer with no `id` has no servo. A door with an `id` and no positions is not
calibrated, and a door that is not calibrated is never moved.

readDoorSettings is the only reader and saveDoorSetting the only writer of
these positions. The PWM servos' angles live elsewhere (bin_layout_store.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import machine_toml

SERVO = "servo"
BACKEND_BUS = "bus"
_KEEP: Any = object()


@dataclass(frozen=True)
class DoorSetting:
    servo_id: int | None = None
    closed: int | None = None
    open: int | None = None

    @property
    def calibrated(self) -> bool:
        return self.servo_id is not None and self.closed is not None and self.open is not None


def servoBackend(config: Mapping[str, Any] | None = None) -> str | None:
    """The servo backend machine.toml names, or None if it names none."""
    if config is None:
        config = machine_toml.read()
    table = config.get(SERVO)
    backend = table.get("backend") if isinstance(table, dict) else None
    return backend if isinstance(backend, str) else None


def readDoorSettings(config: Mapping[str, Any] | None = None, logger: Any = None) -> list[DoorSetting]:
    """One setting a layer, the top layer first, for as many layers as are saved."""
    if config is None:
        config = machine_toml.read()
    table = config.get(SERVO)
    channels = table.get("channels") if isinstance(table, dict) else None
    if not isinstance(channels, list):
        return []
    settings: list[DoorSetting] = []
    for index, raw in enumerate(channels):
        if not isinstance(raw, dict):
            settings.append(DoorSetting())
            continue
        servo_id = raw.get("id")
        if servo_id is not None and not (_isCount(servo_id) and 1 <= servo_id <= 253):
            _warn(logger, f"Ignoring servo.channels[{index}].id = {servo_id!r}: a servo's ID is 1 to 253.")
            servo_id = None
        positions: dict[str, int | None] = {}
        for key in ("closed", "open"):
            value = raw.get(key)
            if value is not None and not _isCount(value):
                _warn(logger, f"Ignoring servo.channels[{index}].{key} = {value!r}: expected a whole number.")
                value = None
            positions[key] = value
        settings.append(DoorSetting(servo_id=servo_id, closed=positions["closed"], open=positions["open"]))
    return settings


def saveDoorSetting(
    layer_index: int,
    *,
    servo_id: int | None = _KEEP,
    closed: int | None = _KEEP,
    open: int | None = _KEEP,
) -> list[DoorSetting]:
    """Change one layer's door: its servo, its positions, or both. What is not
    given stays as saved; None takes it out. Giving a door another servo takes
    its positions out too, as they were the other servo's. Names the bus as the
    servo backend, since only its servos are set up this way."""
    if layer_index < 0:
        raise ValueError("A layer is counted from 0.")
    for label, value in (("closed", closed), ("open", open)):
        if value is not _KEEP and value is not None and not _isCount(value):
            raise ValueError(f"The {label} position must be a whole number of the servo's counts.")
    if servo_id is not _KEEP and servo_id is not None and not (_isCount(servo_id) and 1 <= servo_id <= 253):
        raise ValueError("A servo's ID is 1 to 253.")
    with machine_toml.edit() as config:
        table = config.get(SERVO)
        if not isinstance(table, dict):
            table = {}
            config[SERVO] = table
        table["backend"] = BACKEND_BUS
        channels = table.get("channels")
        if not isinstance(channels, list):
            channels = []
            table["channels"] = channels
        while len(channels) <= layer_index:
            channels.append({})
        entry = channels[layer_index]
        if not isinstance(entry, dict):
            entry = {}
            channels[layer_index] = entry
        if servo_id is not _KEEP and servo_id != entry.get("id"):
            _set(entry, "id", servo_id)
            entry.pop("closed", None)
            entry.pop("open", None)
        if closed is not _KEEP:
            _set(entry, "closed", closed)
        if open is not _KEEP:
            _set(entry, "open", open)
        # A servo turns one door: taking it for this layer takes it from any other.
        if servo_id is not _KEEP and servo_id is not None:
            for other_index, other in enumerate(channels):
                if other_index != layer_index and isinstance(other, dict) and other.get("id") == servo_id:
                    for key in ("id", "closed", "open"):
                        other.pop(key, None)
    return readDoorSettings(config)


def _set(entry: dict, key: str, value: Any) -> None:
    if value is None:
        entry.pop(key, None)
    else:
        entry[key] = int(value)


def _isCount(value: Any) -> bool:
    return type(value) is int and value >= 0


def _warn(logger: Any, message: str) -> None:
    if logger is not None:
        logger.warning(message)
