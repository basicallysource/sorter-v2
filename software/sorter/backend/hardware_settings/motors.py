"""The machine's stepper motors and every name each one goes by.

The API, the UI, [stepper_direction_inverts] and [stepper_bindings] name a
motor by its role (`name`). The per-motor driver tables
([stepper_current_overrides.*], [stepper_stallguard.*], [stepper_driver.*])
key it by `key`, the board socket it is wired to by default. Existing files
and older builds use those keys, so they stay as they are. Names are mapped to
motors here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class Motor:
    name: str
    label: str
    key: str
    # Names older firmware reported for the same socket; read as `key`.
    aliases: tuple[str, ...] = ()

    @property
    def attr(self) -> str:
        """Its attribute on IRLInterface. The stepper also logs under `key`."""
        return self.key if self.key.endswith("_stepper") else f"{self.key}_stepper"


MOTORS: tuple[Motor, ...] = (
    Motor("c_channel_1", "C-Channel 1", "c_channel_1_rotor", ("first_c_channel_rotor",)),
    Motor("c_channel_2", "C-Channel 2", "c_channel_2_rotor", ("second_c_channel_rotor",)),
    Motor("c_channel_3", "C-Channel 3", "c_channel_3_rotor", ("third_c_channel_rotor",)),
    Motor("carousel", "carousel", "carousel"),
    Motor("chute", "chute", "chute_stepper"),
)

# Another name the API and the UI give a motor, with its label there: the
# classification channel's platter (C4) is driven by the carousel motor.
NAME_ALIASES: dict[str, tuple[str, str]] = {"c_channel_4": ("carousel", "C-Channel 4")}

# Sockets no motor is wired to by default; [stepper_bindings] can move one there.
SPARE_SOCKETS = ("distribution_aux_1", "distribution_aux_2", "distribution_aux_3", "fifth_stepper")

BINDINGS = "stepper_bindings"

_BY_NAME = {motor.name: motor for motor in MOTORS}
_SOCKET_FOR_ALIAS = {alias: motor.key for motor in MOTORS for alias in motor.aliases}
SOCKETS = frozenset({motor.key for motor in MOTORS} | set(_SOCKET_FOR_ALIAS) | set(SPARE_SOCKETS))


def motorNamed(name: str) -> Motor | None:
    """The motor an API or UI name means, aliases included."""
    target = NAME_ALIASES[name][0] if name in NAME_ALIASES else name
    return _BY_NAME.get(target)


def apiNames() -> tuple[str, ...]:
    return tuple(motor.name for motor in MOTORS) + tuple(NAME_ALIASES)


def motorSockets(config: Mapping[str, Any], logger: Any = None) -> dict[str, str]:
    """The board socket each motor is wired to, by motor name: its `key` unless
    [stepper_bindings] moves it."""
    sockets = {motor.name: motor.key for motor in MOTORS}
    table = config.get(BINDINGS)
    if table is None:
        return sockets
    if not isinstance(table, dict):
        _warn(logger, "stepper_bindings must be a table; ignoring it.")
        return sockets
    for name, socket in table.items():
        if name not in _BY_NAME:
            _warn(logger, f"Ignoring stepper_bindings.{name}: no such motor. Expected one of {sorted(_BY_NAME)}.")
            continue
        if not isinstance(socket, str) or socket not in SOCKETS:
            _warn(logger, f"Ignoring stepper_bindings.{name} = {socket!r}: expected one of {sorted(SOCKETS)}.")
            continue
        sockets[name] = _SOCKET_FOR_ALIAS.get(socket, socket)
    return sockets


def _warn(logger: Any, message: str) -> None:
    if logger is not None:
        logger.warning(message)
