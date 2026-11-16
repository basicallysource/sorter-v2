"""Finding the chute's home, on a switch or on a magnet.

Both use the board's own homing: the firmware runs the motor at a speed until
an input reads a given level, stops it at once and makes that step 0
(Stepper::stepgen_tick).

**On a switch** (a chute that turns between two stops): run toward the switch
until it trips, then back away to the first bin.

**On a magnet** (a chute that turns without limit): the magnet passes a sensor
once a turn, and the sensor reads it over a stretch of turning, not at one
point. How wide that stretch is depends on the sensor: a hall sensor board with
a pot reads a magnet from further off the more sensitive it is set, and even a
finely set one reads it for a while. Home is the middle of the stretch, which is
where the magnet is however the sensor is set, so the bins are where the
machine's design puts them.

Each edge is found slowly and from outside the stretch, so both are read the
same way. A fast pass finds the magnet; the chute backs out and crawls onto its
upper edge, which the board makes step 0. Then it runs on through and out the
far side, and crawls back onto the lower edge, counting the steps from the
upper one. Home is halfway between. A position check (position_check.py)
finds the upper edge again the same way; Chute.home_edge_steps says where it is
from home.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chute import Chute

# Homing runs toward lower angles; the sign is the direction.
HOME_SPEED_MICROSTEPS_PER_SEC = -1000
HOME_TIMEOUT_MS = 15000

# On a magnet: the fast pass and the crawl, in the same direction.
MAGNET_SEEK_SPEED = -2000
MAGNET_CRAWL_SPEED = -300
# How far to back out of the stretch the sensor reads the magnet over before
# each crawl, in chute degrees.
MAGNET_CLEARANCE_DEG = 6.0
# The widest that stretch can be. A sensitive sensor reads the magnet over tens
# of degrees, and homing takes its middle all the same; one that reads it over
# most of a turn is not reading the magnet.
MAGNET_WINDOW_MAX_DEG = 240.0
MAGNET_TOO_WIDE = (
    "The home sensor reads the magnet over more than two thirds of a turn, so it cannot say where the "
    "magnet is. Check its wiring, and that its light goes off with the magnet away."
)
# A magnet not found in this much turning is not there.
MAGNET_SEARCH_DEG = 450.0
# The firmware can report "stopped" before a run it was just given starts.
START_GRACE_S = 0.3
POLL_S = 0.005


def _fail(chute: "Chute", reason: str) -> bool:
    """Log why homing stopped and keep it for the person who asked for it
    (Chute.home_failure)."""
    chute.logger.error(f"Chute: {reason}")
    chute.home_failure = reason
    return False


def homeOnSwitch(chute: "Chute") -> bool:
    chute.logger.info("Chute: homing on its switch")
    pos_before = chute.current_angle
    raw_before = chute.raw_endstop_active
    chute.stepper.home(
        HOME_SPEED_MICROSTEPS_PER_SEC,
        chute.home_pin,
        home_pin_active_high=chute.endstop_active_high,
    )
    start = time.monotonic()
    polls = 0
    while not chute.stepper.stopped:
        polls += 1
        if (time.monotonic() - start) * 1000 > HOME_TIMEOUT_MS:
            chute.logger.error(
                f"Chute: homing timed out after {HOME_TIMEOUT_MS}ms "
                f"(polls={polls}, moved={chute.current_angle - pos_before:.2f}°, "
                f"endstop raw={chute.raw_endstop_active} triggered={chute.endstop_triggered})"
            )
            chute.home_failure = (
                f"The chute turned for {HOME_TIMEOUT_MS / 1000:g} s without reaching its home switch. "
                "Check the switch and its wiring."
            )
            return False
        time.sleep(0.01)
    elapsed_ms = (time.monotonic() - start) * 1000
    if not chute.endstop_triggered:
        chute.logger.warning(
            "Chute: homing stopped before the endstop triggered "
            f"(elapsed={elapsed_ms:.0f}ms, polls={polls}, "
            f"moved={chute.current_angle - pos_before:.2f}° from {pos_before:.2f}°, "
            f"endstop raw {raw_before}->{chute.raw_endstop_active} "
            f"(active_high={chute.endstop_active_high}, triggered={chute.endstop_triggered})). "
            "polls<=1 / moved~0 means the firmware reported stopped before motion began (race); "
            "large moved means it travelled without the switch ever firing."
        )
        chute.home_failure = (
            "The chute stopped before its home switch was pressed. The switch may not be making good "
            "contact with the chute: try moving it closer."
        )
        return False
    if not chute.backoffToFirstBin():
        chute.home_failure = "The chute found its home switch but did not turn back to bin 1."
        return False
    return True


def homeOnMagnet(chute: "Chute") -> bool:
    """Make the middle of the stretch the sensor reads the magnet over home,
    and turn the chute there."""
    chute.logger.info("Chute: homing on the middle of its magnet")
    if not _findUpperEdge(chute):
        return False
    if not _runOutOfMagnet(chute, MAGNET_SEEK_SPEED):
        return _fail(chute, MAGNET_TOO_WIDE)
    if not _moveBy(chute, -MAGNET_CLEARANCE_DEG):
        return False
    # The edge is somewhere between here and the upper one, where the count is 0.
    stepper = chute.stepper
    back_to_upper_deg = stepper.degrees_for_microsteps(abs(stepper.position)) / chute.gear_ratio
    lower_edge = _crawlOntoEdge(chute, -MAGNET_CRAWL_SPEED, within_deg=back_to_upper_deg + MAGNET_CLEARANCE_DEG)
    if lower_edge is None:
        return _fail(
            chute,
            "The home sensor lost the magnet on the slow approach from its far side. Check that the "
            "sensor is held firmly and its wiring.",
        )
    # The count ran from the upper edge until the board zeroed it on the lower
    # one, where the chute now stands. Home is halfway back up.
    width = abs(lower_edge)
    half = int(round(width / 2))
    stepper.position = stepper.position - half
    chute.home_edge_steps = half
    width_deg = stepper.degrees_for_microsteps(width) / chute.gear_ratio
    chute.magnet_window_deg = round(width_deg, 2)
    chute.logger.info(
        f"Chute: the home sensor reads the magnet over {width_deg:.2f}° ({width} µsteps); home is its middle"
    )
    if chute.moveToAngleBlocking(0.0, timeout_buffer_ms=1500) is None:
        return _fail(chute, "The chute found its magnet but did not turn to its middle.")
    return True


def _findUpperEdge(chute: "Chute") -> bool:
    """Crawl onto the magnet's upper edge from above, and stand there as step 0."""
    if chute.endstop_triggered:
        # Already on the magnet: the firmware would stop at once, somewhere on
        # it. Leave the way a search arrives, then clear it.
        if not _runUntil(chute, -MAGNET_SEEK_SPEED, active=False, within_deg=MAGNET_WINDOW_MAX_DEG):
            return _fail(chute, MAGNET_TOO_WIDE)
        if not _moveBy(chute, MAGNET_CLEARANCE_DEG):
            return False
    if not _runUntil(chute, MAGNET_SEEK_SPEED, active=True, within_deg=MAGNET_SEARCH_DEG):
        return _fail(
            chute,
            "No magnet passed the home sensor in more than a full turn. "
            "Check that the sensor is plugged in, that the magnet is fitted and that the chute turns.",
        )
    if not _runUntil(chute, -MAGNET_CRAWL_SPEED, active=False, within_deg=MAGNET_WINDOW_MAX_DEG):
        return _fail(chute, MAGNET_TOO_WIDE)
    if not _moveBy(chute, MAGNET_CLEARANCE_DEG):
        return False
    if not _runUntil(chute, MAGNET_CRAWL_SPEED, active=True, within_deg=MAGNET_CLEARANCE_DEG * 4):
        return _fail(
            chute,
            "The home sensor lost the magnet on the slow last approach. Check that the sensor is "
            "held firmly and its wiring.",
        )
    return True


def measureTurn(chute: "Chute") -> float | None:
    """How many motor turns one turn of this chute takes, from the magnet's
    upper edge round to the same edge. The chute is left needing a home. None
    if the magnet did not come round.

    A chute that never unwinds adds up whatever its ratio is off by, turn after
    turn, so this is read to a microstep or two. A first pass at speed gives the
    ratio roughly (it only sees the edge between two readings); then the chute
    goes almost a full turn by that ratio and crawls onto the edge, and the
    step count just before the firmware zeroes it is the turn."""
    rough = _roughTurn(chute)
    if rough is None:
        chute.logger.error("Chute: the magnet did not come round while measuring a turn.")
        return None
    as_built = chute.gear_ratio
    chute.setGearRatio(rough)
    try:
        if not _findUpperEdge(chute):
            return None
        # Homing runs toward lower angles: on through the magnet and round, to
        # stop a little short of the edge it started from.
        if not _moveBy(chute, -(360.0 - 2 * MAGNET_CLEARANCE_DEG)):
            return None
        steps = _crawlOntoEdge(chute)
    finally:
        chute.setGearRatio(as_built)
        chute.markUnhomed("its turn was measured")
    if steps is None:
        chute.logger.error("Chute: lost the magnet while measuring a turn.")
        return None
    steps = abs(steps)
    ratio = steps / chute.stepper.total_steps_per_rev
    chute.logger.info(f"Chute: one turn is {steps} µsteps, {ratio:.4f} motor turns")
    return ratio


def _roughTurn(chute: "Chute") -> float | None:
    """The ratio to a part in a thousand: the count between two passes of the
    same edge of the magnet's window, seen at speed."""
    stepper = chute.stepper
    speed = abs(MAGNET_SEEK_SPEED)
    chute.setSpeed(speed)
    deadline = time.monotonic() + _secondsFor(chute, MAGNET_SEARCH_DEG + MAGNET_WINDOW_MAX_DEG, speed) + 2.0
    # Away from home's edge, round, into the window from its far side and out of
    # it again: each time the sensor stops reading the magnet is the same edge.
    edges: list[int] = []
    was_active = chute.endstop_triggered
    if not stepper.move_at_speed(speed):
        return None
    try:
        while time.monotonic() < deadline and len(edges) < 2:
            position = stepper.position
            active = chute.endstop_triggered
            if was_active and not active:
                edges.append(position)
            was_active = active
            time.sleep(POLL_S)
    finally:
        stepper.move_at_speed(0, force=True)
    if len(edges) < 2 or edges[1] == edges[0]:
        return None
    return abs(edges[1] - edges[0]) / stepper.total_steps_per_rev


def _crawlOntoEdge(
    chute: "Chute", speed: int = MAGNET_CRAWL_SPEED, within_deg: float = MAGNET_CLEARANCE_DEG * 6
) -> int | None:
    """Crawl at `speed` onto the magnet's edge the way homing does, and return
    the step count the chute had when it got there: the firmware zeroes it at
    the edge, so it is the last one read before that, carried on by the
    distance the chute goes between two readings."""
    stepper = chute.stepper
    stepper.home(speed, chute.home_pin, home_pin_active_high=chute.endstop_active_high)
    started = time.monotonic()
    give_up_after = _secondsFor(chute, within_deg, speed) + 1.0
    last: int | None = None
    reads = 0
    while True:
        elapsed = time.monotonic() - started
        if stepper.stopped and elapsed >= START_GRACE_S:
            break
        if elapsed > give_up_after:
            stepper.move_at_speed(0, force=True)
            return None
        position = stepper.position
        reads += 1
        if position != 0:
            last = position
    if last is None or not chute.endstop_triggered:
        return None
    # The chute went on for part of a reading's interval after the last one
    # read: half of it, on average, in the direction it crawled.
    crawled_s = time.monotonic() - started
    between_reads = abs(speed) * crawled_s / reads
    return int(round(last + math.copysign(between_reads / 2, speed)))


def _secondsFor(chute: "Chute", chute_degrees: float, speed: int) -> float:
    microsteps = chute.stepper.microsteps_for_degrees(chute_degrees * chute.gear_ratio)
    return abs(microsteps) / max(1, abs(speed))


def _runUntil(chute: "Chute", speed: int, *, active: bool, within_deg: float) -> bool:
    """Run at `speed` until the home sensor reads active (or stops reading it),
    giving up after `within_deg` of turning. The firmware zeroes the step count
    where it stops."""
    level = chute.endstop_active_high if active else not chute.endstop_active_high
    chute.stepper.home(speed, chute.home_pin, home_pin_active_high=level)
    started = time.monotonic()
    give_up_after = _secondsFor(chute, within_deg, speed) + 1.0
    while True:
        elapsed = time.monotonic() - started
        if chute.stepper.stopped and elapsed >= START_GRACE_S:
            break
        if elapsed > give_up_after:
            chute.stepper.move_at_speed(0, force=True)
            return False
        time.sleep(POLL_S)
    return chute.endstop_triggered == active


def _runOutOfMagnet(chute: "Chute", speed: int) -> bool:
    """Run at `speed` until the home sensor stops reading the magnet, then stop.
    Unlike the board's homing this keeps the step count, so the edge the chute
    comes back onto is counted from the one it set out from. False if the
    sensor still reads the magnet after MAGNET_WINDOW_MAX_DEG of turning."""
    stepper = chute.stepper
    chute.setSpeed(abs(speed))
    give_up_at = time.monotonic() + _secondsFor(chute, MAGNET_WINDOW_MAX_DEG, speed) + 1.0
    if not stepper.move_at_speed(speed):
        return False
    try:
        while chute.endstop_triggered:
            if time.monotonic() > give_up_at:
                return False
            time.sleep(POLL_S)
    finally:
        stepper.move_at_speed(0, force=True)
        stopping_until = time.monotonic() + 3.0
        while not stepper.stopped and time.monotonic() < stopping_until:
            time.sleep(POLL_S)
    return True


def _moveBy(chute: "Chute", chute_degrees: float) -> bool:
    """Turn the chute by this much, at its operating speed, and wait."""
    chute.setSpeed(chute.operating_speed_microsteps_per_second)
    motor_degrees = chute_degrees * chute.gear_ratio
    timeout_ms = chute.stepper.estimateMoveDegreesMs(
        motor_degrees, max_speed=chute.operating_speed_microsteps_per_second
    ) + 1500
    if not chute.stepper.move_degrees_blocking(motor_degrees, timeout_ms=timeout_ms):
        return _fail(chute, f"A {chute_degrees:g}° move while homing did not finish.")
    return True
