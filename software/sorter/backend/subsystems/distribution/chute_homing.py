"""Finding the chute's home, on a switch or on a magnet.

Both are the board's own homing (firmware Stepper::stepgen_tick).

**On a switch** (a chute that turns between two stops): run toward the switch
until it trips, then back away to the first bin.

**On a magnet** (a chute that turns without limit): the magnet passes a sensor
once a turn, and the sensor reads it over a stretch of turning, as wide as its
setting makes it, flickering at both edges. The board finds the middle of that
stretch in one command and makes it home, so the bins are where the machine's
design puts them however the sensor is set.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .chute import Chute

# Homing runs toward lower angles; the sign is the direction.
HOME_SPEED_MICROSTEPS_PER_SEC = -1000
HOME_TIMEOUT_MS = 15000

# On a magnet: the board's speed through it, and how far past an edge the sensor
# must read off the magnet to count as off it, past where it flickers there.
MAGNET_HOME_SPEED = -2000
MAGNET_SETTLE_DEG = 5.0
# The board looks until it finds the magnet; this much turning is the limit.
MAGNET_SEARCH_TURNS = 2.5
MAGNET_ALWAYS_ON = (
    "The home sensor reads the magnet all the time. Check its wiring, and that its light goes off "
    "with the magnet away."
)
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
    """Have the board find the middle of the magnet and make it home, then turn
    the chute there."""
    chute.logger.info("Chute: homing on the middle of its magnet")
    found = findMagnetMiddle(chute)
    if found is None:
        return False
    _, width = found
    chute.logger.info(
        f"Chute: the home sensor reads the magnet over {chute.magnet_width_deg:.1f}° ({width} µsteps); home is its middle"
    )
    if chute.moveToAngleBlocking(0.0, timeout_buffer_ms=1500) is None:
        return _fail(chute, "The chute found its magnet but did not turn to its middle.")
    return True


def findMagnetMiddle(chute: "Chute") -> tuple[int, int] | None:
    """The board's own homing on a magnet (firmware Stepper::homeOnMagnet): it
    leaves the magnet if it starts on it, runs through it, and makes the middle
    of the stretch the sensor read it over 0. Returns where that middle was in
    the count from before, and how wide the stretch is, in microsteps. None,
    with the reason in chute.home_failure, if it did not find it."""
    stepper = chute.stepper
    settle = abs(stepper.microsteps_for_degrees(MAGNET_SETTLE_DEG * chute.gear_ratio))
    try:
        stepper.home_on_magnet(MAGNET_HOME_SPEED, chute.home_pin, chute.endstop_active_high, settle)
    except Exception as exc:
        _fail(chute, f"The control board could not home on the magnet ({exc}). Update its firmware.")
        return None
    started = time.monotonic()
    give_up_at = started + _secondsFor(chute, 360.0 * MAGNET_SEARCH_TURNS, MAGNET_HOME_SPEED) + 2.0
    while True:
        found, middle, width = stepper.magnet_home_result()
        if found:
            break
        if time.monotonic() > give_up_at:
            stepper.move_at_speed(0, force=True)
            if chute.endstop_triggered:
                _fail(chute, MAGNET_ALWAYS_ON)
            else:
                _fail(
                    chute,
                    "No magnet passed the home sensor in two turns. Check that the sensor is plugged in, "
                    "that the magnet is fitted and that the chute turns.",
                )
            return None
        if time.monotonic() - started >= START_GRACE_S and stepper.stopped:
            found, middle, width = stepper.magnet_home_result()
            if found:
                break
            _fail(chute, "The chute stopped before it found the middle of its magnet.")
            return None
        time.sleep(POLL_S)
    chute.magnet_width_deg = stepper.degrees_for_microsteps(width) / chute.gear_ratio
    return middle, width


def measureTurn(chute: "Chute") -> float | None:
    """How many motor turns one turn of this chute takes. The board finds the
    magnet's middle twice in a row: the second middle is one turn on from the
    first, in the count the first made 0. The chute is left needing a home.
    None if the magnet was not found."""
    try:
        if findMagnetMiddle(chute) is None:
            return None
        second = findMagnetMiddle(chute)
    finally:
        chute.markUnhomed("its turn was measured")
    if second is None:
        chute.logger.error("Chute: the magnet did not come round while measuring a turn.")
        return None
    steps = abs(second[0])
    ratio = steps / chute.stepper.total_steps_per_rev
    chute.logger.info(f"Chute: one turn is {steps} µsteps, {ratio:.4f} motor turns")
    return ratio


def _secondsFor(chute: "Chute", chute_degrees: float, speed: int) -> float:
    microsteps = chute.stepper.microsteps_for_degrees(chute_degrees * chute.gear_ratio)
    return abs(microsteps) / max(1, abs(speed))
