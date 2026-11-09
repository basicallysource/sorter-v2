"""The doors on the chute that are not PWM servos: a serial bus servo, a door
with no servo, and a door that cannot be moved. What a door is, and the PWM
one, are in hardware/door.py and hardware/sorter_interface.py.
"""

from __future__ import annotations

import time
from typing import Any

from hardware.door import Door
from hardware.feetech import registers
from hardware.feetech.link import GuardState, NoReply, ServoLink, ServoLinkError
from hardware.feetech.servo import BusServo
from hardware_settings.doors import DoorSetting

# A servo that stopped answering is asked again no more often than this.
RETRY_AFTER_S = 1.0


class FixedDoor(Door):
    """A layer whose door has no servo and is always shut: it catches whatever
    reaches it. On a chute nothing falls out of, that is the bottom layer."""

    can_open = False

    def __init__(self, layer_index: int):
        self.layer_index = layer_index
        self.channel = None

    @property
    def available(self) -> bool:
        return True

    @property
    def is_calibrated(self) -> bool:
        return True

    @property
    def stopped(self) -> bool:
        return True

    def open(self) -> bool:
        return False

    def close(self) -> bool:
        return True

    def isOpen(self) -> bool:
        return False

    def isClosed(self) -> bool:
        return True

    def feedback(self) -> dict[str, Any]:
        return {
            "kind": "fixed",
            "layer_index": self.layer_index,
            "available": True,
            "calibrated": True,
            "is_open": False,
            "error": None,
        }


class MissingDoor(Door):
    """A layer whose door cannot be moved, and why: no servo set up for it, or
    the way to its servo is down."""

    def __init__(self, layer_index: int, error: str, *, servo_id: int | None = None):
        self.layer_index = layer_index
        self.channel = servo_id
        self._error = error

    @property
    def available(self) -> bool:
        return False

    @property
    def is_calibrated(self) -> bool:
        return False

    @property
    def stopped(self) -> bool:
        return True

    @property
    def fault(self) -> str | None:
        return self._error

    def open(self) -> bool:
        return False

    def close(self) -> bool:
        return False

    def isOpen(self) -> bool:
        return False

    def isClosed(self) -> bool:
        return False

    def feedback(self) -> dict[str, Any]:
        return {
            "kind": "servo",
            "layer_index": self.layer_index,
            "servo_id": self.channel,
            "available": False,
            "calibrated": False,
            "is_open": None,
            "error": self._error,
        }


class BusServoDoor(Door):
    """A door turned by a serial bus servo. Every move is a guarded one: a door
    that meets something stops, backs off, lets go and says so in `fault`."""

    def __init__(
        self,
        logger: Any,
        link: ServoLink,
        layer_index: int,
        setting: DoorSetting,
    ):
        assert setting.servo_id is not None
        self._logger = logger
        self._link = link
        self.layer_index = layer_index
        self.channel = setting.servo_id
        self._setting = setting
        self._servo: BusServo | None = None
        self._error: str | None = None
        self._asked_at = 0.0
        self._target: str | None = None  # "open" or "closed": where it was last sent
        self._fault: str | None = None
        self._speeds: dict[str, int | None] = {"open": None, "closed": None, "standard": None}
        self._speed: int | None = None
        self._find()

    # --- who it is ---

    def _find(self) -> None:
        self._asked_at = time.monotonic()
        try:
            self._servo = BusServo.identify(self._link, self.channel)
            self._error = None
        except NoReply:
            self._servo = None
            self._error = f"Servo {self.channel} does not answer. Check its cable and the servo power."
        except ServoLinkError as exc:
            self._servo = None
            self._error = str(exc)

    def _lost(self, exc: Exception) -> None:
        self._servo = None
        self._error = f"Servo {self.channel} stopped answering: {exc}"
        self._asked_at = time.monotonic()
        self._logger.warning(f"Layer {self.layer_index + 1} door: {self._error}")

    @property
    def available(self) -> bool:
        if self._servo is None and time.monotonic() - self._asked_at >= RETRY_AFTER_S:
            self._find()
        return self._servo is not None

    @property
    def is_calibrated(self) -> bool:
        return self._setting.calibrated

    def setSetting(self, setting: DoorSetting) -> None:
        self._setting = setting

    # --- speeds, in degrees a second ---

    def set_motion_speeds(self, open_speed: int | None, close_speed: int | None, homing_speed: int | None) -> None:
        self._speeds = {"open": open_speed, "closed": close_speed, "standard": homing_speed}
        self._speed = homing_speed

    def set_speed_limits(self, _min_speed: int, _max_speed: int) -> None:
        # The PWM firmware's own limits, sent where no standard speed is set:
        # here that is this servo's default speed.
        self._speed = None

    def apply_open_speed(self) -> None:
        self._speed = self._speeds["open"] or self._speeds["standard"]

    def apply_close_speed(self) -> None:
        self._speed = self._speeds["closed"] or self._speeds["standard"]

    def apply_homing_speed(self) -> None:
        self._speed = self._speeds["standard"]

    # --- moving ---

    def _send(self, target: str) -> bool:
        if not self.is_calibrated or not self.available:
            return False
        goal = self._setting.closed if target == "closed" else self._setting.open
        assert self._servo is not None and goal is not None
        try:
            self._servo.move(goal, speed_deg_s=self._speed)
        except ServoLinkError as exc:
            self._lost(exc)
            return False
        self._target = target
        self._fault = None
        return True

    def open(self) -> bool:
        return self._send("open")

    def close(self) -> bool:
        return self._send("closed")

    @property
    def stopped(self) -> bool:
        if self._servo is None or self._target is None:
            return True
        try:
            report = self._servo.state()
        except ServoLinkError as exc:
            self._lost(exc)
            self._fault = self._error
            return True
        if report.busy:
            return False
        where = "closing" if self._target == "closed" else "opening"
        if report.state == GuardState.STALLED:
            self._fault = (
                f"Layer {self.layer_index + 1}'s door met something while {where} and backed off. "
                "Something is in its way."
            )
        elif report.state == GuardState.TIMED_OUT:
            self._fault = f"Layer {self.layer_index + 1}'s door did not finish {where} in time."
        elif report.state == GuardState.LOST:
            self._fault = f"Layer {self.layer_index + 1}'s servo stopped answering while {where}."
        return True

    @property
    def fault(self) -> str | None:
        return self._fault

    def isOpen(self) -> bool:
        return self._target == "open" and self._fault is None

    def isClosed(self) -> bool:
        return self._target == "closed" and self._fault is None

    def stop(self) -> None:
        if self._servo is None:
            return
        try:
            self._servo.release()
        except ServoLinkError as exc:
            self._lost(exc)

    @property
    def enabled(self) -> bool:
        return self._servo is not None

    @enabled.setter
    def enabled(self, value: bool) -> None:
        if not value:
            self.stop()

    def set_name(self, _name: str) -> None:
        return

    def feedback(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "kind": "servo",
            "layer_index": self.layer_index,
            "servo_id": self.channel,
            "available": self._servo is not None,
            "calibrated": self.is_calibrated,
            "closed_position": self._setting.closed,
            "open_position": self._setting.open,
            "is_open": None if self._target is None else self.isOpen(),
            "error": self._error or self._fault,
            "model": None,
            "position": None,
        }
        if self._servo is not None:
            info["model"] = self._servo.model.name
            try:
                present = self._servo.present()
                info["position"] = present.position
                info["volts"] = present.volts
                info["temperature_c"] = present.temperature_c
            except ServoLinkError as exc:
                self._lost(exc)
                info["available"] = False
                info["error"] = self._error
        return info


def setDoorsFor(doors: list[Door], target_layer_index: int) -> None:
    """Set the doors so a piece dropped now lands on the target layer: its door
    shut, every other door that can move open. A door that cannot be moved
    safely (not calibrated, not answering) is left alone."""
    for index, door in enumerate(doors):
        if index == target_layer_index or not door.can_open:
            continue
        if door.available and door.is_calibrated:
            door.apply_open_speed()
            door.open()
    target = doors[target_layer_index]
    if target.available and target.is_calibrated:
        target.apply_close_speed()
        target.close()


def catchingLayer(doors: list[Door]) -> int | None:
    """The layer a piece dropped now would land on: the first shut door from the top."""
    for index, door in enumerate(doors):
        if door.isClosed():
            return index
    return None


def releaseAll(link: ServoLink) -> None:
    """Let every servo on a bus go, watched or not."""
    link.stop(registers.BROADCAST_ID, release=True)
