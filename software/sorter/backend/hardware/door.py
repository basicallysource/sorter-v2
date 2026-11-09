"""A door on the chute, one a layer.

A piece falls down the chute past each layer's door. A **closed** door catches
it and sends it out to that layer's bins; an **open** door lets it fall past to
the layers below. So to reach a layer, its door is closed and every door above
it is open.

What turns a door differs by machine (a PWM servo on a control board, a serial
servo on a bus, nothing at all), and so do the things that can go wrong, but the
sorting logic asks every door the same few questions. `Door` is those
questions. `ServoMotor` (sorter_interface.py) is the PWM door; the others are in
machine_platform/doors.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Door(ABC):
    #: A door with no servo cannot be opened: it is always shut.
    can_open: bool = True

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether the door can be moved right now."""

    @property
    @abstractmethod
    def is_calibrated(self) -> bool:
        """Whether its open and closed positions are known. A door that is not
        calibrated is never moved."""

    @property
    @abstractmethod
    def stopped(self) -> bool:
        """Whether it has finished moving, however that ended."""

    @property
    def fault(self) -> str | None:
        """Why the door's last move did not end where it was sent, in words for
        the person at the machine, or None if it did."""
        return None

    @abstractmethod
    def open(self) -> bool:
        """Start opening. False if the door refused or cannot."""

    @abstractmethod
    def close(self) -> bool:
        """Start closing. False if the door refused or cannot."""

    @abstractmethod
    def isOpen(self) -> bool: ...

    @abstractmethod
    def isClosed(self) -> bool: ...

    def stop(self) -> None:
        """Let the door go: stop driving it."""

    # A door moves at its opening speed, its closing speed or its standard one.
    # A door with one speed ignores these.
    def apply_open_speed(self) -> None:
        return

    def apply_close_speed(self) -> None:
        return

    def apply_homing_speed(self) -> None:
        return
