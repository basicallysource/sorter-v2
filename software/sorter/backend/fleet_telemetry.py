"""Machine telemetry: how this sorter is set up and how it runs.

Everything here becomes a telemetry_store record, which the sync worker sends
to every Hive on the machine_telemetry stream. None of it is shown to the
person: it is how the fleet's normal behaviour becomes known (how much load a
chute normally sees at its speed, what exposure cameras settle on), so problems
and better defaults can be found across every machine.

One daemon thread runs the probes while the machine sorts. A probe takes a
reading at its own interval and folds it into a summary. After WINDOW_S of
sorting, when sorting stops, or when a probe's settings change, each probe's
summary since the last one becomes a `window` record of the probe's kind; a
probe with nothing to say writes nothing. A measurement is added by adding a
probe to FleetTelemetry's probes.

Besides the windows:
- the machine specs (machine_specs.buildMachineSpecs) are a `snapshot`,
  written at the first complete reading after start and again whenever they
  change, checked every SPECS_CHECK_S;
- a stall (StepperStallMonitor calls noteStall) is a `stepper_stall` event
  with the stepper's settings and its last readings.

The probes:
- StepperLoadProbe (`stepper_load`): one stepper's TMC2209 every TICK_S, round
  robin among the steppers commanded in the last ACTIVE_S, so it adds at most
  three register reads a tick to the bus: DRV_STATUS, then SG_RESULT and TSTEP
  unless the motor stands still. Readings are binned by TSTEP (speed) in
  quarter-octave bands, each band a histogram of SG_RESULT (StallGuard's load
  figure: lower is more load) with the range of CS_ACTUAL.
- CameraReadingsProbe (`camera_readings`): every CAMERA_INTERVAL_S, each USB
  camera's controls as its driver reports them (what auto exposure and white
  balance chose) and its measured frame rate.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from typing import Any

import telemetry_store

log = logging.getLogger(__name__)

TICK_S = 0.25
WINDOW_S = 3600.0
SPECS_CHECK_S = 300.0
# While the hardware is still coming up (no controller boards yet), the specs
# are checked again this soon, for at most SPECS_WAIT_S after start.
SPECS_RETRY_S = 60.0
SPECS_WAIT_S = 600.0
ERROR_LOG_INTERVAL_S = 300.0

# A stepper counts as possibly moving this long after a move was commanded.
ACTIVE_S = 2.0
# A driver that fails this many reads in a row is left alone for a while.
READ_FAILURES_TO_REST = 3
READ_FAILURE_REST_S = 300.0
STEPPER_SETTINGS_CHECK_S = 30.0
SG_BIN_WIDTH = 32
SG_BINS = 16
# Readings kept per stepper for a stall event.
STALL_CONTEXT = 20
# TSTEP's value at standstill (the register is 20 bits).
TSTEP_STANDSTILL = 0xFFFFF

CAMERA_INTERVAL_S = 300.0

REG_TSTEP = 0x12
REG_SG_RESULT = 0x41
REG_DRV_STATUS = 0x6F
_DRV_FLAGS = (
    ("otpw", 0), ("ot", 1), ("s2ga", 2), ("s2gb", 3), ("s2vsa", 4), ("s2vsb", 5),
    ("ola", 6), ("olb", 7), ("t120", 8), ("t143", 9), ("t150", 10), ("t157", 11),
)
_SETTING_FIELDS = (
    "irun", "ihold", "microsteps", "stealthchop", "coolstep",
    "stallguard", "stallguard_auto", "sgthrs", "tcoolthrs",
)


def _sorting(gc: Any) -> bool:
    stats = getattr(gc, "runtime_stats", None)
    return bool(getattr(stats, "is_running", False)) if stats is not None else False


def _activeIrl() -> Any:
    from server import shared_state

    return shared_state.getActiveIRL()


def _readRegister(stepper: Any, address: int) -> int | None:
    try:
        return int(stepper.read_driver_register(address))
    except Exception:
        return None


def tstepBand(tstep: int) -> int:
    """The quarter-octave band of a TSTEP value: band b holds 2^(b/4) up to
    2^((b+1)/4). Speed is inversely proportional to TSTEP."""
    return int(math.floor(4.0 * math.log2(tstep)))


def _bandBounds(band: int) -> list[int]:
    return [math.ceil(2.0 ** (band / 4.0)), math.ceil(2.0 ** ((band + 1) / 4.0))]


def stepperSettings(motor: Any) -> dict[str, Any]:
    from hardware_settings.steppers import readStepperSettings

    settings = readStepperSettings(motor)
    return {name: getattr(settings, name) for name in _SETTING_FIELDS}


class _Band:
    __slots__ = ("n", "sg", "sg_min", "sg_max", "sg_sum", "cs_min", "cs_max", "cs_sum")

    def __init__(self) -> None:
        self.n = 0
        self.sg = [0] * SG_BINS
        self.sg_min: int | None = None
        self.sg_max: int | None = None
        self.sg_sum = 0
        self.cs_min: int | None = None
        self.cs_max: int | None = None
        self.cs_sum = 0

    def add(self, sg: int, cs: int) -> None:
        self.n += 1
        self.sg[min(sg // SG_BIN_WIDTH, SG_BINS - 1)] += 1
        self.sg_min = sg if self.sg_min is None else min(self.sg_min, sg)
        self.sg_max = sg if self.sg_max is None else max(self.sg_max, sg)
        self.sg_sum += sg
        self.cs_min = cs if self.cs_min is None else min(self.cs_min, cs)
        self.cs_max = cs if self.cs_max is None else max(self.cs_max, cs)
        self.cs_sum += cs


class _StepperWindow:
    def __init__(self) -> None:
        self.samples = 0
        self.standstill = 0
        self.stalls = 0
        self.flags: dict[str, int] = {}
        self.bands: dict[int, _Band] = {}

    def summary(self, settings: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "standstill": self.standstill,
            "stalls": self.stalls,
            "settings": settings,
            "flags": dict(sorted(self.flags.items())),
            "bands": [
                {
                    "tstep": _bandBounds(band),
                    "n": b.n,
                    "sg": b.sg,
                    "sg_min": b.sg_min,
                    "sg_max": b.sg_max,
                    "sg_sum": b.sg_sum,
                    "cs_min": b.cs_min,
                    "cs_max": b.cs_max,
                    "cs_sum": b.cs_sum,
                }
                for band, b in sorted(self.bands.items())
            ],
        }


class StepperLoadProbe:
    kind = "stepper_load"
    schema = 1
    interval_s = TICK_S

    def __init__(self) -> None:
        from hardware_settings.motors import MOTORS

        self._motors = MOTORS
        self._lock = threading.Lock()
        self._windows: dict[str, _StepperWindow] = {}
        self._recent: dict[str, deque[list[Any]]] = {motor.name: deque(maxlen=STALL_CONTEXT) for motor in MOTORS}
        # Each motor's settings now, and as they were when the window began
        # (a change of settings closes the window, see FleetTelemetry.tick).
        self._settings: dict[str, dict[str, Any]] = {}
        self._window_settings: dict[str, dict[str, Any]] = {}
        self._settings_checked_at = 0.0
        self._next = 0
        # Per motor: reads failed in a row, and until when it is left alone.
        self._failures: dict[str, int] = {}
        self._resting_until: dict[str, float] = {}

    def _refreshSettings(self, now: float) -> None:
        if now - self._settings_checked_at < STEPPER_SETTINGS_CHECK_S and self._settings:
            return
        self._settings_checked_at = now
        fresh: dict[str, dict[str, Any]] = {}
        for motor in self._motors:
            try:
                fresh[motor.name] = stepperSettings(motor)
            except Exception:
                continue
        with self._lock:
            self._settings = fresh

    def settingsKey(self) -> Any:
        with self._lock:
            return sorted((name, sorted(values.items())) for name, values in self._settings.items())

    def _candidate(self, irl: Any, now: float) -> tuple[Any, Any] | None:
        count = len(self._motors)
        for offset in range(count):
            index = (self._next + offset) % count
            motor = self._motors[index]
            stepper = getattr(irl, motor.attr, None)
            if stepper is None or self._resting_until.get(motor.name, 0.0) > now:
                continue
            commanded = getattr(stepper, "last_commanded_at", None)
            if getattr(stepper, "running_at_speed", False) or (
                isinstance(commanded, float) and now - commanded < ACTIVE_S
            ):
                self._next = index + 1
                return motor, stepper
        return None

    def sample(self, irl: Any, now: float) -> None:
        if irl is None:
            return
        self._refreshSettings(now)
        picked = self._candidate(irl, now)
        if picked is None:
            return
        motor, stepper = picked
        drv = _readRegister(stepper, REG_DRV_STATUS)
        if drv is None:
            failures = self._failures.get(motor.name, 0) + 1
            self._failures[motor.name] = failures
            if failures >= READ_FAILURES_TO_REST:
                self._failures[motor.name] = 0
                self._resting_until[motor.name] = now + READ_FAILURE_REST_S
                log.warning("fleet telemetry: %s's driver did not answer %d reads; leaving it %.0f s", motor.name, failures, READ_FAILURE_REST_S)
            return
        self._failures[motor.name] = 0
        standstill = bool(drv & (1 << 31))
        cs = (drv >> 16) & 0x1F
        sg = tstep = None
        if not standstill:
            sg = _readRegister(stepper, REG_SG_RESULT)
            tstep = _readRegister(stepper, REG_TSTEP)
        with self._lock:
            if not self._windows:
                self._window_settings = dict(self._settings)
            window = self._windows.setdefault(motor.name, _StepperWindow())
            window.samples += 1
            for name, bit in _DRV_FLAGS:
                if drv & (1 << bit):
                    window.flags[name] = window.flags.get(name, 0) + 1
            if standstill:
                window.standstill += 1
            elif sg is not None and tstep is not None and 0 < tstep < TSTEP_STANDSTILL and 0 <= sg <= 1023:
                window.bands.setdefault(tstepBand(tstep), _Band()).add(sg, cs)
            self._recent[motor.name].append([round(now, 3), sg, tstep, cs, standstill])

    def noteStall(self, name: str, now: float) -> dict[str, Any] | None:
        """The event data for a stall of the motor called `name` (its API name
        or its board socket), counted in the current window."""
        motor = next((m for m in self._motors if name in (m.name, m.key, *m.aliases)), None)
        if motor is None:
            return None
        with self._lock:
            self._windows.setdefault(motor.name, _StepperWindow()).stalls += 1
            recent = [[round(r[0] - now, 3), *r[1:]] for r in self._recent[motor.name]]
            settings = dict(self._settings.get(motor.name) or {})
        if not settings:
            try:
                settings = stepperSettings(motor)
            except Exception:
                settings = {}
        return {"stepper": motor.name, "settings": settings, "recent": recent}

    def summary(self) -> dict[str, Any] | None:
        with self._lock:
            windows, self._windows = self._windows, {}
            settings, self._window_settings = self._window_settings, {}
        if not windows:
            return None
        return {
            "sample_interval_s": TICK_S,
            "sg_bin_width": SG_BIN_WIDTH,
            "steppers": {name: window.summary(settings.get(name)) for name, window in sorted(windows.items())},
        }


class _Range:
    __slots__ = ("n", "min", "max", "sum", "last")

    def __init__(self) -> None:
        self.n = 0
        self.min: float | None = None
        self.max: float | None = None
        self.sum = 0.0
        self.last: float | None = None

    def add(self, value: float) -> None:
        if not math.isfinite(value):
            return
        self.n += 1
        self.min = value if self.min is None else min(self.min, value)
        self.max = value if self.max is None else max(self.max, value)
        self.sum += value
        self.last = value

    def summary(self) -> dict[str, Any]:
        return {
            "min": self.min,
            "max": self.max,
            "mean": round(self.sum / self.n, 2) if self.n else None,
            "last": self.last,
        }


class _CameraWindow:
    def __init__(self, model: str | None) -> None:
        self.model = model
        self.n = 0
        self.fps = _Range()
        self.controls: dict[str, _Range] = {}

    def summary(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "model": self.model,
            "fps": self.fps.summary() if self.fps.n else None,
            "controls": {key: r.summary() for key, r in sorted(self.controls.items())},
        }


class CameraReadingsProbe:
    kind = "camera_readings"
    schema = 1
    interval_s = CAMERA_INTERVAL_S

    def __init__(self) -> None:
        self._windows: dict[str, _CameraWindow] = {}
        # Per role: (frames captured, monotonic time) at the last reading.
        self._frames: dict[str, tuple[int, float]] = {}

    def settingsKey(self) -> Any:
        return None

    def sample(self, irl: Any, now: float) -> None:
        from machine_specs import v4l2CameraModel
        from server import shared_state
        from vision.camera import read_v4l2_control_values

        service = shared_state.camera_service
        devices = service.devices if service is not None else {}
        seen: set[int] = set()
        for role, device in list((devices or {}).items()):
            if id(device) in seen:
                continue  # an alias of a role already read (the carousel is C4)
            seen.add(id(device))
            capture = getattr(device, "capture_thread", None)
            source = capture.getCameraSource() if capture is not None else None
            if not isinstance(source, int) or isinstance(source, bool) or source < 0:
                continue
            window = self._windows.get(role)
            if window is None:
                window = self._windows[role] = _CameraWindow(v4l2CameraModel(source))
            window.n += 1
            for key, value in read_v4l2_control_values(source).items():
                window.controls.setdefault(key, _Range()).add(value)
            frames = int(getattr(capture, "frames_captured", 0) or 0)
            previous = self._frames.get(role)
            if previous is not None and now > previous[1] and frames >= previous[0]:
                window.fps.add(round((frames - previous[0]) / (now - previous[1]), 2))
            self._frames[role] = (frames, now)

    def summary(self) -> dict[str, Any] | None:
        windows, self._windows = self._windows, {}
        # A frame rate spans one reading to the next; a new window starts afresh.
        self._frames = {}
        if not windows:
            return None
        return {
            "sample_interval_s": CAMERA_INTERVAL_S,
            "cameras": {role: window.summary() for role, window in sorted(windows.items())},
        }


class FleetTelemetry:
    def __init__(self, gc: Any) -> None:
        self._gc = gc
        self._steppers = StepperLoadProbe()
        self._probes: tuple[Any, ...] = (self._steppers, CameraReadingsProbe())
        self._next_at: dict[str, float] = {probe.kind: 0.0 for probe in self._probes}
        self._window_started_at: float | None = None
        self._window_sorting_s = 0.0
        self._window_keys: dict[str, Any] = {}
        self._last_tick: float | None = None
        self._started = time.monotonic()
        self._specs_next_at = 0.0
        self._specs_last: dict[str, Any] | None = None
        self._last_error_log = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="fleet-telemetry")

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick(time.monotonic(), time.time())
            except Exception as exc:
                if time.monotonic() - self._last_error_log >= ERROR_LOG_INTERVAL_S:
                    self._last_error_log = time.monotonic()
                    log.warning("fleet telemetry: %s", exc)
            self._stop.wait(TICK_S)

    def shutdown(self) -> None:
        """Stop, keeping the window under way (the backend is shutting down)."""
        self._stop.set()
        self._thread.join(timeout=2.0)
        if self._window_started_at is not None:
            self._closeWindow(time.time())

    def tick(self, now: float, wall: float) -> None:
        running = _sorting(self._gc)
        if running:
            irl = _activeIrl()
            if self._window_started_at is None:
                self._window_started_at = wall
                self._window_sorting_s = 0.0
                self._window_keys = {}
            elif self._last_tick is not None:
                self._window_sorting_s += min(now - self._last_tick, 4 * TICK_S)
            for probe in self._probes:
                if now >= self._next_at[probe.kind]:
                    self._next_at[probe.kind] = now + probe.interval_s
                    probe.sample(irl, now)
                key = probe.settingsKey()
                if probe.kind not in self._window_keys:
                    self._window_keys[probe.kind] = key
                elif key != self._window_keys[probe.kind]:
                    self._closeWindow(wall)
                    break
        if self._window_started_at is not None and (
            not running or wall - self._window_started_at >= WINDOW_S
        ):
            self._closeWindow(wall)
        self._last_tick = now if running else None
        if now >= self._specs_next_at:
            self.checkSpecs(now)

    def _closeWindow(self, wall: float) -> None:
        started_at = self._window_started_at
        sorting_s = round(self._window_sorting_s, 1)
        self._window_started_at = None
        self._window_sorting_s = 0.0
        self._window_keys = {}
        if started_at is None:
            return
        for probe in self._probes:
            data = probe.summary()
            if data is None:
                continue
            data["sorting_s"] = sorting_s
            self._write(probe.kind, telemetry_store.FORM_WINDOW, data, started_at, wall, probe.schema)

    def checkSpecs(self, now: float) -> None:
        from machine_specs import buildMachineSpecs

        specs = buildMachineSpecs()
        if not specs.get("controller_boards") and self._specs_last is None and now - self._started < SPECS_WAIT_S:
            self._specs_next_at = now + SPECS_RETRY_S
            return
        self._specs_next_at = now + SPECS_CHECK_S
        stable = {key: value for key, value in specs.items() if key != "captured_at"}
        if stable == self._specs_last:
            return
        if self._write("machine_specs", telemetry_store.FORM_SNAPSHOT, specs, time.time(), None, 1) is not None:
            self._specs_last = stable

    def noteStall(self, names: list[str]) -> None:
        """StepperStallMonitor saw these motors stall (their board socket names)."""
        now = time.monotonic()
        wall = time.time()
        for name in names:
            try:
                data = self._steppers.noteStall(name, now)
            except Exception as exc:
                log.warning("fleet telemetry: stall of %s not recorded: %s", name, exc)
                continue
            if data is None:
                continue
            data["sorting"] = _sorting(self._gc)
            self._write("stepper_stall", telemetry_store.FORM_EVENT, data, wall, None, 1)

    def _write(
        self, kind: str, form: str, data: dict[str, Any], started_at: float, ended_at: float | None, schema: int,
    ) -> int | None:
        try:
            record_id = telemetry_store.write(kind, form, data, started_at=started_at, ended_at=ended_at, schema=schema)
        except Exception as exc:
            log.warning("fleet telemetry: %s %s not written: %s", kind, form, exc)
            return None
        if record_id is None:
            log.warning("fleet telemetry: %s %s too large to keep", kind, form)
        return record_id


_service: FleetTelemetry | None = None


def start(gc: Any) -> FleetTelemetry:
    global _service
    _service = FleetTelemetry(gc)
    _service.start()
    return _service


def noteStall(names: list[str]) -> None:
    if _service is not None:
        _service.noteStall(names)


def shutdown() -> None:
    if _service is not None:
        _service.shutdown()
