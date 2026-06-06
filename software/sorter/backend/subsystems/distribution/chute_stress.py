"""Chute stress-test loop runner.

Drives the chute back and forth between angles for endurance / wear testing.
Runs in a background thread; exposes start/pause/resume/stop and live progress.
"""
from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

import stepper_telemetry
import tmc_telemetry
from global_config import GlobalConfig
from hardware.sorter_interface import DISABLE_STALLGUARD
from local_state import (
    finalizeChuteStressRun,
    recordChuteStressRunStart,
    updateChuteStressRunProgress,
)
from subsystems.distribution.chute import GEAR_RATIO, HOME_SPEED_MICROSTEPS_PER_SEC, HOME_TIMEOUT_MS, Chute

_TELEMETRY_STATUS_MAP = {
    "completed": stepper_telemetry.RUN_STATUS_COMPLETED,
    "stopped": stepper_telemetry.RUN_STATUS_ABORTED,
    "failed": stepper_telemetry.RUN_STATUS_ERROR,
    "stalled": stepper_telemetry.RUN_STATUS_ABORTED,
}

StressMode = Literal["sweep", "random"]
RunStatus = Literal[
    "running", "paused", "stopping", "completed", "stopped", "failed", "stalled"
]

CHUTE_MAX_ANGLE_LIMIT_DEG = 345.0
LEG_TIMEOUT_BUFFER_S = 5.0
POLL_INTERVAL_S = 0.02
MIN_RANDOM_DELTA_DEG = 5.0
MIN_RANDOM_ANGLE_DEG = 5.0

# The chute UART bus is marginal and occasionally returns a garbled/partial reply
# to a command. A single corrupted ack should not abort a whole run, so retry the
# move a few times, and tolerate a few unreadable stop-status polls per leg.
MOVE_ACCEPT_RETRIES = 4
MOVE_ACCEPT_RETRY_DELAY_S = 0.15
STOPPED_READ_ERROR_TOLERANCE = 5

# A StallGuard stall must HALT the run into a terminal "stalled" state rather than
# silently rolling into the next leg. The only trustworthy stall signal is the
# firmware's sticky per-channel DIAG latch (read_stall_latched) — a rejected move
# or a garbled bus ack is NOT a stall and must never trip this. The same chute bus
# that hands back partial frames could also corrupt a single stall-status read, so
# we require the latch to read set on several consecutive CLEAN reads; any clean
# read with the bit clear proves "not stalled" and aborts the check immediately.
STALL_CONFIRM_READS = 3
STALL_CONFIRM_READ_DELAY_S = 0.04


@dataclass
class StressTestParams:
    mode: StressMode
    target_max_deg: float
    duration_s: float
    speed_microsteps_per_sec: int
    invert_direction: bool = False


@dataclass
class StressTestState:
    run_id: str
    params: StressTestParams
    started_at: float
    status: RunStatus = "running"
    total_distance_deg: float = 0.0
    elapsed_s: float = 0.0
    ended_at: float | None = None
    error: str | None = None
    last_target_deg: float | None = None
    telemetry_run_id: str | None = None
    stalled_at_deg: float | None = None

    def toDict(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "mode": self.params.mode,
            "target_max_deg": self.params.target_max_deg,
            "duration_target_s": self.params.duration_s,
            "speed_microsteps_per_sec": self.params.speed_microsteps_per_sec,
            "invert_direction": self.params.invert_direction,
            "status": self.status,
            "total_distance_deg": self.total_distance_deg,
            "total_time_s": self.elapsed_s,
            "last_target_deg": self.last_target_deg,
            "telemetry_run_id": self.telemetry_run_id,
            "stalled_at_deg": self.stalled_at_deg,
            "error": self.error,
        }


def _snapshot(state: StressTestState) -> StressTestState:
    return StressTestState(
        run_id=state.run_id,
        params=state.params,
        started_at=state.started_at,
        status=state.status,
        total_distance_deg=state.total_distance_deg,
        elapsed_s=state.elapsed_s,
        ended_at=state.ended_at,
        error=state.error,
        last_target_deg=state.last_target_deg,
        telemetry_run_id=state.telemetry_run_id,
        stalled_at_deg=state.stalled_at_deg,
    )


class ChuteStressTestRunner:
    def __init__(self, gc: GlobalConfig, chute: Chute) -> None:
        self.gc = gc
        self.logger = gc.logger
        self.chute = chute
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._state: StressTestState | None = None

    def isActive(self) -> bool:
        with self._lock:
            t = self._thread
            return bool(t is not None and t.is_alive())

    def getState(self) -> StressTestState | None:
        with self._lock:
            return _snapshot(self._state) if self._state is not None else None

    def start(self, params: StressTestParams) -> StressTestState:
        with self._lock:
            if self.isActive():
                raise RuntimeError("A chute stress test is already running")
            if params.target_max_deg <= 0 or params.target_max_deg > CHUTE_MAX_ANGLE_LIMIT_DEG:
                raise ValueError(
                    f"target_max_deg must be in (0, {CHUTE_MAX_ANGLE_LIMIT_DEG}]"
                )
            if params.duration_s <= 0:
                raise ValueError("duration_s must be > 0")
            if params.speed_microsteps_per_sec <= 0:
                raise ValueError("speed_microsteps_per_sec must be > 0")
            if params.mode not in ("sweep", "random"):
                raise ValueError("mode must be 'sweep' or 'random'")

            now = time.time()
            run_id = str(uuid.uuid4())
            recordChuteStressRunStart(
                run_id=run_id,
                started_at=now,
                mode=params.mode,
                target_max_deg=params.target_max_deg,
                duration_target_s=params.duration_s,
                speed_microsteps_per_sec=params.speed_microsteps_per_sec,
            )
            self._state = StressTestState(
                run_id=run_id,
                params=params,
                started_at=now,
            )
            self._stop_event.clear()
            self._pause_event.set()
            self._thread = threading.Thread(
                target=self._run, name="ChuteStressTest", daemon=True
            )
            self._thread.start()
            return _snapshot(self._state)

    def pause(self) -> None:
        with self._lock:
            if not self.isActive() or self._state is None:
                raise RuntimeError("No chute stress test is running")
            if self._state.status in ("paused", "stopping"):
                return
            self._pause_event.clear()
            self._state.status = "paused"
        self.logger.info("Chute stress: pause requested (will hold after current leg)")

    def resume(self) -> None:
        with self._lock:
            if not self.isActive() or self._state is None:
                raise RuntimeError("No chute stress test is running")
            if self._state.status != "paused":
                return
            self._state.status = "running"
            self._pause_event.set()
        self.logger.info("Chute stress: resumed")

    def stop(self) -> None:
        with self._lock:
            if self._state is None:
                raise RuntimeError("No chute stress test is running")
            self._stop_event.set()
            self._pause_event.set()
            if self._state.status not in ("completed", "stopped", "failed"):
                self._state.status = "stopping"
        self.logger.info("Chute stress: stop requested")

    def _pickNextTarget(self, current_deg: float) -> float | None:
        # Returns None to signal that sweep should home rather than move to a position.
        assert self._state is not None
        params = self._state.params
        max_deg = params.target_max_deg
        if params.mode == "sweep":
            last = self._state.last_target_deg
            if last is None or last < max_deg / 2.0:
                return max_deg
            return None  # home leg
        min_deg = max(MIN_RANDOM_ANGLE_DEG, float(self.chute.first_bin_center or 0.0))
        for _ in range(10):
            candidate = random.uniform(min_deg, max_deg)
            if abs(candidate - current_deg) >= MIN_RANDOM_DELTA_DEG:
                return candidate
        return max_deg if current_deg < max_deg / 2.0 else min_deg

    def _homeToZero(self) -> float:
        assert self._state is not None
        stepper = self.chute.stepper
        current_deg = self.chute.current_angle
        timeout_s = (HOME_TIMEOUT_MS / 1000.0) + LEG_TIMEOUT_BUFFER_S

        stepper.enabled = True
        stepper.home(
            HOME_SPEED_MICROSTEPS_PER_SEC,
            self.chute.home_pin,
            home_pin_active_high=self.chute.endstop_active_high,
        )

        leg_start = time.monotonic()
        while True:
            if self._stop_event.is_set():
                self._halt()
                break
            try:
                if stepper.stopped:
                    break
            except Exception:
                self._halt()
                break
            if (time.monotonic() - leg_start) > timeout_s:
                self.logger.warning("Chute stress: home leg timed out")
                self._halt()
                break
            time.sleep(POLL_INTERVAL_S)

        try:
            final_deg = self.chute.current_angle
            return abs(final_deg - current_deg)
        except Exception:
            return abs(current_deg)

    def _confirmStall(self) -> bool:
        # Only return True for a stall we're confident about. The firmware DIAG
        # latch is sticky, so a genuine stall reads set on every clean poll; a
        # transient corrupt frame on the chute bus can't fake that across several
        # reads, and a single clean "bit clear" read is proof the leg simply ended
        # normally (no stall) — not the bus error this run otherwise tolerates.
        if DISABLE_STALLGUARD:
            return False
        stepper = self.chute.stepper
        reader = getattr(stepper, "read_stall_latched", None)
        if not callable(reader):
            return False
        confirmations = 0
        for _ in range(STALL_CONFIRM_READS):
            try:
                if reader():
                    confirmations += 1
                else:
                    return False
            except Exception:
                pass  # unreadable poll — neither confirms nor denies; try again
            self._stop_event.wait(STALL_CONFIRM_READ_DELAY_S)
        return confirmations >= STALL_CONFIRM_READS

    def _halt(self) -> None:
        stepper = self.chute.stepper
        halt = getattr(stepper, "halt", None)
        try:
            if callable(halt):
                halt(disable_driver=False)
            else:
                if not bool(stepper.stopped):
                    stepper.move_at_speed(0)
        except Exception as e:
            self.logger.warning(f"Chute stress: halt failed: {e}")

    def _moveTo(self, target_deg: float) -> float:
        assert self._state is not None
        stepper = self.chute.stepper
        current_deg = self.chute.current_angle
        target_deg = max(0.0, min(CHUTE_MAX_ANGLE_LIMIT_DEG, target_deg))
        delta_output = target_deg - current_deg
        if abs(delta_output) < 0.01:
            return 0.0
        delta_motor = delta_output * GEAR_RATIO * (-1 if self._state.params.invert_direction else 1)

        try:
            est_ms = stepper.estimateMoveDegreesMs(
                delta_motor,
                max_speed=self._state.params.speed_microsteps_per_sec,
            )
        except Exception:
            est_ms = 5000
        timeout_s = (est_ms / 1000.0) + LEG_TIMEOUT_BUFFER_S

        stepper.enabled = True
        accepted = False
        last_err: Exception | None = None
        for attempt in range(MOVE_ACCEPT_RETRIES):
            if self._stop_event.is_set():
                return 0.0
            try:
                if bool(stepper.move_degrees(delta_motor)):
                    accepted = True
                    break
            except Exception as e:
                last_err = e
            # A garbled/partial bus reply can make a move that actually landed look
            # rejected (the command TX is one-way and usually arrives). If the
            # stepper is moving now, the command took — proceed instead of resending.
            try:
                if not bool(stepper.stopped):
                    accepted = True
                    break
            except Exception:
                pass
            self.logger.warning(
                f"Chute stress: move to {target_deg:.1f}° not accepted, retrying "
                f"({attempt + 1}/{MOVE_ACCEPT_RETRIES})"
                + (f": {last_err}" if last_err is not None else "")
            )
            self._stop_event.wait(MOVE_ACCEPT_RETRY_DELAY_S)
        if not accepted:
            raise RuntimeError(
                f"Stepper did not accept move_degrees after {MOVE_ACCEPT_RETRIES} attempts"
                + (f" (last error: {last_err})" if last_err is not None else "")
            )

        leg_start = time.monotonic()
        stopped_read_errors = 0
        while True:
            if self._stop_event.is_set():
                self._halt()
                break
            try:
                if stepper.stopped:
                    break
                stopped_read_errors = 0
            except Exception as e:
                # Tolerate transient bus hiccups on the stop-status poll; only give
                # up the leg after several consecutive unreadable polls. The timeout
                # below still bounds a genuine hang.
                stopped_read_errors += 1
                if stopped_read_errors >= STOPPED_READ_ERROR_TOLERANCE:
                    self.logger.warning(
                        f"Chute stress: stop-status unreadable {stopped_read_errors}x, "
                        f"halting leg to {target_deg:.1f}°: {e}"
                    )
                    self._halt()
                    break
            if (time.monotonic() - leg_start) > timeout_s:
                self.logger.warning(
                    f"Chute stress: leg to {target_deg:.1f}° exceeded {timeout_s:.1f}s timeout"
                )
                self._halt()
                break
            time.sleep(POLL_INTERVAL_S)

        # Use actual final position to record true distance traveled
        try:
            final_deg = self.chute.current_angle
            return abs(final_deg - current_deg)
        except Exception:
            return abs(delta_output)

    def _startTelemetry(self, stepper: Any) -> tmc_telemetry.TmcTelemetryRecorder | None:
        # Best-effort: a telemetry failure must never abort the actual hardware test.
        assert self._state is not None
        try:
            snapshot = tmc_telemetry.readDriverSettingsSnapshot(stepper)
            decoded = snapshot.get("decoded", {})
            gconf = decoded.get("gconf", {})
            chopconf = decoded.get("chopconf", {})
            current = getattr(stepper, "last_set_current", None)
            irun = current.get("irun") if isinstance(current, dict) else None
            telemetry_run_id = stepper_telemetry.createRun(
                stepper_telemetry.SOURCE_CHUTE_STRESS,
                stepper_name="chute_stepper",
                label=self._state.params.mode,
                params=snapshot,
                machine_id=getattr(self.gc, "machine_id", None),
                chute_stress_run_id=self._state.run_id,
            )
            recorder = tmc_telemetry.TmcTelemetryRecorder(
                self.gc,
                stepper,
                telemetry_run_id=telemetry_run_id,
                stepper_name="chute_stepper",
                commanded_speed=int(self._state.params.speed_microsteps_per_sec),
                stealthchop=gconf.get("stealthchop"),
                microsteps=chopconf.get("microsteps") or getattr(stepper, "_microsteps", None),
                irun=irun,
            )
            recorder.start()
            with self._lock:
                self._state.telemetry_run_id = telemetry_run_id
            self.logger.info(
                f"Chute stress: telemetry recording started (run {telemetry_run_id})"
            )
            return recorder
        except Exception as e:
            self.logger.warning(f"Chute stress: telemetry recording unavailable: {e}")
            return None

    def _run(self) -> None:
        assert self._state is not None
        params = self._state.params
        stepper = self.chute.stepper
        prev_operating_speed = int(self.chute.operating_speed_microsteps_per_second)
        recorder: tmc_telemetry.TmcTelemetryRecorder | None = None

        try:
            stepper.set_speed_limits(
                min_speed=16,
                max_speed=int(params.speed_microsteps_per_sec),
            )
            self.chute.setOperatingSpeed(int(params.speed_microsteps_per_sec))
            recorder = self._startTelemetry(stepper)

            start_monotonic = time.monotonic()
            last_persist = 0.0
            while True:
                if self._stop_event.is_set():
                    break
                self._pause_event.wait()
                if self._stop_event.is_set():
                    break

                elapsed = time.monotonic() - start_monotonic
                if elapsed >= params.duration_s:
                    break

                target = self._pickNextTarget(self.chute.current_angle)
                with self._lock:
                    self._state.last_target_deg = target if target is not None else 0.0

                if target is None:
                    distance = self._homeToZero()
                else:
                    distance = self._moveTo(target)
                with self._lock:
                    self._state.total_distance_deg += distance
                    self._state.elapsed_s = time.monotonic() - start_monotonic

                # A firmware-latched stall ends the run here, in a terminal
                # "stalled" state, instead of rolling into the next leg. Skip the
                # check when we're already stopping — a user halt is not a stall.
                if not self._stop_event.is_set() and self._confirmStall():
                    self._halt()
                    try:
                        stall_deg = self.chute.current_angle
                    except Exception:
                        stall_deg = None
                    target_desc = "home" if target is None else f"{target:.1f}°"
                    where = f"{stall_deg:.1f}°" if stall_deg is not None else "unknown angle"
                    message = (
                        f"StallGuard stall confirmed at {where} "
                        f"(leg target {target_desc})"
                    )
                    self.logger.error(f"Chute stress: {message}; halting run.")
                    with self._lock:
                        self._state.status = "stalled"
                        self._state.stalled_at_deg = stall_deg
                        self._state.error = message
                        self._state.ended_at = time.time()
                    break

                now = time.monotonic()
                if now - last_persist >= 1.0:
                    last_persist = now
                    updateChuteStressRunProgress(
                        run_id=self._state.run_id,
                        total_distance_deg=self._state.total_distance_deg,
                        total_time_s=self._state.elapsed_s,
                    )

            with self._lock:
                if self._state.status != "stalled":
                    self._state.status = (
                        "stopped" if self._stop_event.is_set() else "completed"
                    )
                    self._state.ended_at = time.time()
        except Exception as exc:
            self.logger.error(f"Chute stress test failed: {exc}", exc_info=True)
            self._halt()
            with self._lock:
                if self._state is not None:
                    self._state.status = "failed"
                    self._state.error = str(exc)
                    self._state.ended_at = time.time()
        finally:
            if recorder is not None:
                final_status = self._state.status if self._state is not None else "stopped"
                telemetry_status = _TELEMETRY_STATUS_MAP.get(
                    final_status, stepper_telemetry.RUN_STATUS_ABORTED
                )
                recorder.stop(
                    status=telemetry_status,
                    error=self._state.error if self._state is not None else None,
                )
            try:
                stepper.set_speed_limits(
                    min_speed=16,
                    max_speed=int(prev_operating_speed),
                )
                self.chute.setOperatingSpeed(int(prev_operating_speed))
            except Exception as e:
                self.logger.warning(
                    f"Chute stress: failed to restore operating speed: {e}"
                )
            if self._state is not None:
                finalizeChuteStressRun(
                    run_id=self._state.run_id,
                    ended_at=self._state.ended_at or time.time(),
                    status=self._state.status,
                    total_distance_deg=self._state.total_distance_deg,
                    total_time_s=self._state.elapsed_s,
                    error=self._state.error,
                )


_runner_lock = threading.Lock()
_runner: ChuteStressTestRunner | None = None


def getChuteStressRunner(gc: GlobalConfig, chute: Chute) -> ChuteStressTestRunner:
    """Get or create the singleton stress-test runner bound to the given chute."""
    global _runner
    with _runner_lock:
        if _runner is None or _runner.chute is not chute:
            if _runner is not None and _runner.isActive():
                raise RuntimeError(
                    "A chute stress test is running against a different chute instance"
                )
            _runner = ChuteStressTestRunner(gc, chute)
        return _runner


def getActiveChuteStressRunner() -> ChuteStressTestRunner | None:
    with _runner_lock:
        return _runner
