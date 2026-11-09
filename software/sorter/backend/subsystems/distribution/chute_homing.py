"""Finding the chute's home, on a switch or on a magnet.

Both use the board's own homing: the firmware runs the motor at a speed until
an input reads a given level, stops it at once and makes that step 0
(Stepper::stepgen_tick).

**On a switch** (a chute that turns between two stops): run toward the switch
until it trips, then back away to the first bin.

**On a magnet** (a chute that turns without limit): the magnet passes a sensor
once a turn and reads active over a window some degrees wide, so home is one
edge of that window, always found from the same side and slowly. A fast pass
finds the magnet; the chute backs out of it and comes back at a crawl, and that
stop is 0. It is the same edge a position check finds (position_check.py),
which approaches it the same way.
"""

from __future__ import annotations

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
# How far to back out of the magnet's window before the crawl, in chute degrees.
MAGNET_CLEARANCE_DEG = 6.0
# The widest a magnet's window can be: leaving it takes no longer than this.
MAGNET_WINDOW_MAX_DEG = 90.0
# A magnet not found in this much turning is not there.
MAGNET_SEARCH_DEG = 450.0
# The firmware can report "stopped" before a run it was just given starts.
START_GRACE_S = 0.3
POLL_S = 0.005


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
        return False
    return chute.backoffToFirstBin()


def homeOnMagnet(chute: "Chute") -> bool:
    chute.logger.info("Chute: homing on its magnet")
    if chute.endstop_triggered:
        # Already inside the window: the firmware would stop at once, somewhere
        # in it. Leave the way a search arrives, then clear it.
        if not _runUntil(chute, -MAGNET_SEEK_SPEED, active=False, within_deg=MAGNET_WINDOW_MAX_DEG):
            chute.logger.error(
                "Chute: the home sensor reads active however far the chute turns. "
                "Check the sensor's wiring and its polarity setting."
            )
            return False
        if not _moveBy(chute, MAGNET_CLEARANCE_DEG):
            return False
    if not _runUntil(chute, MAGNET_SEEK_SPEED, active=True, within_deg=MAGNET_SEARCH_DEG):
        chute.logger.error(
            "Chute: no magnet passed the home sensor in more than a full turn. "
            "Check that the sensor is plugged in, that the magnet is fitted and that the chute turns."
        )
        return False
    if not _runUntil(chute, -MAGNET_CRAWL_SPEED, active=False, within_deg=MAGNET_WINDOW_MAX_DEG):
        chute.logger.error("Chute: could not back out of the magnet after finding it.")
        return False
    if not _moveBy(chute, MAGNET_CLEARANCE_DEG):
        return False
    if not _runUntil(chute, MAGNET_CRAWL_SPEED, active=True, within_deg=MAGNET_CLEARANCE_DEG * 4):
        chute.logger.error("Chute: lost the magnet on the slow approach.")
        return False
    return True


def measureTurn(chute: "Chute") -> float | None:
    """How many motor turns one turn of this chute takes: the microsteps from
    where the magnet's window ends, round to where it ends again. The chute must
    be homed on its magnet (so it stands at the window's edge) and is left
    needing a home. None if the magnet did not come round."""
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
        chute.markUnhomed("its turn was measured")
    if len(edges) < 2 or edges[1] == edges[0]:
        chute.logger.error("Chute: the magnet did not come round while measuring a turn.")
        return None
    steps = abs(edges[1] - edges[0])
    ratio = steps / stepper.total_steps_per_rev
    chute.logger.info(f"Chute: one turn is {steps} µsteps, {ratio:.4f} motor turns")
    return ratio


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


def _moveBy(chute: "Chute", chute_degrees: float) -> bool:
    """Turn the chute by this much, at its operating speed, and wait."""
    chute.setSpeed(chute.operating_speed_microsteps_per_second)
    motor_degrees = chute_degrees * chute.gear_ratio
    timeout_ms = chute.stepper.estimateMoveDegreesMs(
        motor_degrees, max_speed=chute.operating_speed_microsteps_per_second
    ) + 1500
    if not chute.stepper.move_degrees_blocking(motor_degrees, timeout_ms=timeout_ms):
        chute.logger.error(f"Chute: a {chute_degrees:g}° move while homing did not finish")
        return False
    return True
