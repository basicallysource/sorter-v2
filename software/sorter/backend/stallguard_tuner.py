"""Self-tuning StallGuard: a motor with automatic tuning on learns what its
load reads in normal running, and keeps its stall trigger and speed floor set
from that, at whatever speed it runs.

A TMC2209 reports a stall (the firmware stops the motor and latches it) when
SG_RESULT, its load reading, falls to 2 x SGTHRS or below while the motor runs
faster than the speed floor: TSTEP at or under TCOOLTHRS. The reading drops as
the load rises and is near zero in a stall. What it reads in normal running
depends on the speed, the current, the microstepping and the chopper mode, and
it drifts as a motor wears or collects debris. So:

- The speed floor follows the speed. TCOOLTHRS is FLOOR_MARGIN times the TSTEP
  of the operating speed, so the driver judges the cruise and the top of each
  ramp at any speed. Lower down a ramp the reading sinks toward zero with no
  load at all on some motors, and judging it would force a trigger too low to
  catch anything.
- The trigger follows the load. While the motor makes a move at its operating
  speed, the tuner reads TSTEP and SG_RESULT every SAMPLE_INTERVAL_S and keeps
  the readings the driver judges. From the last WINDOW of them it takes the
  normal low (the NORMAL_LOW_QUANTILE) and puts the trigger as many times over
  a stall (STALL_SG) as it is under half that normal low.
- Until MIN_READINGS readings are in at the speed, current, microstepping and
  chopper mode the motor runs on, the trigger is PROVISIONAL_TRIGGER: a stall
  reads under it, and normal running does not come near it.
- A move that ends in a stall is not normal running: its readings are dropped.
- The highest normal low it has tuned to is kept. When the normal low falls
  under DRIFT_RATIO of it, the motor works harder than it did (wear, debris),
  and the status says so. Learning again starts over from the motor as it is.

It changes the driver only between moves, never clears a stall latch, and
saves what it sets, so the motor starts on it next time.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import db
from hardware.sorter_interface import DISABLE_STALLGUARD
from hardware_settings.motors import Motor, motorNamed
from hardware_settings.steppers import (
    TCOOLTHRS_EVERY_SPEED,
    StepperSettings,
    applyStepperSettings,
    changedStepperSettings,
    readStepperSettings,
    saveStepperSettings,
)

SAMPLE_INTERVAL_S = 0.05
SETTINGS_CHECK_S = 5.0
FLOOR_MARGIN = 1.25
# TSTEP counts the driver's 12 MHz clock between two 1/256 microsteps.
DRIVER_CLOCK_HZ = 12_000_000
WINDOW = 6000
MIN_READINGS = 600
RETUNE_EVERY = 300
NORMAL_LOW_QUANTILE = 0.005
STALL_SG = 4
SAFE_FRACTION = 0.5
PROVISIONAL_TRIGGER = 12
MIN_TRIGGER = 8
# Normal running under this reads within a few triggers of a stall: a stall
# still trips it, with little room for normal running.
RELIABLE_NORMAL_LOW = 32
DRIFT_RATIO = 0.6
# The stall monitor mirrors a stall onto the stepper this soon after it.
STALL_SEEN_S = 0.5
CHANGES_KEPT = 10
# After the driver refuses a change, it tries again this much later.
APPLY_RETRY_S = 30.0
REG_TSTEP = 0x12
REG_SG_RESULT = 0x41
SG_MAX = 1023
ERROR_LOG_INTERVAL_S = 300.0


def tstepAt(speed: float, microsteps: int) -> float:
    """The TSTEP a motor runs at, at `speed` µsteps/s."""
    return DRIVER_CLOCK_HZ * microsteps / (256.0 * speed)


def speedAt(tstep: float, microsteps: int) -> int:
    """The speed in µsteps/s a TSTEP stands for."""
    return round(DRIVER_CLOCK_HZ * microsteps / (256.0 * tstep))


def floorFor(speed: int, microsteps: int) -> int:
    return min(TCOOLTHRS_EVERY_SPEED, math.ceil(tstepAt(speed, microsteps) * FLOOR_MARGIN))


def triggerFor(normal_low: int) -> int:
    """2 x SGTHRS: as many times over a stall as under half the normal low."""
    return max(MIN_TRIGGER, min(2 * 255, round(math.sqrt(STALL_SG * SAFE_FRACTION * normal_low))))


def sgthrsFor(trigger: int) -> int:
    return max(1, min(255, round(trigger / 2)))


def normalLow(readings: list[int]) -> int:
    ordered = sorted(readings)
    return ordered[int(NORMAL_LOW_QUANTILE * (len(ordered) - 1))]


@dataclass(frozen=True)
class Conditions:
    """What the readings depend on; a change starts learning over."""

    speed: int
    microsteps: int
    irun: int
    stealthchop: bool

    @property
    def key(self) -> str:
        chopper = "stealthchop" if self.stealthchop else "spreadcycle"
        return f"{self.speed}/{self.microsteps}/{self.irun}/{chopper}"


@dataclass
class Learned:
    """What a motor has learned under one set of conditions; kept across restarts."""

    conditions: str = ""
    normal_low: int | None = None
    # The highest normal low it has tuned to: the motor at its easiest.
    baseline_low: int | None = None
    readings: int = 0
    tuned_at: float | None = None
    # Newest first: {at, sgthrs: [from, to], tcoolthrs: [from, to], why}.
    changes: list[dict[str, Any]] = field(default_factory=list)


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS stallguard_tuning ("
        "motor TEXT PRIMARY KEY, learned_json TEXT NOT NULL, updated_at REAL NOT NULL)"
    )


def _loadLearned(motor: Motor) -> Learned:
    with db.connect(_createTables) as conn:
        row = conn.execute(
            "SELECT learned_json FROM stallguard_tuning WHERE motor = ?", (motor.name,)
        ).fetchone()
    if row is None:
        return Learned()
    try:
        return Learned(**json.loads(row["learned_json"]))
    except Exception:
        return Learned()


def _storeLearned(motor: Motor, learned: Learned) -> None:
    with db.connect(_createTables) as conn:
        conn.execute(
            "INSERT INTO stallguard_tuning (motor, learned_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(motor) DO UPDATE SET learned_json = excluded.learned_json, "
            "updated_at = excluded.updated_at",
            (motor.name, json.dumps(asdict(learned)), time.time()),
        )
        conn.commit()


def _chute(irl: Any) -> tuple[Any, int] | None:
    chute = getattr(irl, "chute", None)
    if chute is None or getattr(chute, "stepper", None) is None:
        return None
    return chute.stepper, int(chute.operating_speed_microsteps_per_second)


# The motors it tunes, by API name: those whose operating speed it knows, with
# where to find the stepper and that speed.
TUNABLE: dict[str, Callable[[Any], tuple[Any, int] | None]] = {"chute": _chute}


def supports(motor: Motor) -> bool:
    return motor.name in TUNABLE


def _read(stepper: Any, register: int) -> int | None:
    try:
        return int(stepper.read_driver_register(register))
    except Exception:
        return None


class MotorTuning:
    """One motor's learning: its readings, what it set and why."""

    def __init__(self, motor: Motor, learned: Learned) -> None:
        self.motor = motor
        self.learned = learned
        self.readings: deque[int] = deque(maxlen=WINDOW)
        self.since_retune = 0
        self.conditions: Conditions | None = None
        self.settings: StepperSettings | None = None
        self.settings_read_at = -math.inf
        self.move: Any = None
        # The readings of the move being followed; None once it is judged.
        self.move_readings: list[int] | None = None
        # (sgthrs, tcoolthrs, why) for the driver, set between moves.
        self.target: tuple[int, int, str] | None = None
        self.retry_at = -math.inf
        self.state = "off"
        self.error: str | None = None

    def currentSettings(self, now: float) -> StepperSettings:
        if self.settings is None or now - self.settings_read_at >= SETTINGS_CHECK_S:
            self.settings = readStepperSettings(self.motor)
            self.settings_read_at = now
        return self.settings

    def floor(self) -> int:
        assert self.conditions is not None
        return floorFor(self.conditions.speed, self.conditions.microsteps)

    def aim(self, sgthrs: int, why: str) -> None:
        settings = self.settings
        floor = self.floor()
        if settings is not None and (settings.sgthrs, settings.tcoolthrs) == (sgthrs, floor):
            self.target = None
        else:
            self.target = (sgthrs, floor, why)

    def startOver(self, conditions: Conditions, why: str) -> None:
        self.conditions = conditions
        self.learned = Learned(conditions=conditions.key)
        self.readings.clear()
        self.since_retune = 0
        self.aim(sgthrsFor(PROVISIONAL_TRIGGER), why)

    def judgeMove(self, stalled: bool, log: Any) -> None:
        readings = self.move_readings
        self.move_readings = None
        if not readings:
            return
        if stalled:
            log.info(f"StallGuard tuner: {self.motor.name}: left out {len(readings)} readings of the move that stalled.")
            return
        self.readings.extend(readings)
        self.since_retune += len(readings)
        self.learned.readings += len(readings)

    def due(self) -> bool:
        if len(self.readings) < MIN_READINGS:
            return False
        return self.learned.normal_low is None or self.since_retune >= RETUNE_EVERY

    def retune(self, log: Any) -> None:
        self.since_retune = 0
        low = normalLow(list(self.readings))
        learned = self.learned
        was_harder = self.workingHarder()
        first = learned.normal_low is None
        learned.normal_low = low
        if learned.baseline_low is None or low > learned.baseline_low:
            learned.baseline_low = low
        if first:
            learned.tuned_at = time.time()
        if self.workingHarder() and not was_harder:
            log.warning(
                f"StallGuard tuner: {self.motor.name} works harder than it did: its normal "
                f"load reading fell from {learned.baseline_low} to {low}."
            )
        sgthrs = sgthrsFor(triggerFor(low))
        current = self.settings.sgthrs if self.settings is not None else None
        # Lowering it always goes through: it keeps normal running clear of it.
        # Raising it waits for a change of two, so it does not flicker.
        if first or current is None or sgthrs < current or sgthrs >= current + 2:
            self.aim(sgthrs, f"normal low {low} over {len(self.readings)} readings")

    def workingHarder(self) -> bool:
        learned = self.learned
        return (
            learned.normal_low is not None
            and learned.baseline_low is not None
            and learned.normal_low < DRIFT_RATIO * learned.baseline_low
        )

    def status(self) -> dict[str, Any]:
        settings = self.settings
        conditions = self.conditions
        learned = self.learned
        return {
            "state": self.state,
            "readings": len(self.readings),
            "needed": MIN_READINGS,
            "learned_from": learned.readings,
            "normal_low": learned.normal_low,
            "baseline_low": learned.baseline_low,
            "working_harder": self.workingHarder(),
            "reliable": learned.normal_low is None or learned.normal_low >= RELIABLE_NORMAL_LOW,
            "tuned_at": learned.tuned_at,
            "sgthrs": settings.sgthrs if settings else None,
            "trigger": 2 * settings.sgthrs if settings else None,
            "tcoolthrs": settings.tcoolthrs if settings else None,
            "speed": conditions.speed if conditions else None,
            "floor_speed": (
                speedAt(settings.tcoolthrs, conditions.microsteps)
                if settings and conditions and settings.tcoolthrs > 0
                else None
            ),
            "changes": learned.changes,
            "error": self.error,
        }


class StallGuardTuner:
    def __init__(self, gc: Any) -> None:
        self._gc = gc
        self._log = gc.logger
        self._lock = threading.Lock()
        self._tunings: dict[str, MotorTuning] = {}
        self._last_error_log = -math.inf

    def run(self) -> None:
        while True:
            try:
                self.step(time.monotonic())
            except Exception as e:
                now = time.monotonic()
                if now - self._last_error_log >= ERROR_LOG_INTERVAL_S:
                    self._last_error_log = now
                    self._log.warning(f"StallGuard tuner: {e}")
            time.sleep(SAMPLE_INTERVAL_S)

    def tuning(self, name: str) -> MotorTuning:
        tuning = self._tunings.get(name)
        if tuning is None:
            motor = motorNamed(name)
            assert motor is not None
            tuning = MotorTuning(motor, _loadLearned(motor))
            self._tunings[name] = tuning
        return tuning

    def step(self, now: float) -> None:
        from server import shared_state

        irl = shared_state.getActiveIRL()
        if irl is None:
            return
        for name, locate in TUNABLE.items():
            found = locate(irl)
            if found is None:
                continue
            stepper, speed = found
            lock = shared_state.pulse_locks.get(name)
            with self._lock:
                self.stepMotor(self.tuning(name), stepper, speed, now, busy=lock is not None and lock.locked())

    def stepMotor(self, tuning: MotorTuning, stepper: Any, speed: int, now: float, *, busy: bool = False) -> None:
        settings = tuning.currentSettings(now)
        if DISABLE_STALLGUARD or not (settings.stallguard and settings.stallguard_auto):
            tuning.state = "off"
            tuning.move_readings = None
            tuning.conditions = None
            return
        # A StallGuard recording or a jog holds the motor: what it reads then
        # is not normal running, and its settings are the recording's.
        if busy or not getattr(stepper, "stallguard_enabled", False):
            tuning.state = "waiting"
            tuning.move_readings = None
            return
        conditions = Conditions(speed, settings.microsteps, settings.irun, settings.stealthchop)
        if conditions != tuning.conditions:
            self.meet(tuning, conditions)
        self.follow(tuning, stepper, now)
        if tuning.due():
            tuning.retune(self._log)
            self.store(tuning)
        tuning.state = "tuned" if tuning.learned.normal_low is not None else "learning"
        if tuning.target is not None and now >= tuning.retry_at and self.betweenMoves(stepper, now):
            self.apply(tuning, stepper, now)

    def meet(self, tuning: MotorTuning, conditions: Conditions) -> None:
        """Conditions it has not been following: those it learned under before
        a restart, or new ones (a new speed, current, microstepping or chopper mode)."""
        previous = tuning.conditions
        if previous is None and tuning.learned.conditions == conditions.key and tuning.learned.normal_low is not None:
            tuning.conditions = conditions
            tuning.readings.clear()
            tuning.since_retune = 0
            tuning.aim(sgthrsFor(triggerFor(tuning.learned.normal_low)), "as learned before the restart")
            return
        tuning.startOver(conditions, f"learning at {conditions.speed} µsteps/s")
        self.store(tuning)

    def follow(self, tuning: MotorTuning, stepper: Any, now: float) -> None:
        assert tuning.conditions is not None
        move = getattr(stepper, "last_move", None)
        if move is not tuning.move:
            # A new move: the one before ended without a stall the machine stopped for.
            tuning.judgeMove(bool(getattr(stepper, "stalled", False)), self._log)
            tuning.move = move
            tuning.move_readings = [] if move is not None and move.max_speed == tuning.conditions.speed else None
        if move is None or tuning.move_readings is None:
            return
        ends = move.sent_at + move.duration_s
        if now <= ends + SAMPLE_INTERVAL_S:
            if now >= move.sent_at:
                self.sample(tuning, stepper)
        elif now > ends + STALL_SEEN_S:
            tuning.judgeMove(bool(getattr(stepper, "stalled", False)), self._log)

    def sample(self, tuning: MotorTuning, stepper: Any) -> None:
        assert tuning.move_readings is not None
        # Only what the driver judges: TSTEP at or under the speed floor.
        tstep = _read(stepper, REG_TSTEP)
        if tstep is None or not 0 < tstep <= tuning.floor():
            return
        sg = _read(stepper, REG_SG_RESULT)
        if sg is not None and 0 <= sg <= SG_MAX:
            tuning.move_readings.append(sg)

    def betweenMoves(self, stepper: Any, now: float) -> bool:
        if getattr(stepper, "stalled", False):
            return False
        move = getattr(stepper, "last_move", None)
        return move is None or now > move.sent_at + move.duration_s + SAMPLE_INTERVAL_S

    def apply(self, tuning: MotorTuning, stepper: Any, now: float) -> None:
        assert tuning.target is not None
        sgthrs, tcoolthrs, why = tuning.target
        # Someone may have just set them by hand, which turns tuning off.
        before = readStepperSettings(tuning.motor)
        if not (before.stallguard and before.stallguard_auto):
            tuning.settings = before
            tuning.target = None
            return
        changes = {"sgthrs": sgthrs, "tcoolthrs": tcoolthrs}
        try:
            applyStepperSettings(stepper, changedStepperSettings(tuning.motor, changes), changes, rearm=False)
            tuning.settings = saveStepperSettings(tuning.motor, changes)
        except Exception as e:
            tuning.error = f"Could not set the driver: {e}"
            tuning.retry_at = now + APPLY_RETRY_S
            self._log.warning(f"StallGuard tuner: {tuning.motor.name}: {tuning.error}")
            return
        tuning.error = None
        tuning.target = None
        tuning.learned.changes = [
            {"at": time.time(), "sgthrs": [before.sgthrs, sgthrs], "tcoolthrs": [before.tcoolthrs, tcoolthrs], "why": why},
            *tuning.learned.changes,
        ][:CHANGES_KEPT]
        self._log.info(
            f"StallGuard tuner: {tuning.motor.name} trips at {2 * sgthrs} (SGTHRS {before.sgthrs} -> {sgthrs}), "
            f"speed floor TCOOLTHRS {before.tcoolthrs} -> {tcoolthrs}: {why}."
        )
        self.store(tuning)

    def store(self, tuning: MotorTuning) -> None:
        try:
            _storeLearned(tuning.motor, tuning.learned)
        except Exception as e:
            db.report_failure("store StallGuard tuning", e)

    def status(self, name: str) -> dict[str, Any]:
        with self._lock:
            return self.tuning(name).status()

    def settingsChanged(self, name: str) -> None:
        with self._lock:
            tuning = self._tunings.get(name)
            if tuning is not None:
                tuning.settings = None

    def learnAgain(self, name: str) -> None:
        with self._lock:
            tuning = self.tuning(name)
            if tuning.conditions is not None:
                tuning.startOver(tuning.conditions, "learning again")
            else:
                tuning.learned = Learned()
            self.store(tuning)


_tuner: StallGuardTuner | None = None


def start(gc: Any) -> StallGuardTuner:
    global _tuner
    _tuner = StallGuardTuner(gc)
    threading.Thread(target=_tuner.run, daemon=True, name="stallguard-tuner").start()
    return _tuner


def status(motor: Motor) -> dict[str, Any]:
    """The motor's automatic tuning, as the StallGuard tab shows it."""
    settings = readStepperSettings(motor)
    result: dict[str, Any] = {
        "motor": motor.name,
        "supported": supports(motor),
        "auto": settings.stallguard_auto,
        "running": _tuner is not None,
    }
    if supports(motor) and _tuner is not None:
        result.update(_tuner.status(motor.name))
    return result


def learnAgain(motor: Motor) -> None:
    if _tuner is not None and supports(motor):
        _tuner.learnAgain(motor.name)


def settingsChanged(motor: Motor) -> None:
    """A setting of the motor was saved: read them again before the next move."""
    if _tuner is not None and supports(motor):
        _tuner.settingsChanged(motor.name)
