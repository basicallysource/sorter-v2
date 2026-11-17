"""Every stepper driver's readings, kept and watched while the hardware runs.

A TMC2209 protects itself: over its temperature limit, or when it reads a short
on a coil, it switches its outputs off and stays off. The control board goes on
sending it steps and answers every move with success, so the motor stands still
and nothing else in the backend can tell. One way into that state needs no real
short: a StealthChop driver run below the current it can regulate tunes its PWM
amplitude far out of range, and the first move at a real current trips the
protection (hardware_settings.steppers.resetDriverTuning).

One daemon thread, started when the hardware starts and stopped with it, reads
one driver every TICK_S, the motors in turn: DRV_STATUS, GSTAT, PWM_SCALE and
PWM_AUTO, and SG_RESULT and TSTEP while the motor moves, whether StallGuard is
on or not. Every read takes the bus lock the control loop needs too, so a tick
makes six at most, and a driver that does not answer is left alone for a while.
With the readings it:

- keeps the last MEMORY_S of every driver in memory, for the pages that draw
  them (GET /api/drivers, server/routers/drivers.py);
- writes a thinned copy down as `driver_readings` telemetry windows
  (telemetry_store, a kind of the machine's own that is never sent), so the
  history outlives a restart. The storage is often an SD card, so it is kept
  light: one write at most every WRITE_EVERY_S, a reading every KEEP_ACTIVE_S
  while its motor moves and every KEEP_QUIET_S while it stands still
  (worthKeeping), and nothing older than RETENTION_S, pruned here;
- warns on the dashboard while a driver runs hot (incidents, a kind that does
  not hold the machine);
- holds the machine while a driver is switched off, and restarts it: driver
  off, tuning reset, error flags cleared, current and microstepping sent again,
  driver on. A stall the board latched for it was the driver's error line, and
  is cleared with it (stepper_stall_monitor hands such a latch over). The chute
  has lost its position by then, so it is homed again before the hold ends;
  any other motor just goes on. After RECOVERY_ATTEMPTS in RECOVERY_WINDOW_S
  the watch stops trying, pauses the machine and leaves the hold up with a
  Try again button;
- resets a tuning that stands far out of range (PWM_OFS_AUTO_OUT_OF_RANGE)
  while the motor stands still, before it can trip the protection.

When the hardware starts, every driver is looked at once before anything
moves, so a driver left switched off or badly tuned by an earlier run homes
like any other.

Which machines watch their drivers is their generation's choice
(hardware_settings/generation.py); machine.toml overrides it, read when the
hardware starts:

    [driver_watch]
    enabled = true

A machine that does not watch them reads nothing, and the routes say so.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Mapping, NamedTuple

import incidents
import machine_toml
import telemetry_store
from computer_health import Episode
from hardware_settings.generation import machineGeneration
from hardware_settings.motors import MOTORS, NAME_ALIASES, Motor, apiNames, motorNamed
from hardware_settings.steppers import readStepperSettings, resetDriverTuning
from stepper_stall_monitor import CHUTE_NEEDS_HOMING_INCIDENT_KIND, requestPauseIfRunning
from tmc_telemetry import (
    REG_DRV_STATUS,
    REG_GSTAT,
    REG_PWM_AUTO,
    REG_PWM_SCALE,
    REG_SG_RESULT,
    REG_TSTEP,
    decodeDrvStatus,
    decodeGstat,
    decodePwmAuto,
    decodePwmScale,
    fullStepsPerSecond,
    safeReadRegister,
)

log = logging.getLogger(__name__)

# machine.toml: [driver_watch] enabled.
TABLE = "driver_watch"
KEY = "enabled"

TICK_S = 0.2
MEMORY_S = 2 * 3600.0
# The most a history answer holds, about (thin).
HISTORY_SAMPLES = 1200
# A driver's latest reading is shown while it is this fresh.
LATEST_MAX_AGE_S = 10.0
RECOVERIES_KEPT = 20

# What is written down.
KIND = "driver_readings"
SCHEMA = 1
RETENTION_S = 24 * 3600.0
WRITE_EVERY_S = 30.0
# A batch smaller than WRITE_ROWS waits up to WRITE_QUIET_EVERY_S for more.
WRITE_ROWS = 20
WRITE_QUIET_EVERY_S = 300.0
# A driver's readings are written this far apart while its motor moves or its
# tuning shifts, and this far apart while nothing happens.
KEEP_ACTIVE_S = 2.0
KEEP_QUIET_S = 60.0
KEEP_TUNING_STEP = 4
ROWS_PER_RECORD = 1000
PENDING_ROWS_MAX = 5000
PRUNE_EVERY_S = 600.0

# PWM_OFS_AUTO is the PWM amplitude (0 to 255) a StealthChop driver has learned
# its motor needs to hold its current standing still. On the Sorter's motors it
# settles between about 35 and 65. A driver run below the current it can
# regulate keeps raising it, and from here up the first move at a real current
# draws enough for the short-circuit protection to switch a coil off. A motor
# standing still with it this high has its tuning reset before it moves again.
PWM_OFS_AUTO_OUT_OF_RANGE = 160

# A driver gets this many restarts, homes or tuning resets in RECOVERY_WINDOW_S.
RECOVERY_ATTEMPTS = 3
RECOVERY_WINDOW_S = 600.0
# The control loop gets this long to see the hold before the driver comes back.
PARK_S = 0.5
# A move the board is still stepping gets this long to end before a restart.
MOVE_WAIT_S = 3.0
RETRY_AFTER_S = 5.0
# A stall latched this soon after a restart was the driver's too.
STALL_CLAIM_S = 5.0

READ_FAILURES_TO_REST = 3
READ_FAILURE_REST_S = 10.0
ERROR_LOG_INTERVAL_S = 300.0
# The overheating warning starts and ends this long after the driver's flag.
HOT_START_S = 2.0
HOT_END_S = 30.0
JOIN_S = 2.0
# Readings and actions a driver gets in the look before the first move.
FIRST_LOOK_VISITS = 4

# Sample.flags.
MOVING = 1
OVERHEATING = 2
OVERHEATED = 4
SHORT = 8
SHUT_DOWN = 16
ALERT_FLAGS = OVERHEATING | OVERHEATED | SHORT | SHUT_DOWN

# A driver's fault, as the routes name it.
SHUT_DOWN_FAULT = "shut_down"
OVERHEATED_FAULT = "overheated"
OVERHEATING_FAULT = "overheating"
TUNING_FAULT = "tuning_out_of_range"

# The incident each fault shows as (incidents/kinds.py). The first two hold
# the machine; the others are warnings.
HOLDS = {SHUT_DOWN_FAULT: "driver_shut_down", OVERHEATED_FAULT: "driver_overheated"}
OVERHEATING_WARNING = "driver_overheating"
TUNING_WARNING = "driver_tuning_out_of_range"

RESTARTED = "restarted the driver"
HOMED = "homed the chute"
RESET_TUNING = "reset the tuning"

# What is being done about a switched-off driver, on its incident's card.
RESTARTING_IT = "It is being restarted."
COOLING = "It starts again once it has cooled. Check that air reaches the control board."
HOMING_CHUTE = "The chute is being homed again."

# How far getting a switched-off driver back is (_Outage.stage).
WAITING = "waiting"
RESTARTING = "restarting"
SENT = "sent"
HOME = "home"


class Sample(NamedTuple):
    """One reading of a driver. `flags` adds up MOVING, OVERHEATING,
    OVERHEATED, SHORT and SHUT_DOWN. SG_RESULT and TSTEP are read only while
    the motor moves: standing still they say nothing."""

    t: float
    flags: int
    cs_actual: int
    sg_result: int | None
    tstep: int | None
    pwm_scale_sum: int | None
    pwm_scale_auto: int | None
    pwm_ofs_auto: int | None
    pwm_grad_auto: int | None


def samplePayload(sample: Sample) -> dict[str, Any]:
    """A reading as the routes give it."""
    if not sample.flags & MOVING:
        speed: float | None = 0.0
    else:
        speed = fullStepsPerSecond(sample.tstep) if sample.tstep is not None else None
    return {
        "t": round(sample.t, 3),
        "moving": bool(sample.flags & MOVING),
        "cs_actual": sample.cs_actual,
        "sg_result": sample.sg_result,
        "full_steps_per_s": round(speed, 2) if speed is not None else None,
        "pwm_scale_sum": sample.pwm_scale_sum,
        "pwm_scale_auto": sample.pwm_scale_auto,
        "pwm_ofs_auto": sample.pwm_ofs_auto,
        "pwm_grad_auto": sample.pwm_grad_auto,
        "overheating": bool(sample.flags & OVERHEATING),
        "overheated": bool(sample.flags & OVERHEATED),
        "short": bool(sample.flags & SHORT),
        "shut_down": bool(sample.flags & SHUT_DOWN),
    }


def readSample(stepper: Any, now: float) -> tuple[Sample, dict[str, Any]] | None:
    """Read a driver: the sample and its decoded DRV_STATUS, or None when it
    does not answer. Four register reads standing still, six moving."""
    raw = safeReadRegister(stepper, REG_DRV_STATUS)
    if raw is None:
        return None
    drv = decodeDrvStatus(raw)
    gstat = safeReadRegister(stepper, REG_GSTAT)
    moving = not drv["stst"]
    sg = tstep = None
    if moving:
        sg = safeReadRegister(stepper, REG_SG_RESULT)
        tstep = safeReadRegister(stepper, REG_TSTEP)
    scale = safeReadRegister(stepper, REG_PWM_SCALE)
    auto = safeReadRegister(stepper, REG_PWM_AUTO)
    short = drv["s2ga"] or drv["s2gb"] or drv["s2vsa"] or drv["s2vsb"]
    # drv_err stays set after the flags that raised it are gone: the driver was
    # switched off at some point since it was last cleared.
    shut_down = short or drv["ot"] or (gstat is not None and decodeGstat(gstat)["drv_err"])
    flags = (
        (MOVING if moving else 0)
        | (OVERHEATING if drv["otpw"] else 0)
        | (OVERHEATED if drv["ot"] else 0)
        | (SHORT if short else 0)
        | (SHUT_DOWN if shut_down else 0)
    )
    pwm = decodePwmScale(scale) if scale is not None else {}
    tuned = decodePwmAuto(auto) if auto is not None else {}
    sample = Sample(
        now,
        flags,
        drv["cs_actual"],
        sg,
        tstep,
        pwm.get("pwm_scale_sum"),
        pwm.get("pwm_scale_auto"),
        tuned.get("pwm_ofs_auto"),
        tuned.get("pwm_grad_auto"),
    )
    return sample, drv


def worthKeeping(kept: Sample | None, sample: Sample) -> bool:
    """Whether a reading is written down, given the last one of its driver that
    was: when an alert flag changed, every KEEP_ACTIVE_S while the motor moves
    or its tuning shifts, and every KEEP_QUIET_S otherwise."""
    if kept is None:
        return True
    gap = sample.t - kept.t
    if gap < 0 or gap >= KEEP_QUIET_S:
        return True
    if (sample.flags ^ kept.flags) & ALERT_FLAGS:
        return True
    active = (
        bool((sample.flags | kept.flags) & MOVING)
        or _shifted(sample.pwm_ofs_auto, kept.pwm_ofs_auto)
        or _shifted(sample.pwm_grad_auto, kept.pwm_grad_auto)
    )
    return active and gap >= KEEP_ACTIVE_S


def _shifted(value: int | None, kept: int | None) -> bool:
    return value is not None and kept is not None and abs(value - kept) >= KEEP_TUNING_STEP


def thin(samples: list[Sample]) -> list[Sample]:
    """About HISTORY_SAMPLES at most: the newest quarter as they are, the older
    ones picked evenly, plus every one where an alert flag changed, so a short
    fault is never thinned away."""
    if len(samples) <= HISTORY_SAMPLES:
        return samples
    newest = samples[-(HISTORY_SAMPLES // 4):]
    older = samples[: len(samples) - len(newest)]
    slots = HISTORY_SAMPLES - len(newest)
    step = len(older) / slots
    picked = {int(index * step) for index in range(slots)}
    thinned: list[Sample] = []
    alerts = older[0].flags & ALERT_FLAGS
    for index, sample in enumerate(older):
        changed = sample.flags & ALERT_FLAGS != alerts
        alerts = sample.flags & ALERT_FLAGS
        if changed or index in picked:
            thinned.append(sample)
    return thinned + newest


def watchEnabled(config: Mapping[str, Any] | None = None, logger: Any = None) -> bool:
    """Whether this machine watches its drivers: what machine.toml says, else
    its generation's choice. A value that is not true or false is ignored,
    with a warning."""
    if config is None:
        config = machine_toml.read()
    built_in = machineGeneration(config).driver_watch
    table = config.get(TABLE)
    if not isinstance(table, dict) or KEY not in table:
        return built_in
    value = table[KEY]
    if isinstance(value, bool):
        return value
    if logger is not None:
        logger.warning(
            f"Ignoring {TABLE}.{KEY} = {value!r}: expected true or false. "
            f"Taking it as {'true' if built_in else 'false'}."
        )
    return built_in


class _Outage:
    """A driver that has switched itself off, and how far getting it back is."""

    def __init__(self, kind: str, since: float, detail: str, not_before: float) -> None:
        self.kind = kind
        self.since = since
        self.detail = detail
        # What is being done about it, for the incident's card.
        self.doing = COOLING if kind == OVERHEATED_FAULT else RESTARTING_IT
        self.stage = WAITING
        # Monotonic: when it began, and the earliest the next step may be taken.
        self.began = time.monotonic()
        self.not_before = not_before
        # The chute's motor: its position is lost, so it is homed again.
        self.rehome = False
        # The home straight after a restart belongs to that attempt.
        self.home_free = False
        self.homing = False
        self.home_result: bool | None = None
        self.gave_up = False
        self.retry = False
        # The card last shown, so it is written again only when it changes.
        self.shown: tuple[Any, ...] | None = None


class _Driver:
    """One motor's driver: its readings, which outlive the hardware, and what
    is live while the hardware runs."""

    def __init__(self, motor: Motor) -> None:
        self.motor = motor
        self.label = motor.label[:1].upper() + motor.label[1:]
        self.samples: deque[Sample] = deque()
        self.recoveries: deque[dict[str, Any]] = deque(maxlen=RECOVERIES_KEPT)
        # The last reading written down.
        self.kept: Sample | None = None
        self.unbind()

    def unbind(self) -> None:
        """The hardware is down: nothing of this driver is live."""
        self.stepper: Any = None
        self.outage: _Outage | None = None
        self.outage_ended = float("-inf")
        self.hot = Episode(HOT_START_S, HOT_END_S)
        self.hot_detail = ""
        self.tuning_since: float | None = None
        self.tuning_detail = ""
        self.tuning_gave_up = False
        self.reset_tuning = False
        self.tuning_reset_at: float | None = None
        # When its recovery attempts were made (monotonic).
        self.attempts: deque[float] = deque()
        # Read it at the next tick, before its turn.
        self.due = False
        # A stall the board latched for it is the driver's own error line.
        self.clear_latch = False
        self.failures = 0
        self.silent = False
        self.resting_until = 0.0


class DriverWatch:
    def __init__(self, gc: Any = None) -> None:
        self._gc = gc
        self._lock = threading.Lock()
        self._drivers = {motor.name: _Driver(motor) for motor in MOTORS}
        self._order = list(self._drivers.values())
        self._next = 0
        self._irl: Any = None
        self._pending: list[tuple[str, Sample]] = []
        self._written = time.monotonic()
        self._pruned = float("-inf")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error_log = float("-inf")

    # -- the hardware's start and stop -------------------------------------

    @property
    def attached(self) -> bool:
        """Whether it is reading the drivers of started hardware."""
        return self._thread is not None

    def attach(self, irl: Any) -> None:
        """The hardware started: look at every driver once, before anything
        moves, then keep reading them."""
        self.detach()
        self._irl = irl
        with self._lock:
            for driver in self._order:
                driver.unbind()
                driver.stepper = getattr(irl, driver.motor.attr, None)
        self._firstLook()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(self._stop,), daemon=True, name="driver-watch")
        self._thread.start()

    def detach(self) -> None:
        """The hardware is stopping: stop reading, and close what was raised."""
        thread, self._thread = self._thread, None
        self._stop.set()
        if thread is not None:
            thread.join(timeout=JOIN_S)
        for driver in self._order:
            if driver.stepper is not None:
                self._closeAlerts(driver)
        with self._lock:
            for driver in self._order:
                driver.unbind()
        self._irl = None

    def _firstLook(self) -> None:
        for driver in self._order:
            if driver.stepper is None:
                continue
            driver.due = True
            for _ in range(FIRST_LOOK_VISITS):
                if not driver.due:
                    break
                try:
                    self._visit(driver, time.time(), time.monotonic())
                except Exception as exc:
                    self._logError(exc)
                    break
            driver.due = False

    def _loop(self, stop: threading.Event) -> None:
        while not stop.is_set():
            started = time.monotonic()
            try:
                self._tick(time.time(), started)
            except Exception as exc:
                self._logError(exc)
            try:
                self._writeDown(time.time(), time.monotonic())
            except Exception as exc:
                self._logError(exc)
            stop.wait(max(0.05, TICK_S - (time.monotonic() - started)))
        try:
            self._writeDown(time.time(), time.monotonic(), everything=True)
        except Exception as exc:
            self._logError(exc)

    # -- one tick ----------------------------------------------------------

    def _tick(self, now: float, mono: float) -> None:
        driver = self._pick(mono)
        if driver is not None:
            self._visit(driver, now, mono)

    def _pick(self, mono: float) -> _Driver | None:
        """The driver for this tick: one with something under way, else the
        next in turn that is not being left alone."""
        for driver in self._order:
            if driver.due and driver.stepper is not None:
                return driver
        for offset in range(len(self._order)):
            index = (self._next + offset) % len(self._order)
            driver = self._order[index]
            if driver.stepper is not None and driver.resting_until <= mono:
                self._next = index + 1
                return driver
        return None

    def _visit(self, driver: _Driver, now: float, mono: float) -> None:
        """One driver's tick: a step of what is being done to it, which reads
        one register, or else a reading and what follows from it."""
        driver.due = False
        outage = driver.outage
        if outage is not None and outage.stage == RESTARTING:
            self._restart(driver, outage, now, mono)
            return
        if driver.reset_tuning:
            self._resetTuning(driver, now, mono)
            return
        reading = readSample(driver.stepper, now)
        if reading is None:
            self._noAnswer(driver, mono)
            return
        if driver.silent:
            driver.silent = False
            self._log("info", f"driver watch: the {driver.motor.label} stepper's driver answers again")
        driver.failures = 0
        sample, drv = reading
        self._remember(driver, sample)
        self._watchOutage(driver, sample, drv, now, mono)
        self._watchHeat(driver, sample, drv, now)
        self._watchTuning(driver, sample, drv, now, mono)
        if driver.clear_latch and (driver.outage is None or driver.outage.stage == HOME):
            # A latch handed over once its driver was already on again.
            self._clearStallLatch(driver)

    def _noAnswer(self, driver: _Driver, mono: float) -> None:
        driver.failures += 1
        if driver.failures < READ_FAILURES_TO_REST:
            return
        driver.failures = 0
        driver.resting_until = mono + READ_FAILURE_REST_S
        if not driver.silent:
            driver.silent = True
            self._log(
                "warning",
                f"driver watch: the {driver.motor.label} stepper's driver does not answer; "
                f"asking it every {READ_FAILURE_REST_S:.0f} s",
            )

    def _remember(self, driver: _Driver, sample: Sample) -> None:
        with self._lock:
            driver.samples.append(sample)
            while driver.samples[0].t < sample.t - MEMORY_S:
                driver.samples.popleft()
            if worthKeeping(driver.kept, sample):
                driver.kept = sample
                self._pending.append((driver.motor.name, sample))
                del self._pending[: max(0, len(self._pending) - PENDING_ROWS_MAX)]

    # -- a driver that switched itself off ---------------------------------

    def _watchOutage(self, driver: _Driver, sample: Sample, drv: dict[str, Any], now: float, mono: float) -> None:
        off = bool(sample.flags & SHUT_DOWN)
        outage = driver.outage
        if outage is None:
            if not off:
                return
            outage = self._beginOutage(driver, sample, drv, now, mono)
        if outage.retry:
            # Try again was pressed.
            outage.retry = False
            outage.gave_up = False
            outage.not_before = mono
            driver.attempts.clear()
        if outage.stage == SENT:
            # The reading after a restart tells whether it took.
            self._note(driver, now, RESTARTED, not off)
            outage.stage = WAITING
            if off:
                outage.not_before = mono + RETRY_AFTER_S
        if outage.stage == WAITING:
            self._waitToRestart(driver, outage, sample, drv, off, mono)
        if driver.outage is outage and outage.stage == HOME:
            self._homeAgain(driver, outage, off, now, mono)

    def _beginOutage(self, driver: _Driver, sample: Sample, drv: dict[str, Any], now: float, mono: float) -> _Outage:
        kind = OVERHEATED_FAULT if sample.flags & OVERHEATED else SHUT_DOWN_FAULT
        park = PARK_S if self._controllerLive() else 0.0
        outage = driver.outage = _Outage(kind, now, self._outageDetail(driver, kind, drv), mono + park)
        chute = self._chuteOf(driver)
        outage.rehome = chute is not None
        self._log("error", f"driver watch: {outage.detail}")
        self._hold(driver, outage)
        if chute is not None:
            # Once the hold is up, so the stall monitor's hold for a chute that
            # needs homing does not open in its place.
            chute.markUnhomed("its driver switched itself off")
        return outage

    def _waitToRestart(
        self, driver: _Driver, outage: _Outage, sample: Sample, drv: dict[str, Any], off: bool, mono: float
    ) -> None:
        if sample.flags & OVERHEATED:
            # Too hot to come back yet: the driver stays off until it has cooled.
            outage.kind = OVERHEATED_FAULT
            outage.detail = self._outageDetail(driver, OVERHEATED_FAULT, drv)
            outage.doing = COOLING
            self._hold(driver, outage)
            return
        if not off:
            self._restarted(driver, outage)
            return
        if outage.gave_up:
            self._hold(driver, outage)
            requestPauseIfRunning(self._gc, "A motor driver stays switched off")
            return
        if mono < outage.not_before:
            return
        if not self._attemptsLeft(driver, mono):
            self._giveUp(driver, outage)
            return
        outage.doing = RESTARTING_IT
        outage.stage = RESTARTING
        driver.due = True
        self._hold(driver, outage)

    def _restart(self, driver: _Driver, outage: _Outage, now: float, mono: float) -> None:
        """Switch the driver off, reset it and switch it on again. The next
        reading tells whether it took."""
        if mono - outage.began < MOVE_WAIT_S and not self._stopped(driver.stepper):
            return  # a move the board is still stepping ends first; at its next turn
        self._spend(driver, mono)
        try:
            self._resetDriver(driver, clear_shutdown=True)
        except Exception as exc:
            self._note(driver, now, RESTARTED, False)
            self._log("warning", f"driver watch: restarting the {driver.motor.label} stepper's driver failed: {exc}")
            outage.stage = WAITING
            outage.not_before = mono + RETRY_AFTER_S
            return
        outage.stage = SENT
        driver.due = True

    def _restarted(self, driver: _Driver, outage: _Outage) -> None:
        """The driver is on again."""
        if driver.clear_latch:
            self._clearStallLatch(driver)
        if not outage.rehome:
            self._resolve(driver, outage)
            return
        outage.stage = HOME
        outage.home_free = True

    def _homeAgain(self, driver: _Driver, outage: _Outage, off: bool, now: float, mono: float) -> None:
        if outage.homing:
            return  # the home under way tells
        if outage.home_result is not None:
            homed, outage.home_result = outage.home_result, None
            self._note(driver, now, HOMED, homed)
            outage.not_before = mono + RETRY_AFTER_S
        if off:
            # It switched itself off again: back to restarting it.
            outage.stage = WAITING
            return
        chute = self._chuteOf(driver)
        if chute is None or chute.homed or not self._homesHere():
            # Homed, or not a homed machine at rest: its next start or home
            # finds home.
            self._resolve(driver, outage)
            return
        if outage.gave_up:
            self._hold(driver, outage)
            requestPauseIfRunning(self._gc, "The chute did not find home after its driver was restarted")
            return
        if mono < outage.not_before:
            return
        outage.doing = HOMING_CHUTE
        if not self._hold(driver, outage):
            return  # another incident holds the machine: when this one's turn comes
        if not outage.home_free:
            if not self._attemptsLeft(driver, mono):
                self._giveUp(driver, outage, at_home=True)
                return
            self._spend(driver, mono)
        outage.home_free = False
        outage.homing = True
        threading.Thread(
            target=self._homeChute, args=(driver, outage, chute), daemon=True, name="driver-watch-home"
        ).start()

    def _homeChute(self, driver: _Driver, outage: _Outage, chute: Any) -> None:
        """Home the chute, off the watch's thread: it takes seconds. The hold
        stays up meanwhile, so the control loop sends the chute nowhere."""
        try:
            homed = bool(chute.home())
        except Exception as exc:
            self._log("warning", f"driver watch: homing the chute failed: {exc}")
            homed = False
        outage.home_result = homed
        outage.homing = False
        driver.due = True

    def _giveUp(self, driver: _Driver, outage: _Outage, at_home: bool = False) -> None:
        outage.gave_up = True
        minutes = RECOVERY_WINDOW_S / 60.0
        if at_home:
            outage.doing = (
                "Its driver is on again, but the chute did not find home. "
                "Check that it turns freely, then press Try again."
            )
        elif outage.kind == OVERHEATED_FAULT:
            # It comes back each time it cools and overheats again: the current
            # is more than this driver can carry for this motor's work.
            outage.doing = (
                f"It overheated {RECOVERY_ATTEMPTS} times in {minutes:.0f} minutes. Lower its run current, "
                "or cool the driver, then press Try again."
            )
        else:
            outage.doing = (
                f"Restarting it {RECOVERY_ATTEMPTS} times in {minutes:.0f} minutes did not keep it on. "
                "Check the motor's cable and plug, then press Try again."
            )
        self._log("error", f"driver watch: giving up on the {driver.motor.label} stepper's driver: {outage.doing}")
        self._hold(driver, outage)
        requestPauseIfRunning(self._gc, "A motor driver stays switched off")

    def _resolve(self, driver: _Driver, outage: _Outage) -> None:
        driver.outage = None
        driver.outage_ended = time.monotonic()
        self._log(
            "info",
            f"driver watch: the {driver.motor.label} stepper's driver is on again, "
            f"{time.time() - outage.since:.0f} s after it switched itself off",
        )
        self._release(driver)

    def _outageDetail(self, driver: _Driver, kind: str, drv: dict[str, Any]) -> str:
        subject = f"The {driver.motor.label} stepper's driver"
        if kind == OVERHEATED_FAULT:
            return f"{subject} overheated and switched itself off."
        a = drv["s2ga"] or drv["s2vsa"]
        b = drv["s2gb"] or drv["s2vsb"]
        if not (a or b):
            return f"{subject} switched itself off to protect itself."
        coils = "coils A and B" if a and b else "coil A" if a else "coil B"
        return f"{subject} switched itself off: it read a short on {coils}."

    # -- the incident that holds the machine --------------------------------

    def _hold(self, driver: _Driver, outage: _Outage) -> bool:
        """Show the outage as the open incident, which holds the machine, or
        bring its card up to date. False while another incident is open."""
        stats = getattr(self._gc, "runtime_stats", None)
        if stats is None:
            return False
        kind = HOLDS[outage.kind]
        shown = (kind, outage.detail, outage.doing, outage.gave_up)
        fields = {
            "channel": driver.motor.key,
            "detail": outage.detail,
            "doing": outage.doing,
            "gave_up": outage.gave_up,
            "operator_message": f"{outage.detail} {outage.doing}".strip(),
        }
        active = stats.activeIncident()
        if active is None:
            opened = incidents.report(self._gc, kind, subject=driver.label, triggered_at=outage.since, **fields)
            outage.shown = shown if opened else None
            return opened
        if active.get("kind") in HOLDS.values() and active.get("subject") == driver.label:
            if outage.shown != shown:
                stats.setActiveIncident({**active, "kind": kind, **fields})
                outage.shown = shown
            return True
        if outage.rehome and active.get("kind") == CHUTE_NEEDS_HOMING_INCIDENT_KIND:
            # The stall monitor's hold for the home this chute lost. This one
            # says why it lost it, and homes it.
            stats.setActiveIncident({"kind": kind, "subject": driver.label, "triggered_at": outage.since, **fields})
            outage.shown = shown
            return True
        return False

    def _release(self, driver: _Driver) -> None:
        for kind in HOLDS.values():
            incidents.clear(self._gc, kind, subject=driver.label, resolved_by="driver_watch")

    def _closeAlerts(self, driver: _Driver) -> None:
        self._release(driver)
        for kind in (OVERHEATING_WARNING, TUNING_WARNING):
            incidents.clear(self._gc, kind, subject=driver.label)

    # -- a driver running hot ------------------------------------------------

    def _watchHeat(self, driver: _Driver, sample: Sample, drv: dict[str, Any], now: float) -> None:
        hot = bool(sample.flags & OVERHEATING)
        change = driver.hot.update(now, hot, not hot)
        if change == "ended":
            self._log("info", f"driver watch: the {driver.motor.label} stepper's driver has cooled")
            incidents.clear(self._gc, OVERHEATING_WARNING, subject=driver.label)
            return
        if not driver.hot.active:
            return
        # The driver's own thresholds; its warning comes at the first.
        over = 157 if drv["t157"] else 150 if drv["t150"] else 143 if drv["t143"] else 120
        detail = f"The {driver.motor.label} stepper's driver is running hot (over {over} °C)."
        if change != "started" and detail == driver.hot_detail:
            return
        driver.hot_detail = detail
        if change == "started":
            self._log("warning", f"driver watch: {detail}")
        incidents.report(self._gc, OVERHEATING_WARNING, subject=driver.label, channel=driver.motor.key, detail=detail)

    # -- a tuning out of range -----------------------------------------------

    def _watchTuning(self, driver: _Driver, sample: Sample, drv: dict[str, Any], now: float, mono: float) -> None:
        offset = sample.pwm_ofs_auto
        if offset is None:
            return
        if driver.tuning_reset_at is not None:
            # The reading after a reset tells whether it held.
            self._note(driver, driver.tuning_reset_at, RESET_TUNING, offset < PWM_OFS_AUTO_OUT_OF_RANGE)
            driver.tuning_reset_at = None
        if driver.outage is not None:
            return  # restarting the driver resets its tuning too
        if offset < PWM_OFS_AUTO_OUT_OF_RANGE:
            if driver.tuning_since is not None:
                self._log("info", f"driver watch: the {driver.motor.label} stepper's driver is tuned in range again")
                driver.tuning_since = None
                driver.tuning_gave_up = False
                incidents.clear(self._gc, TUNING_WARNING, subject=driver.label)
            return
        if sample.flags & MOVING or not drv["stealth"]:
            return  # judged standing still, and only StealthChop uses it
        driver.tuning_detail = (
            f"The {driver.motor.label} stepper's driver has tuned itself out of range "
            f"(offset {offset}, where {PWM_OFS_AUTO_OUT_OF_RANGE} is already far too high)."
        )
        if driver.tuning_since is None:
            driver.tuning_since = now
            self._log("warning", f"driver watch: {driver.tuning_detail}")
        if driver.tuning_gave_up:
            return
        if self._attemptsLeft(driver, mono):
            driver.reset_tuning = True
            driver.due = True
            return
        driver.tuning_gave_up = True
        # A tuning that runs out of range again after every reset is a run
        # current set lower than the driver can hold on this motor.
        driver.tuning_detail = (
            f"The {driver.motor.label} stepper's driver cannot hold a run current as low as the one set "
            f"({readStepperSettings(driver.motor).irun} of 31) on this motor, so its tuning runs out of range "
            f"(offset {offset}). The motor still turns, at about the lowest current the driver can hold. "
            "Raise the run current to clear this."
        )
        self._log(
            "warning",
            f"driver watch: resetting the {driver.motor.label} stepper's tuning does not hold; leaving it",
        )
        incidents.report(
            self._gc, TUNING_WARNING, subject=driver.label, channel=driver.motor.key, detail=driver.tuning_detail
        )

    def _resetTuning(self, driver: _Driver, now: float, mono: float) -> None:
        driver.reset_tuning = False
        if not self._stopped(driver.stepper):
            return  # it has started to move: asked again once it stands still
        self._spend(driver, mono)
        try:
            self._resetDriver(driver, clear_shutdown=False)
        except Exception as exc:
            self._note(driver, now, RESET_TUNING, False)
            self._log("warning", f"driver watch: resetting the {driver.motor.label} stepper's tuning failed: {exc}")
            return
        driver.tuning_reset_at = now
        driver.due = True

    # -- shared steps ----------------------------------------------------------

    def _resetDriver(self, driver: _Driver, *, clear_shutdown: bool) -> None:
        settings = readStepperSettings(driver.motor)
        resetDriverTuning(
            driver.stepper,
            (settings.irun, settings.ihold, settings.ihold_delay),
            settings.microsteps,
            clear_shutdown=clear_shutdown,
        )

    def _clearStallLatch(self, driver: _Driver) -> None:
        driver.clear_latch = False
        stepper = driver.stepper
        try:
            stepper.clear_stall()
            stepper.enable_stall_detection(bool(getattr(stepper, "stallguard_enabled", False)))
            stepper.stalled = False
        except Exception as exc:
            self._log("warning", f"driver watch: the {driver.motor.label} stepper's stall latch was not cleared: {exc}")

    def _attemptsLeft(self, driver: _Driver, mono: float) -> bool:
        while driver.attempts and mono - driver.attempts[0] >= RECOVERY_WINDOW_S:
            driver.attempts.popleft()
        return len(driver.attempts) < RECOVERY_ATTEMPTS

    def _spend(self, driver: _Driver, mono: float) -> None:
        driver.attempts.append(mono)

    def _note(self, driver: _Driver, when: float, what: str, ok: bool) -> None:
        with self._lock:
            driver.recoveries.append({"t": round(when, 3), "what": what, "ok": ok})
        self._log(
            "info" if ok else "warning",
            f"driver watch: {driver.motor.label} stepper: {what}, {'and it worked' if ok else 'which did not work'}",
        )

    def _stopped(self, stepper: Any) -> bool:
        try:
            return bool(stepper.stopped)
        except Exception:
            return True

    def _chuteOf(self, driver: _Driver) -> Any:
        """The chute, if this is the driver of its motor."""
        chute = getattr(self._irl, "chute", None)
        return chute if chute is not None and getattr(chute, "stepper", None) is driver.stepper else None

    def _controllerLive(self) -> bool:
        from server import shared_state

        return shared_state.controller_ref is not None

    def _homesHere(self) -> bool:
        """Whether a chute that lost its position is homed from here: on a
        homed machine, with nothing starting or homing it."""
        from server import shared_state

        worker = shared_state.hardware_worker_thread
        return (
            shared_state.hardware_state == "ready"
            and not (worker is not None and worker.is_alive())
            and shared_state.controller_ref is not None
            and not getattr(self._gc, "disable_chute", False)
        )

    def _log(self, level: str, message: str) -> None:
        logger = getattr(self._gc, "logger", None)
        getattr(logger if logger is not None else log, level)(message)

    def _logError(self, exc: Exception) -> None:
        if time.monotonic() - self._last_error_log >= ERROR_LOG_INTERVAL_S:
            self._last_error_log = time.monotonic()
            self._log("warning", f"driver watch: {exc}")

    # -- from other threads ----------------------------------------------------

    def claimStall(self, stepper: Any) -> bool:
        """For the stall monitor, when the board latches a stall on `stepper`:
        whether that is its driver having switched itself off, which raises the
        same line as a stall. Then the latch is this watch's to clear, once the
        driver is on again."""
        driver = next((d for d in self._order if d.stepper is stepper), None)
        if driver is None:
            return False
        if driver.outage is None and time.monotonic() - driver.outage_ended >= STALL_CLAIM_S:
            raw = safeReadRegister(stepper, REG_DRV_STATUS)
            if raw is None:
                return False
            drv = decodeDrvStatus(raw)
            if not (drv["ot"] or drv["s2ga"] or drv["s2gb"] or drv["s2vsa"] or drv["s2vsb"]):
                return False
        driver.clear_latch = True
        driver.due = True
        return True

    def retry(self, key: str) -> bool:
        """Try again was pressed for the driver of the motor with this key."""
        for driver in self._order:
            outage = driver.outage
            if driver.motor.key == key and outage is not None:
                outage.retry = True
                driver.due = True
                return True
        return False

    # -- what the pages read -----------------------------------------------------

    def describe(self) -> list[dict[str, Any]]:
        """Every driver under each name the API gives its motor (the
        classification channel's has two), as /api/stepper/{name}/tmc takes them."""
        now = time.time()
        drivers = []
        for name in apiNames():
            driver = self._drivers[motorNamed(name).name]
            with self._lock:
                latest = driver.samples[-1] if driver.samples else None
                recoveries = list(driver.recoveries)
            if latest is not None and (driver.stepper is None or now - latest.t > LATEST_MAX_AGE_S):
                latest = None
            drivers.append(
                {
                    "name": name,
                    "label": NAME_ALIASES[name][1] if name in NAME_ALIASES else driver.label,
                    "latest": samplePayload(latest) if latest is not None else None,
                    "fault": self._fault(driver),
                    "recoveries": recoveries,
                }
            )
        return drivers

    def _fault(self, driver: _Driver) -> dict[str, Any] | None:
        """The worst thing wrong with a driver now."""
        outage = driver.outage
        if outage is not None:
            return {"kind": outage.kind, "since": outage.since, "detail": outage.detail}
        if driver.hot.active:
            return {"kind": OVERHEATING_FAULT, "since": driver.hot.since, "detail": driver.hot_detail}
        if driver.tuning_since is not None:
            return {"kind": TUNING_FAULT, "since": driver.tuning_since, "detail": driver.tuning_detail}
        return None

    def history(self, motor: Motor, seconds: float) -> list[dict[str, Any]]:
        """The motor's readings of the last `seconds`, oldest first, thinned
        (thin): from memory, and what is older than memory holds from what was
        written down."""
        now = time.time()
        since = now - seconds
        with self._lock:
            samples = [s for s in self._drivers[motor.name].samples if s.t >= since]
        if seconds > MEMORY_S:
            until = samples[0].t if samples else now
            samples = [s for s in self._writtenDown(since)[motor.name] if s.t < until] + samples
        return [samplePayload(sample) for sample in thin(samples)]

    # -- what is written down ------------------------------------------------------

    def seed(self, now: float) -> None:
        """Fill memory from what earlier runs wrote down, so a restart keeps
        the charts."""
        try:
            written = self._writtenDown(now - MEMORY_S)
        except Exception as exc:
            log.warning("driver watch: earlier readings not read: %s", exc)
            return
        with self._lock:
            for driver in self._order:
                samples = written[driver.motor.name]
                driver.samples.extend(samples)
                driver.kept = samples[-1] if samples else None

    def _writtenDown(self, since: float) -> dict[str, list[Sample]]:
        """Every driver's readings written down since `since`, oldest first."""
        written: dict[str, list[Sample]] = {name: [] for name in self._drivers}
        for record in telemetry_store.listKind(KIND, since):
            started_at = record["started_at"]
            for name, rows in ((record.get("data") or {}).get("drivers") or {}).items():
                if name not in written:
                    continue
                for row in rows:
                    if isinstance(row, list) and len(row) == len(Sample._fields) and started_at + row[0] >= since:
                        written[name].append(Sample(started_at + row[0], *row[1:]))
        for samples in written.values():
            samples.sort(key=lambda sample: sample.t)
        return written

    def _writeDown(self, now: float, mono: float, everything: bool = False) -> None:
        """Write the readings kept since the last write as telemetry windows,
        when it is time, and drop what is past RETENTION_S."""
        with self._lock:
            count = len(self._pending)
        waited = mono - self._written
        if count == 0:
            return
        if not everything and (
            waited < WRITE_EVERY_S or (count < WRITE_ROWS and waited < WRITE_QUIET_EVERY_S)
        ):
            return
        with self._lock:
            pending, self._pending = self._pending, []
        self._written = mono
        for start in range(0, len(pending), ROWS_PER_RECORD):
            rows = pending[start : start + ROWS_PER_RECORD]
            started_at = min(sample.t for _name, sample in rows)
            drivers: dict[str, list[list[Any]]] = {}
            for name, sample in rows:
                # The time as seconds into the window: shorter than the date.
                drivers.setdefault(name, []).append([round(sample.t - started_at, 2), *sample[1:]])
            telemetry_store.write(
                KIND,
                telemetry_store.FORM_WINDOW,
                {"fields": list(Sample._fields), "drivers": drivers},
                started_at=started_at,
                ended_at=max(sample.t for _name, sample in rows),
                schema=SCHEMA,
            )
        if mono - self._pruned >= PRUNE_EVERY_S:
            self._pruned = mono
            telemetry_store.pruneKind(KIND, now - RETENTION_S)


_service: DriverWatch | None = None
_service_lock = threading.Lock()


def _watch(gc: Any = None) -> DriverWatch:
    """The watch, made at its first use: its readings outlive the hardware."""
    global _service
    with _service_lock:
        if _service is None:
            _service = DriverWatch(gc)
            _service.seed(time.time())
        elif gc is not None:
            _service._gc = gc
        return _service


def _on() -> bool:
    """Whether the drivers are watched: they are being read now, or will be
    when the hardware starts."""
    from server import shared_state

    if _service is not None and _service.attached:
        return True
    # Without motor power the drivers cannot answer.
    if getattr(shared_state.gc_ref, "no_power_development_mode", False):
        return False
    return watchEnabled()


def start(gc: Any, irl: Any) -> None:
    """The hardware started. Nothing happens on a machine that does not watch
    its drivers."""
    if getattr(gc, "no_power_development_mode", False) or not watchEnabled(logger=gc.logger):
        return
    _watch(gc).attach(irl)


def stop() -> None:
    """The hardware is stopping."""
    if _service is not None:
        _service.detach()


def describe() -> dict[str, Any]:
    """GET /api/drivers."""
    if not _on():
        return {"enabled": False, "drivers": []}
    return {"enabled": True, "drivers": _watch().describe()}


def history(motor: Motor, name: str, seconds: float) -> dict[str, Any]:
    """GET /api/drivers/{name}/history."""
    if not _on():
        return {"enabled": False, "name": name, "samples": []}
    return {"enabled": True, "name": name, "samples": _watch().history(motor, seconds)}


def claimStall(stepper: Any) -> bool:
    return _service is not None and _service.claimStall(stepper)


def retry(key: str) -> bool:
    return _service is not None and _service.retry(key)
