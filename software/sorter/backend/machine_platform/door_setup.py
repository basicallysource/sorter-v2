"""Setting up the serial servos that turn the layer doors: which servo is on
which door, and the two positions each door turns between.

**Which servo is which.** Every new servo answers to ID 1, and two servos with
one ID answer over each other, so a scan says three things apart: nothing there,
one servo, several sharing an ID. A servo is matched to its door without moving
anything: every servo is let go, the person turns one door by hand, and the
servo whose position changes is that door's (`HandWatch`). A servo still on the
factory ID is given an ID of its own when it gets a door (`DOOR_ID_BASE` plus
the layer's number), so the next new servo plugged into the chain is alone on ID 1.

**Where a door stops.** A door turns between two things it cannot pass: shut
across the chute, and open against its wall. `findTravel` finds both with the
bus's slow probe, which creeps toward each and stops the moment the servo is
held, never pushing hard. The two positions kept are a little inside the two
stops, so the servo does not lean on them in daily use. Which of the two is
"closed" cannot be told from the servo: the person is shown one and asked.

A door can also be set by hand, with nothing moving: hold it where it should
be and mark the place (`readPosition`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from hardware.feetech import registers
from hardware.feetech.link import GuardReport, GuardState, ServoLink, ServoLinkError
from hardware.feetech.servo import BusServo, FoundServo, scan

# A servo given a door gets this plus the layer's number (the top layer is 1)
# as its ID, if it still has the factory one.
DOOR_ID_BASE = 10
# How far inside each stop a door's two positions are kept, in degrees.
STOP_MARGIN_DEG = 3.0
# A door that turns less than this between its stops is not a door that works.
SMALLEST_TRAVEL_DEG = 15.0
# Turning a door by hand moves its servo at least this far, in degrees.
HAND_MOVE_DEG = 5.0
PROBE_TIMEOUT_S = 40.0


class DoorSetupError(Exception):
    """Something the person at the machine has to know to go on."""


@dataclass(frozen=True)
class Travel:
    """Where a door stops at each end, and the two positions to keep, in counts."""

    low_stop: int
    high_stop: int
    low: int
    high: int
    degrees: float
    # An end where the probe met nothing before the servo's own limit.
    open_ended: tuple[str, ...] = ()


def scanBus(link: ServoLink) -> list[FoundServo]:
    return scan(link)


def doorIdFor(layer_index: int) -> int:
    return DOOR_ID_BASE + layer_index + 1


def claimServo(link: ServoLink, servo_id: int, layer_index: int) -> BusServo:
    """The servo answering to `servo_id`, ready to be a layer's door. One still
    on the factory ID is given the layer's own ID first, kept through power off."""
    servo = _identify(link, servo_id)
    if servo_id != registers.FACTORY_ID:
        return servo
    try:
        return servo.set_id(doorIdFor(layer_index))
    except ValueError as exc:
        raise DoorSetupError(
            f"This servo is new and needs a number of its own, but {doorIdFor(layer_index)} is taken: {exc} "
            "Unplug the servo that has it, or give that one to this layer instead."
        ) from None
    except ServoLinkError as exc:
        raise DoorSetupError(f"The servo did not take its new number: {exc}") from None


def readPosition(link: ServoLink, servo_id: int) -> int:
    """Where the servo is now, for marking a door's place by hand."""
    try:
        return _identify(link, servo_id).present().position
    except ServoLinkError as exc:
        raise DoorSetupError(str(exc)) from None


class HandWatch:
    """Finds the servo on the door a person turns by hand. Every servo is let
    go when the watch starts; `moved()` is the one that has turned since."""

    def __init__(self, link: ServoLink, servos: list[FoundServo]):
        self._servos: dict[int, BusServo] = {}
        self._start: dict[int, int] = {}
        for found in servos:
            if found.state != "ok":
                continue
            try:
                servo = BusServo.identify(link, found.servo_id)
                servo.release()
                self._servos[found.servo_id] = servo
                self._start[found.servo_id] = servo.present().position
            except ServoLinkError:
                continue
        if not self._servos:
            raise DoorSetupError("No servo answers, so there is no door to find. Scan first.")

    def positions(self) -> dict[int, float]:
        """How far each servo has turned since the watch started, in degrees."""
        turned: dict[int, float] = {}
        for servo_id, servo in self._servos.items():
            try:
                counts = abs(servo.present().position - self._start[servo_id])
            except ServoLinkError:
                continue
            turned[servo_id] = round(servo.series.degrees(counts), 1)
        return turned

    def moved(self) -> int | None:
        """The servo that has been turned by hand, once exactly one has."""
        turned = [servo_id for servo_id, degrees in self.positions().items() if degrees >= HAND_MOVE_DEG]
        return turned[0] if len(turned) == 1 else None


def findTravel(
    link: ServoLink,
    servo_id: int,
    *,
    said: Callable[[str], None] = lambda _message: None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Travel:
    """Find where the door stops at both ends, slowly, and leave it let go."""
    servo = _identify(link, servo_id)
    series = servo.series
    try:
        low_limit, high_limit = servo.limits()
        if not 0 <= low_limit < high_limit <= series.max_raw:
            low_limit, high_limit = 0, series.max_raw
        open_ended: list[str] = []
        stops: dict[int, int] = {}
        for direction, limit, name in ((-1, low_limit, "low"), (1, high_limit, "high")):
            said("Turning the door slowly one way until it stops" if direction < 0 else "And slowly the other way")
            servo.probe(direction, limit=limit)
            report = _waitProbe(servo, cancelled)
            if report.state == GuardState.CONTACT:
                stops[direction] = report.mark
            elif report.state == GuardState.NO_CONTACT:
                stops[direction] = limit
                open_ended.append(name)
            elif report.state == GuardState.LOST:
                raise DoorSetupError(f"Servo {servo_id} stopped answering while the door was turning.")
            else:
                raise DoorSetupError("The search for the door's stop was interrupted.")
    except ServoLinkError as exc:
        raise DoorSetupError(str(exc)) from None
    finally:
        try:
            servo.release()
        except ServoLinkError:
            pass
    low_stop, high_stop = stops[-1], stops[1]
    margin = series.counts(STOP_MARGIN_DEG)
    degrees = series.degrees(high_stop - low_stop)
    if degrees < SMALLEST_TRAVEL_DEG:
        raise DoorSetupError(
            f"The door only turns {degrees:.0f} degrees between its stops. Something is holding it, "
            "or the servo is not driving the door. Check that it turns freely by hand."
        )
    return Travel(
        low_stop=low_stop,
        high_stop=high_stop,
        low=low_stop + margin,
        high=high_stop - margin,
        degrees=round(degrees, 1),
        open_ended=tuple(open_ended),
    )


def moveGuarded(link: ServoLink, servo_id: int, goal: int, *, timeout_s: float = 10.0) -> GuardReport:
    """Send a servo to a position through the guard and wait for how it ends."""
    try:
        servo = _identify(link, servo_id)
        servo.move(goal)
        return servo.wait(timeout_s)
    except ServoLinkError as exc:
        raise DoorSetupError(str(exc)) from None


def nudged(link: ServoLink, servo_id: int, position: int, degrees: float) -> int:
    """`position` moved by a few degrees, held inside what the servo can reach."""
    series = _identify(link, servo_id).series
    return series.clamp(position + series.counts(degrees))


def _identify(link: ServoLink, servo_id: int) -> BusServo:
    try:
        return BusServo.identify(link, servo_id)
    except ServoLinkError as exc:
        raise DoorSetupError(str(exc)) from None


def _waitProbe(servo: BusServo, cancelled: Callable[[], bool]) -> GuardReport:
    deadline = time.monotonic() + PROBE_TIMEOUT_S
    report = servo.state()
    while report.busy:
        if cancelled() or time.monotonic() > deadline:
            servo.release()
            return servo.state()
        time.sleep(0.05)
        report = servo.state()
    return report
