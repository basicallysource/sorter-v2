from __future__ import annotations

import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from global_config import GlobalConfig
from local_state import (
    finalizePowerStressRun,
    get_led_state,
    recordPowerStressEvent,
    recordPowerStressRunStart,
    updatePowerStressRunProgress,
)
from subsystems.distribution.chute_stress import (
    CHUTE_MAX_ANGLE_LIMIT_DEG,
    StressTestParams,
    getActiveChuteStressRunner,
    getChuteStressRunner,
)

DEFAULT_DURATION_S = 600.0
DEFAULT_STEPPER_SPEED = 6000
DEFAULT_CHUTE_SPEED = 3000
DEFAULT_CHUTE_MAX_DEG = 345.0
MIN_DURATION_S = 10.0
MAX_DURATION_S = 3600.0
MIN_SPEED = 16
SAFE_ACCELERATION = 10000
POLL_INTERVAL_S = 0.04
STOP_TIMEOUT_S = 5.0
RANDOM_RUN_MIN_S = 0.3
RANDOM_RUN_MAX_S = 1.4
RANDOM_STOP_MIN_S = 0.03
RANDOM_STOP_MAX_S = 0.15

PowerStressStatus = Literal["running", "stopping", "completed", "stopped", "failed"]
PhaseMode = Literal["stable", "random", "mixed"]


@dataclass(frozen=True)
class PhaseSegment:
    phase: PhaseMode
    segment: int
    duration_s: float


@dataclass(frozen=True)
class PowerStressParams:
    duration_s: float = DEFAULT_DURATION_S
    stepper_speed_microsteps_per_sec: int = DEFAULT_STEPPER_SPEED
    chute_speed_microsteps_per_sec: int = DEFAULT_CHUTE_SPEED
    chute_max_deg: float = DEFAULT_CHUTE_MAX_DEG


@dataclass
class PowerStressState:
    run_id: str
    params: PowerStressParams
    started_at: float
    status: PowerStressStatus = "running"
    elapsed_s: float = 0.0
    ended_at: float | None = None
    current_phase: str | None = "preparing"
    current_segment: int = 0
    error: str | None = None
    hardware: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def toDict(self) -> dict[str, Any]:
        return {
            "id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_target_s": self.params.duration_s,
            "stepper_speed_microsteps_per_sec": self.params.stepper_speed_microsteps_per_sec,
            "chute_speed_microsteps_per_sec": self.params.chute_speed_microsteps_per_sec,
            "chute_max_deg": self.params.chute_max_deg,
            "status": self.status,
            "total_time_s": self.elapsed_s,
            "current_phase": self.current_phase,
            "current_segment": self.current_segment,
            "error": self.error,
            "hardware": dict(self.hardware),
            "events": [dict(event) for event in self.events],
        }


def buildPhasePlan(duration_s: float) -> list[PhaseSegment]:
    stable_s = duration_s / 3.0
    random_s = duration_s / 3.0
    mixed_s = max(0.0, duration_s - stable_s - random_s)
    plan = [
        PhaseSegment("stable", 1, stable_s),
        PhaseSegment("random", 1, random_s),
    ]
    if mixed_s <= 0:
        return plan
    block_s = max(10.0, min(45.0, mixed_s / 4.0))
    remaining_s = mixed_s
    segment = 1
    while remaining_s > 0.001:
        segment_s = min(block_s, remaining_s)
        plan.append(PhaseSegment("mixed", segment, segment_s))
        remaining_s -= segment_s
        segment += 1
    return plan


def _snapshot(state: PowerStressState) -> PowerStressState:
    return PowerStressState(
        run_id=state.run_id,
        params=state.params,
        started_at=state.started_at,
        status=state.status,
        elapsed_s=state.elapsed_s,
        ended_at=state.ended_at,
        current_phase=state.current_phase,
        current_segment=state.current_segment,
        error=state.error,
        hardware=dict(state.hardware),
        events=[dict(event) for event in state.events],
    )


class PowerStressTestRunner:
    def __init__(self, gc: GlobalConfig, irl: Any) -> None:
        self.gc = gc
        self.logger = gc.logger
        self.irl = irl
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._state: PowerStressState | None = None
        self._rng = random.Random()

    def isActive(self) -> bool:
        with self._lock:
            return bool(self._thread is not None and self._thread.is_alive())

    def getState(self) -> PowerStressState | None:
        with self._lock:
            return _snapshot(self._state) if self._state is not None else None

    def start(self, params: PowerStressParams) -> PowerStressState:
        with self._lock:
            if self.isActive():
                raise RuntimeError("A power stress test is already running")
            self._validateParams(params)
            hardware = self._hardwareSummary()
            self._validateHardware(hardware)
            started_at = time.time()
            run_id = str(uuid.uuid4())
            plan = buildPhasePlan(params.duration_s)
            config = {
                "phase_plan": [
                    {
                        "phase": item.phase,
                        "segment": item.segment,
                        "duration_s": item.duration_s,
                    }
                    for item in plan
                ],
                "hardware": hardware,
                "timezone": "UTC epoch seconds",
            }
            recordPowerStressRunStart(
                run_id=run_id,
                started_at=started_at,
                duration_target_s=params.duration_s,
                stepper_speed_microsteps_per_sec=params.stepper_speed_microsteps_per_sec,
                chute_speed_microsteps_per_sec=params.chute_speed_microsteps_per_sec,
                chute_max_deg=params.chute_max_deg,
                config=config,
            )
            self._state = PowerStressState(
                run_id=run_id,
                params=params,
                started_at=started_at,
                hardware=hardware,
            )
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="PowerStressTest", daemon=True
            )
            self._thread.start()
            return _snapshot(self._state)

    def stop(self) -> None:
        with self._lock:
            if not self.isActive() or self._state is None:
                raise RuntimeError("No power stress test is running")
            self._state.status = "stopping"
            self._stop_event.set()
        self.logger.info("Power stress: stop requested")

    def _validateParams(self, params: PowerStressParams) -> None:
        if not MIN_DURATION_S <= params.duration_s <= MAX_DURATION_S:
            raise ValueError(
                f"duration_s must be between {MIN_DURATION_S:g} and {MAX_DURATION_S:g}"
            )
        if not MIN_SPEED < params.stepper_speed_microsteps_per_sec <= 20000:
            raise ValueError("stepper_speed_microsteps_per_sec must be between 17 and 20000")
        if not MIN_SPEED < params.chute_speed_microsteps_per_sec <= 10000:
            raise ValueError("chute_speed_microsteps_per_sec must be between 17 and 10000")
        if not 5.0 <= params.chute_max_deg <= CHUTE_MAX_ANGLE_LIMIT_DEG:
            raise ValueError(
                f"chute_max_deg must be between 5 and {CHUTE_MAX_ANGLE_LIMIT_DEG:g}"
            )

    def _steppers(self) -> dict[str, Any]:
        c4_stepper = getattr(self.irl, "c_channel_4_rotor_stepper", None) or getattr(
            self.irl, "carousel_stepper", None
        )
        return {
            "c_channel_1": getattr(self.irl, "c_channel_1_rotor_stepper", None),
            "c_channel_2": getattr(self.irl, "c_channel_2_rotor_stepper", None),
            "c_channel_3": getattr(self.irl, "c_channel_3_rotor_stepper", None),
            "c_channel_4": c4_stepper,
        }

    def _servos(self) -> list[Any]:
        return [
            servo
            for servo in list(getattr(self.irl, "servos", []) or [])
            if bool(getattr(servo, "available", True))
        ]

    def _hardwareSummary(self) -> dict[str, Any]:
        perception = getattr(self.gc, "perception_service", None)
        workers = getattr(perception, "_workers", {}) if perception is not None else {}
        worker_values = list(workers.values()) if isinstance(workers, dict) else []
        camera_service = None
        try:
            from server import shared_state

            camera_service = shared_state.camera_service
        except Exception:
            pass
        feeds = getattr(camera_service, "feeds", {}) if camera_service is not None else {}
        return {
            "steppers": [name for name, stepper in self._steppers().items() if stepper is not None],
            "servo_count": len(self._servos()),
            "led_output_count": len(
                getattr(getattr(self.irl, "led_controller", None), "outputs", [])
            ),
            "perception_started": bool(getattr(perception, "started", False)),
            "perception_workers": len(worker_values),
            "perception_workers_alive": sum(
                1 for worker in worker_values if bool(getattr(worker, "is_alive", False))
            ),
            "camera_roles": sorted(feeds.keys()) if isinstance(feeds, dict) else [],
        }

    def _validateHardware(self, hardware: dict[str, Any]) -> None:
        if getattr(self.irl, "chute", None) is None:
            raise RuntimeError("Chute hardware is unavailable")
        missing = sorted(set(self._steppers()) - set(hardware["steppers"]))
        if missing:
            raise RuntimeError(f"Required steppers unavailable: {', '.join(missing)}")
        worker_count = int(hardware["perception_workers"])
        alive_count = int(hardware["perception_workers_alive"])
        if not hardware["perception_started"] or worker_count == 0 or alive_count != worker_count:
            raise RuntimeError(
                "Perception models are not running on every configured channel"
            )
        chute_runner = getActiveChuteStressRunner()
        if chute_runner is not None and chute_runner.isActive():
            raise RuntimeError("A chute stress test is already running")

    def _event(self, event_type: str, details: dict[str, Any]) -> None:
        assert self._state is not None
        event = recordPowerStressEvent(
            run_id=self._state.run_id,
            created_at=time.time(),
            event_type=event_type,
            phase=self._state.current_phase,
            details=details,
        )
        with self._lock:
            self._state.events.append(event)
        self.logger.info(
            f"Power stress: {event_type} phase={self._state.current_phase} details={details}"
        )

    def _configuredStepperSpeeds(self) -> dict[str, int]:
        config = None
        controller = None
        try:
            from server import shared_state

            controller = shared_state.controller_ref
        except Exception:
            pass
        if controller is not None and hasattr(controller, "coordinator"):
            config = getattr(controller.coordinator, "irl_config", config)
        attr_by_name = {
            "c_channel_1": "c_channel_1_rotor_stepper",
            "c_channel_2": "c_channel_2_rotor_stepper",
            "c_channel_3": "c_channel_3_rotor_stepper",
            "c_channel_4": "c_channel_4_rotor_stepper",
        }
        speeds: dict[str, int] = {}
        for name, attr in attr_by_name.items():
            stepper_config = getattr(config, attr, None) if config is not None else None
            speeds[name] = int(getattr(stepper_config, "default_steps_per_second", 4000))
        return speeds

    def _setStepperSpeed(self, stepper: Any, speed: int, max_speed: int) -> None:
        stepper.enabled = True
        stepper.set_speed_limits(MIN_SPEED, max_speed)
        if not bool(stepper.move_at_speed(speed, acceleration=SAFE_ACCELERATION)):
            raise RuntimeError(f"Stepper {getattr(stepper, 'name', '?')} rejected speed {speed}")

    def _stopSteppers(self, steppers: dict[str, Any], max_speed: int) -> None:
        moving: list[Any] = []
        for stepper in steppers.values():
            try:
                stepper.set_speed_limits(MIN_SPEED, max_speed)
                stepper.set_acceleration(SAFE_ACCELERATION)
                if not bool(stepper.stopped):
                    if not bool(stepper.move_at_speed(0)):
                        raise RuntimeError("stop command rejected")
                    moving.append(stepper)
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to brake stepper {getattr(stepper, 'name', '?')}: {exc}"
                ) from exc
        deadline = time.monotonic() + STOP_TIMEOUT_S
        while moving and time.monotonic() < deadline:
            moving = [stepper for stepper in moving if not bool(stepper.stopped)]
            if moving:
                time.sleep(POLL_INTERVAL_S)
        if moving:
            for stepper in moving:
                stepper.enabled = False
            names = [str(getattr(stepper, "name", "?")) for stepper in moving]
            raise RuntimeError(f"Stepper braking timed out: {', '.join(names)}")

    def _restoreSteppers(self, steppers: dict[str, Any]) -> None:
        speeds = self._configuredStepperSpeeds()
        for name, stepper in steppers.items():
            try:
                default_speed = speeds.get(name, 4000)
                stepper.set_speed_limits(MIN_SPEED, default_speed)
                default_acceleration = getattr(stepper, "default_acceleration", None)
                if default_acceleration is not None:
                    stepper.set_acceleration(int(default_acceleration))
            except Exception as exc:
                self.logger.warning(f"Power stress: failed to restore {name}: {exc}")

    def _stopServos(self, servos: list[Any]) -> None:
        for servo in servos:
            try:
                if hasattr(servo, "stop"):
                    servo.stop()
                if hasattr(servo, "enabled"):
                    servo.enabled = False
            except Exception as exc:
                self.logger.warning(f"Power stress: failed to stop servo: {exc}")

    def _startChute(self, mode: str, duration_s: float) -> str:
        assert self._state is not None
        chute = self.irl.chute
        runner = getChuteStressRunner(self.gc, chute)
        state = runner.start(
            StressTestParams(
                mode=mode,  # type: ignore[arg-type]
                target_max_deg=self._state.params.chute_max_deg,
                duration_s=duration_s,
                speed_microsteps_per_sec=self._state.params.chute_speed_microsteps_per_sec,
            )
        )
        return state.run_id

    def _stopChute(self) -> None:
        runner = getActiveChuteStressRunner()
        if runner is None or not runner.isActive():
            return
        try:
            runner.stop()
        except RuntimeError:
            return
        deadline = time.monotonic() + STOP_TIMEOUT_S
        while runner.isActive() and time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL_S)
        if runner.isActive():
            raise RuntimeError("Chute stress runner did not stop")

    def _segmentModes(self, segment: PhaseSegment) -> dict[str, Any]:
        names = list(self._steppers())
        if segment.phase == "stable":
            stepper_modes = {name: "continuous" for name in names}
            servo_mode = "sweep"
            chute_mode = "sweep"
        elif segment.phase == "random":
            stepper_modes = {name: "burst" for name in names}
            servo_mode = "random"
            chute_mode = "random"
        else:
            stepper_modes = {
                name: "continuous" if (index + segment.segment) % 2 == 0 else "burst"
                for index, name in enumerate(names)
            }
            servo_mode = "random" if segment.segment % 2 else "sweep"
            chute_mode = "sweep" if segment.segment % 2 else "random"
        return {
            "steppers": stepper_modes,
            "servos": servo_mode,
            "chute": chute_mode,
        }

    def _updateBurstStepper(
        self,
        stepper: Any,
        state: dict[str, Any],
        now: float,
        speed: int,
    ) -> bool:
        motion_state = state.get("state", "idle")
        if motion_state == "running" and now >= float(state["until"]):
            if not bool(stepper.move_at_speed(0)):
                raise RuntimeError("Stepper rejected burst stop")
            state["state"] = "stopping"
            return True
        if motion_state == "stopping":
            if bool(stepper.stopped):
                state["state"] = "idle"
                state["until"] = now + self._rng.uniform(
                    RANDOM_STOP_MIN_S, RANDOM_STOP_MAX_S
                )
            return False
        if motion_state == "idle" and now >= float(state.get("until", 0.0)):
            direction = -1 if self._rng.random() < 0.5 else 1
            run_speed = max(MIN_SPEED + 1, int(speed * self._rng.uniform(0.7, 1.0)))
            if not bool(
                stepper.move_at_speed(
                    direction * run_speed, acceleration=SAFE_ACCELERATION
                )
            ):
                raise RuntimeError("Stepper rejected burst start")
            state["state"] = "running"
            state["until"] = now + self._rng.uniform(RANDOM_RUN_MIN_S, RANDOM_RUN_MAX_S)
            return True
        return False

    def _updateServo(
        self,
        servo: Any,
        state: dict[str, Any],
        mode: str,
    ) -> bool:
        if not bool(getattr(servo, "stopped", True)):
            return False
        previous = int(state.get("target", 180))
        if mode == "sweep":
            target = 0 if previous >= 90 else 180
        else:
            choices = [angle for angle in range(0, 181, 15) if abs(angle - previous) >= 45]
            target = self._rng.choice(choices)
        if not bool(servo.move_to(target)):
            raise RuntimeError(
                f"Servo {getattr(servo, 'channel', '?')} rejected target {target}"
            )
        state["target"] = target
        return True

    def _runSegment(self, segment: PhaseSegment, test_started: float) -> None:
        assert self._state is not None
        steppers = self._steppers()
        servos = self._servos()
        speed = self._state.params.stepper_speed_microsteps_per_sec
        modes = self._segmentModes(segment)
        stepper_states = {name: {"state": "idle", "until": 0.0} for name in steppers}
        servo_states = {id(servo): {"target": 180} for servo in servos}
        stepper_commands = {name: 0 for name in steppers}
        servo_commands = {str(getattr(servo, "channel", index)): 0 for index, servo in enumerate(servos)}

        self._stopSteppers(steppers, speed)
        for index, (name, stepper) in enumerate(steppers.items()):
            stepper.set_speed_limits(MIN_SPEED, speed)
            if modes["steppers"][name] == "continuous":
                direction = -1 if (index + segment.segment) % 2 else 1
                self._setStepperSpeed(stepper, direction * speed, speed)
                stepper_commands[name] += 1

        chute_run_id = self._startChute(modes["chute"], segment.duration_s)
        self._event(
            "segment_started",
            {
                "segment": segment.segment,
                "duration_s": segment.duration_s,
                "modes": modes,
                "chute_run_id": chute_run_id,
            },
        )
        segment_started = time.monotonic()
        deadline = segment_started + segment.duration_s
        last_persist = 0.0
        try:
            while not self._stop_event.is_set() and time.monotonic() < deadline:
                now = time.monotonic()
                for name, stepper in steppers.items():
                    if bool(getattr(stepper, "stalled", False)):
                        raise RuntimeError(f"Stepper stall detected on {name}")
                    if modes["steppers"][name] == "burst":
                        if self._updateBurstStepper(
                            stepper, stepper_states[name], now, speed
                        ):
                            stepper_commands[name] += 1
                for index, servo in enumerate(servos):
                    if self._updateServo(
                        servo, servo_states[id(servo)], modes["servos"]
                    ):
                        key = str(getattr(servo, "channel", index))
                        servo_commands[key] += 1
                runner = getActiveChuteStressRunner()
                if runner is not None and not runner.isActive():
                    chute_state = runner.getState()
                    chute_status = chute_state.status if chute_state is not None else "unknown"
                    if chute_status not in {"completed", "stopped"}:
                        raise RuntimeError(f"Chute stress ended early with status {chute_status}")
                elapsed = now - test_started
                with self._lock:
                    self._state.elapsed_s = elapsed
                if now - last_persist >= 1.0:
                    last_persist = now
                    updatePowerStressRunProgress(
                        run_id=self._state.run_id,
                        current_phase=self._state.current_phase,
                        total_time_s=elapsed,
                    )
                self._stop_event.wait(POLL_INTERVAL_S)
        finally:
            self._stopChute()
            self._stopSteppers(steppers, speed)
            self._stopServos(servos)

        self._event(
            "segment_completed",
            {
                "segment": segment.segment,
                "elapsed_s": time.monotonic() - segment_started,
                "stepper_commands": stepper_commands,
                "servo_commands": servo_commands,
                "chute_run_id": chute_run_id,
            },
        )

    def _run(self) -> None:
        assert self._state is not None
        steppers = self._steppers()
        servos = self._servos()
        led_controller = getattr(self.irl, "led_controller", None)
        led_state = get_led_state()
        test_started = time.monotonic()

        try:
            self._event("run_started", {"hardware": self._state.hardware})
            self._event("chute_home_started", {})
            if not bool(self.irl.chute.home()):
                raise RuntimeError("Chute homing failed")
            self._event(
                "chute_home_completed",
                {"angle_deg": float(self.irl.chute.current_angle)},
            )
            if led_controller is not None:
                led_controller.allOn()
            self._event(
                "leds_full_on",
                {"output_count": self._state.hardware["led_output_count"]},
            )
            self._event(
                "vision_verified",
                {
                    "camera_roles": self._state.hardware["camera_roles"],
                    "worker_count": self._state.hardware["perception_workers_alive"],
                },
            )

            for segment in buildPhasePlan(self._state.params.duration_s):
                if self._stop_event.is_set():
                    break
                with self._lock:
                    self._state.current_phase = segment.phase
                    self._state.current_segment = segment.segment
                self._runSegment(segment, test_started)

            with self._lock:
                self._state.elapsed_s = time.monotonic() - test_started
                self._state.status = "stopped" if self._stop_event.is_set() else "completed"
                self._state.current_phase = None
                self._state.ended_at = time.time()
            self._event("run_stopped" if self._stop_event.is_set() else "run_completed", {})
        except Exception as exc:
            self.logger.error(f"Power stress test failed: {exc}", exc_info=True)
            with self._lock:
                self._state.elapsed_s = time.monotonic() - test_started
                self._state.status = "failed"
                self._state.error = str(exc)
                self._state.ended_at = time.time()
            try:
                self._event("run_failed", {"error": str(exc)})
            except Exception:
                pass
        finally:
            try:
                self._stopChute()
            except Exception as exc:
                self.logger.warning(f"Power stress: chute cleanup failed: {exc}")
            try:
                self._stopSteppers(steppers, self._state.params.stepper_speed_microsteps_per_sec)
            except Exception as exc:
                self.logger.warning(f"Power stress: stepper cleanup failed: {exc}")
            self._stopServos(servos)
            self._restoreSteppers(steppers)
            if led_controller is not None:
                try:
                    led_controller.apply(led_state)
                except Exception as exc:
                    self.logger.warning(f"Power stress: LED restore failed: {exc}")
            with self._lock:
                if self._state.ended_at is None:
                    self._state.ended_at = time.time()
                if self._state.status in {"running", "stopping"}:
                    self._state.status = "stopped"
                self._state.elapsed_s = time.monotonic() - test_started
            finalizePowerStressRun(
                run_id=self._state.run_id,
                ended_at=self._state.ended_at,
                status=self._state.status,
                total_time_s=self._state.elapsed_s,
                error=self._state.error,
            )


_runner_lock = threading.Lock()
_runner: PowerStressTestRunner | None = None


def getPowerStressRunner(gc: GlobalConfig, irl: Any) -> PowerStressTestRunner:
    global _runner
    with _runner_lock:
        if _runner is None or _runner.irl is not irl:
            if _runner is not None and _runner.isActive():
                raise RuntimeError(
                    "A power stress test is running against a different hardware instance"
                )
            _runner = PowerStressTestRunner(gc, irl)
        return _runner


def getActivePowerStressRunner() -> PowerStressTestRunner | None:
    with _runner_lock:
        return _runner
