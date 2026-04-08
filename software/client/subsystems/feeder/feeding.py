import time
from typing import Optional, TYPE_CHECKING
import server.shared_state as shared_state
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .analysis import ChannelAction, analyzeFeederChannels
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager
from defs.consts import LOOP_TICK_MS
from defs.events import PauseCommandData, PauseCommandEvent

CH3_PRECISE_HOLDOVER_MS = 2000
CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0
CH1_STALL_ALERT_PREFIX = "Feeder transport blocked"
FEEDER_DETECTION_ALERT_PREFIX = "Feeder camera detection unavailable"
FEEDER_DETECTION_UNAVAILABLE_GRACE_S = 3.0

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor
    from irl.config import RotorPulseConfig

class Feeding(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision: VisionManager,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.vision = vision
        self._last_ch2_action = ChannelAction.IDLE
        self._last_ch3_action = ChannelAction.IDLE
        self._busy_until: dict[str, float] = {}
        self._ch3_last_precise_at: float = 0.0
        self._occupancy_state_by_resource: dict[str, str] = {}
        self._last_ch2_activity_at: float = time.monotonic()
        self._ch1_pulses_since_ch2_activity: int = 0
        self._ch1_jam_recovery_cooldown_until: float = 0.0
        self._ch1_jam_recovery_level: int = 0
        self._ch1_jam_recovery_attempts: int = 0
        self._last_ch1_jam_recovery_level_used: int = 0
        self._ch1_pause_enqueued: bool = False
        self._feeder_detection_unavailable_since: float | None = None
        self._feeder_detection_pause_enqueued: bool = False

    def _resetCh1JamTracking(self) -> None:
        self._ch1_pulses_since_ch2_activity = 0
        self._ch1_jam_recovery_level = 0
        self._ch1_jam_recovery_attempts = 0
        self._ch1_jam_recovery_cooldown_until = 0.0
        self._ch1_pause_enqueued = False

    def _clearCh1StallAlertIfOwned(self) -> None:
        with shared_state.hardware_lifecycle_lock:
            if (
                isinstance(shared_state.hardware_error, str)
                and shared_state.hardware_error.startswith(CH1_STALL_ALERT_PREFIX)
            ):
                shared_state.hardware_error = None

    def _clearFeederDetectionAlertIfOwned(self) -> None:
        with shared_state.hardware_lifecycle_lock:
            if (
                isinstance(shared_state.hardware_error, str)
                and shared_state.hardware_error.startswith(FEEDER_DETECTION_ALERT_PREFIX)
            ):
                shared_state.hardware_error = None

    def _pauseMachineForCh1Stall(self, max_levels: int) -> None:
        if self._ch1_pause_enqueued:
            return

        message = (
            f"{CH1_STALL_ALERT_PREFIX}: No parts could be transported through the feeder after {max_levels} recovery attempts. "
            "Please check whether there are still parts available or whether the bulk bucket / C-Channel 1 is clogged."
        )
        self.gc.logger.error(message)
        self.gc.profiler.hit("feeder.ch1_jam_recovery.exhausted")
        self.gc.runtime_stats.observeBlockedReason("feeder", "ch1_recovery_exhausted")
        with shared_state.hardware_lifecycle_lock:
            shared_state.hardware_error = message

        if shared_state.command_queue is not None:
            shared_state.command_queue.put(PauseCommandEvent(tag="pause", data=PauseCommandData()))

        self._ch1_pause_enqueued = True

    def _pauseMachineForDetectionUnavailable(self, detail: str | None) -> None:
        if self._feeder_detection_pause_enqueued:
            return

        suffix = f" ({detail})" if detail else ""
        message = (
            f"{FEEDER_DETECTION_ALERT_PREFIX}: The feeder cameras are not delivering reliable live data. "
            f"Please check the C-Channel cameras and reconnect them if needed.{suffix}"
        )
        self.gc.logger.error(message)
        self.gc.profiler.hit("feeder.detection_unavailable")
        self.gc.runtime_stats.observeBlockedReason("feeder", "detection_unavailable")
        with shared_state.hardware_lifecycle_lock:
            shared_state.hardware_error = message

        if shared_state.command_queue is not None:
            shared_state.command_queue.put(PauseCommandEvent(tag="pause", data=PauseCommandData()))

        self._feeder_detection_pause_enqueued = True

    def _setOccupancyState(self, resource_name: str, state_name: str) -> None:
        prev_state = self._occupancy_state_by_resource.get(resource_name)
        if prev_state == state_name:
            return
        self._occupancy_state_by_resource[resource_name] = state_name
        self.gc.runtime_stats.observeStateTransition(
            resource_name,
            prev_state,
            state_name,
        )

    def _ch1RecoveryDegrees(self, cfg: "RotorPulseConfig", recovery_level: int) -> float:
        _ = cfg
        base_output_degrees = float(
            self.irl_config.feeder_config.first_rotor_jam_backtrack_output_degrees
        )
        max_output_degrees = float(
            self.irl_config.feeder_config.first_rotor_jam_max_output_degrees
        )
        output_degrees = min(max_output_degrees, base_output_degrees + recovery_level * 6.0)
        return max(15.0, min(30.0, output_degrees))

    def _ch1RecoveryCycles(self, recovery_level: int) -> int:
        max_cycles = max(1, int(self.irl_config.feeder_config.first_rotor_jam_max_cycles))
        return max(1, min(max_cycles, 1 + recovery_level))

    def _runCh1JamRecovery(self, cfg: "RotorPulseConfig", now_mono: float) -> bool:
        if self._isStepperBusy(self.irl.c_channel_1_rotor_stepper):
            return False

        recovery_level = min(self._ch1_jam_recovery_level, 4)
        self._last_ch1_jam_recovery_level_used = recovery_level
        recovery_degrees = self._ch1RecoveryDegrees(cfg, recovery_level)
        recovery_cycles = self._ch1RecoveryCycles(recovery_level)
        recovery_label = f"ch1_jam_recovery_l{recovery_level + 1}"
        self.gc.logger.warning(
            "Feeder: bulk bucket appears stuck before C-Channel 2; "
            f"running ch1 jam recovery level {recovery_level + 1} "
            f"({recovery_cycles}x {recovery_degrees:.1f}° back/forward)"
        )

        self.gc.profiler.hit("feeder.path.ch1_jam_recovery")
        self.gc.runtime_stats.observePulse(recovery_label, "sent", now_mono)

        motor_recovery_degrees = recovery_degrees * CHANNEL_OUTPUT_GEAR_RATIO
        move_timeout_ms = max(2500, int(recovery_degrees * 90))
        reverse_ok = True
        forward_ok = True
        for cycle_index in range(recovery_cycles):
            reverse_ok = self.irl.c_channel_1_rotor_stepper.move_degrees_blocking(
                -motor_recovery_degrees,
                timeout_ms=move_timeout_ms,
            )
            if not reverse_ok:
                self.gc.profiler.hit("feeder.jam_recovery.reverse_failed")
                self.gc.logger.warning(
                    f"Feeder: ch1 jam recovery reverse move failed on cycle {cycle_index + 1}/{recovery_cycles}"
                )
                break

            forward_ok = self.irl.c_channel_1_rotor_stepper.move_degrees_blocking(
                motor_recovery_degrees,
                timeout_ms=move_timeout_ms,
            )
            if not forward_ok:
                self.gc.profiler.hit("feeder.jam_recovery.forward_failed")
                self.gc.logger.warning(
                    f"Feeder: ch1 jam recovery forward move failed on cycle {cycle_index + 1}/{recovery_cycles}"
                )
                break

        if reverse_ok and forward_ok:
            self.gc.logger.info(
                f"Feeder: ch1 jam recovery level {recovery_level + 1} completed"
            )

        now_after = time.monotonic()
        self._busy_until[self.irl.c_channel_1_rotor_stepper._name] = max(
            self._busy_until.get(self.irl.c_channel_1_rotor_stepper._name, 0.0),
            now_after + max(0.25, cfg.delay_between_pulse_ms / 1000.0),
        )
        self._ch1_jam_recovery_cooldown_until = (
            now_after + self.irl_config.feeder_config.first_rotor_jam_retry_cooldown_s
        )
        self._ch1_pulses_since_ch2_activity = 0
        self._ch1_jam_recovery_attempts += 1
        self._ch1_jam_recovery_level = min(
            self._ch1_jam_recovery_level + 1,
            max(0, int(self.irl_config.feeder_config.first_rotor_jam_max_cycles) - 1),
        )
        return reverse_ok and forward_ok

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        return None

    def _isStepperBusy(self, stepper: "StepperMotor") -> bool:
        return time.monotonic() < self._busy_until.get(stepper._name, 0.0)

    def _sendPulse(
        self,
        label: str,
        stepper: "StepperMotor",
        cfg: "RotorPulseConfig",
    ) -> bool:
        now_mono = time.monotonic()
        if self._isStepperBusy(stepper):
            self.gc.profiler.hit(f"feeder.skip.busy.{label}")
            self.gc.runtime_stats.observePulse(label, "busy", now_mono)
            return False
        prof = self.gc.profiler
        pulse_degrees = stepper.degrees_for_microsteps(cfg.steps_per_pulse)
        with prof.timer(f"feeder.move_cmd.{label}_ms"):
            success = stepper.move_degrees(pulse_degrees)
        exec_ms = stepper.estimateMoveDegreesMs(pulse_degrees)
        if success:
            cooldown_ms = max(exec_ms, cfg.delay_between_pulse_ms)
            if label.startswith("ch2"):
                self.vision.scheduleFeederTeacherCaptureAfterMove(
                    "c_channel_2",
                    delay_s=max(0.0, exec_ms) / 1000.0,
                    move_label=label,
                    pulse_degrees=float(pulse_degrees),
                )
            elif label.startswith("ch3"):
                self.vision.scheduleFeederTeacherCaptureAfterMove(
                    "c_channel_3",
                    delay_s=max(0.0, exec_ms) / 1000.0,
                    move_label=label,
                    pulse_degrees=float(pulse_degrees),
                )
        else:
            # Back off briefly after a rejected hardware move to avoid a hot retry loop.
            cooldown_ms = max(500, cfg.delay_between_pulse_ms)
            prof.hit(f"feeder.move_failed.{label}")
        self._busy_until[stepper._name] = time.monotonic() + cooldown_ms / 1000.0
        prof.observeValue(f"feeder.cooldown.{label}_ms", float(cooldown_ms))
        self.gc.runtime_stats.observePulse(label, "sent" if success else "failed", now_mono)
        return success

    def _executionLoop(self) -> None:
        fc = self.irl_config.feeder_config
        prof = self.gc.profiler

        while not self._stop_event.is_set():
            prof.hit("feeder.execution_loop.calls")
            prof.mark("feeder.execution_loop.interval_ms")

            with prof.timer("feeder.execution_loop.total_ms"):
                with prof.timer("feeder.get_feeder_detections_ms"):
                    detections = self.vision.getFeederHeatmapDetections()
                prof.observeValue(
                    "feeder.object_detection_count", float(len(detections))
                )

                detection_available, detection_reason = self.vision.getFeederDetectionAvailability()
                now = time.monotonic()

                if detection_available:
                    self._feeder_detection_unavailable_since = None
                    self._feeder_detection_pause_enqueued = False
                    self._clearFeederDetectionAlertIfOwned()
                else:
                    if self._feeder_detection_unavailable_since is None:
                        self._feeder_detection_unavailable_since = now
                    unavailable_for = now - self._feeder_detection_unavailable_since
                    if unavailable_for >= FEEDER_DETECTION_UNAVAILABLE_GRACE_S:
                        self._pauseMachineForDetectionUnavailable(detection_reason)

                    self.gc.runtime_stats.observeBlockedReason("feeder", "detection_unavailable")
                    self.gc.runtime_stats.observeFeederSignals(
                        {
                            "wait_chute": False,
                            "wait_classification_ready": False,
                            "wait_ch2_dropzone_clear": False,
                            "wait_ch3_dropzone_clear": False,
                            "wait_stepper_busy": False,
                            "pulse_intent_ch1": False,
                            "pulse_intent_ch2": False,
                            "pulse_intent_ch3": False,
                            "stepper_busy_ch1": False,
                            "stepper_busy_ch2": False,
                            "stepper_busy_ch3": False,
                            "pulse_sent_any": False,
                            "stable": False,
                        },
                        now_monotonic=now,
                    )
                    self._setOccupancyState("feeder.ch1", "feeding.wait_detection_available")
                    self._setOccupancyState("feeder.ch2", "feeding.wait_detection_available")
                    self._setOccupancyState("feeder.ch3", "feeding.wait_detection_available")
                    self._stop_event.wait(LOOP_TICK_MS / 1000.0)
                    continue

                with prof.timer("feeder.analyze_state_ms"):
                    analysis = analyzeFeederChannels(self.gc, detections)

                ch2_action = analysis.ch2_action
                ch3_action = analysis.ch3_action

                if ch3_action == ChannelAction.PULSE_PRECISE:
                    self._ch3_last_precise_at = now
                elif ch3_action == ChannelAction.PULSE_NORMAL and self._ch3_last_precise_at > 0:
                    if (now - self._ch3_last_precise_at) * 1000 < CH3_PRECISE_HOLDOVER_MS:
                        ch3_action = ChannelAction.PULSE_PRECISE

                ch2_active = analysis.ch2_dropzone_occupied or ch2_action != ChannelAction.IDLE
                if ch2_active:
                    self._last_ch2_activity_at = now
                    self._resetCh1JamTracking()
                    self._clearCh1StallAlertIfOwned()

                if ch2_action != self._last_ch2_action:
                    self.gc.logger.info(f"state change: ch2 {self._last_ch2_action.value} -> {ch2_action.value}")
                    self._last_ch2_action = ch2_action
                if ch3_action != self._last_ch3_action:
                    self.gc.logger.info(f"state change: ch3 {self._last_ch3_action.value} -> {ch3_action.value}")
                    self._last_ch3_action = ch3_action

                can_run = self.gc.rotary_channel_steppers_can_operate_in_parallel or (
                    not self.shared.chute_move_in_progress
                )
                ch3_held = (
                    not self.shared.classification_ready
                    and ch3_action == ChannelAction.PULSE_PRECISE
                )
                ch1_pulse_intent = not analysis.ch2_dropzone_occupied
                ch2_pulse_intent = (
                    not analysis.ch3_dropzone_occupied
                    and (
                        ch2_action == ChannelAction.PULSE_PRECISE
                        or ch2_action == ChannelAction.PULSE_NORMAL
                    )
                )
                ch3_pulse_intent = (
                    not ch3_held
                    and (
                        ch3_action == ChannelAction.PULSE_PRECISE
                        or ch3_action == ChannelAction.PULSE_NORMAL
                    )
                )
                ch1_stepper_busy = self._isStepperBusy(self.irl.c_channel_1_rotor_stepper)
                ch2_stepper_busy = self._isStepperBusy(self.irl.c_channel_2_rotor_stepper)
                ch3_stepper_busy = self._isStepperBusy(self.irl.c_channel_3_rotor_stepper)
                wait_stepper_busy = (
                    (ch1_pulse_intent and ch1_stepper_busy)
                    or (ch2_pulse_intent and ch2_stepper_busy)
                    or (ch3_pulse_intent and ch3_stepper_busy)
                )
                self.gc.runtime_stats.observeFeederState(
                    now_monotonic=now,
                    ch2_dropzone_occupied=analysis.ch2_dropzone_occupied,
                    ch3_dropzone_occupied=analysis.ch3_dropzone_occupied,
                    can_run=can_run,
                    classification_ready=self.shared.classification_ready,
                    ch2_action=ch2_action.value,
                    ch3_action=ch3_action.value,
                )

                if not can_run:
                    self.gc.runtime_stats.observeFeederSignals(
                        {
                            "wait_chute": True,
                            "wait_classification_ready": ch3_held,
                            "wait_ch2_dropzone_clear": analysis.ch2_dropzone_occupied,
                            "wait_ch3_dropzone_clear": analysis.ch3_dropzone_occupied,
                            "wait_stepper_busy": wait_stepper_busy,
                            "pulse_intent_ch1": ch1_pulse_intent,
                            "pulse_intent_ch2": ch2_pulse_intent,
                            "pulse_intent_ch3": ch3_pulse_intent,
                            "stepper_busy_ch1": ch1_stepper_busy,
                            "stepper_busy_ch2": ch2_stepper_busy,
                            "stepper_busy_ch3": ch3_stepper_busy,
                            "pulse_sent_any": False,
                            "stable": False,
                        },
                        now_monotonic=now,
                    )
                    self._setOccupancyState("feeder.ch1", "feeding.wait_chute_move_in_progress")
                    self._setOccupancyState("feeder.ch2", "feeding.wait_chute_move_in_progress")
                    self._setOccupancyState("feeder.ch3", "feeding.wait_chute_move_in_progress")
                    prof.hit("feeder.skip.chute_in_progress")
                    self.gc.runtime_stats.observeBlockedReason("feeder", "chute_in_progress")
                    self._stop_event.wait(LOOP_TICK_MS / 1000.0)
                    continue

                # channel 3 — hold precise pulses if carousel not ready to receive
                if ch3_held:
                    prof.hit("feeder.skip.ch3_held_for_carousel")
                    self.gc.runtime_stats.observeBlockedReason("feeder", "ch3_held_for_carousel")
                elif ch3_action == ChannelAction.PULSE_PRECISE:
                    prof.hit("feeder.path.ch3_precise")
                    if self._sendPulse("ch3_precise", self.irl.c_channel_3_rotor_stepper, fc.third_rotor_precision):
                        self.gc.logger.info("Feeder: ch3 precise, pulsing 3rd (precise)")
                elif ch3_action == ChannelAction.PULSE_NORMAL:
                    prof.hit("feeder.path.ch3_normal")
                    if self._sendPulse("ch3_normal", self.irl.c_channel_3_rotor_stepper, fc.third_rotor_normal):
                        self.gc.logger.info("Feeder: ch3 normal, pulsing 3rd")
                else:
                    prof.hit("feeder.path.ch3_idle")

                pulse_intent = False
                pulse_sent = False

                # channel 2 — only pulse if ch3 dropzone is clear
                if not analysis.ch3_dropzone_occupied:
                    if ch2_action == ChannelAction.PULSE_PRECISE:
                        prof.hit("feeder.path.ch2_precise")
                        pulse_intent = True
                        if self._sendPulse("ch2_precise", self.irl.c_channel_2_rotor_stepper, fc.second_rotor_precision):
                            pulse_sent = True
                            self.gc.logger.info("Feeder: ch2 precise, pulsing 2nd (precise)")
                    elif ch2_action == ChannelAction.PULSE_NORMAL:
                        prof.hit("feeder.path.ch2_normal")
                        pulse_intent = True
                        if self._sendPulse("ch2_normal", self.irl.c_channel_2_rotor_stepper, fc.second_rotor_normal):
                            pulse_sent = True
                            self.gc.logger.info("Feeder: ch2 normal, pulsing 2nd")
                    else:
                        prof.hit("feeder.path.ch2_idle")
                else:
                    prof.hit("feeder.skip.ch2_dropzone_occupied")
                    self.gc.runtime_stats.observeBlockedReason("feeder", "ch2_blocked_by_ch3_dropzone")

                # channel 1 — only pulse if ch2 dropzone is clear
                ch1_jam_recovery_triggered = False
                if not analysis.ch2_dropzone_occupied:
                    prof.hit("feeder.path.ch1")
                    no_recent_ch2_activity = (
                        now - self._last_ch2_activity_at >= fc.first_rotor_jam_timeout_s
                    )
                    ch1_has_been_trying = (
                        self._ch1_pulses_since_ch2_activity >= fc.first_rotor_jam_min_pulses
                    )
                    recovery_ready = now >= self._ch1_jam_recovery_cooldown_until
                    max_recovery_levels = max(1, int(self.irl_config.feeder_config.first_rotor_jam_max_cycles))
                    if (
                        no_recent_ch2_activity
                        and ch1_has_been_trying
                        and recovery_ready
                        and not analysis.ch3_dropzone_occupied
                    ):
                        if self._ch1_jam_recovery_attempts >= max_recovery_levels:
                            self._pauseMachineForCh1Stall(max_recovery_levels)
                            self._setOccupancyState(
                                "feeder.ch1",
                                "feeding.stalled_before_ch2_dropzone",
                            )
                            self._stop_event.wait(LOOP_TICK_MS / 1000.0)
                            continue
                        ch1_jam_recovery_triggered = self._runCh1JamRecovery(
                            fc.first_rotor,
                            now,
                        )
                        pulse_intent = True
                        pulse_sent = pulse_sent or ch1_jam_recovery_triggered
                    else:
                        pulse_intent = True
                        if self._sendPulse("ch1", self.irl.c_channel_1_rotor_stepper, fc.first_rotor):
                            pulse_sent = True
                            self._ch1_pulses_since_ch2_activity += 1
                            self.gc.logger.info("Feeder: clear, pulsing 1st")
                else:
                    prof.hit("feeder.skip.ch1_dropzone_occupied")
                    self.gc.runtime_stats.observeBlockedReason("feeder", "ch1_blocked_by_ch2_dropzone")

                if ch1_jam_recovery_triggered:
                    self._setOccupancyState(
                        "feeder.ch1",
                        f"feeding.recover_bulk_bucket_to_ch2_l{self._last_ch1_jam_recovery_level_used + 1}",
                    )
                elif analysis.ch2_dropzone_occupied:
                    self._setOccupancyState("feeder.ch1", "feeding.wait_ch2_dropzone_clear")
                else:
                    self._setOccupancyState("feeder.ch1", "feeding.pulse_ch1_when_clear")

                if analysis.ch3_dropzone_occupied:
                    self._setOccupancyState("feeder.ch2", "feeding.wait_ch3_dropzone_clear")
                elif ch2_action == ChannelAction.IDLE:
                    self._setOccupancyState("feeder.ch2", "feeding.idle_no_piece_in_ch2")
                elif ch2_action == ChannelAction.PULSE_PRECISE:
                    self._setOccupancyState("feeder.ch2", "feeding.pulse_ch2_precise")
                else:
                    self._setOccupancyState("feeder.ch2", "feeding.pulse_ch2_normal")

                if ch3_held:
                    self._setOccupancyState("feeder.ch3", "feeding.wait_classification_ready_for_ch3_precise")
                elif ch3_action == ChannelAction.IDLE:
                    self._setOccupancyState("feeder.ch3", "feeding.idle_no_piece_in_ch3")
                elif ch3_action == ChannelAction.PULSE_PRECISE:
                    self._setOccupancyState("feeder.ch3", "feeding.pulse_ch3_precise")
                else:
                    self._setOccupancyState("feeder.ch3", "feeding.pulse_ch3_normal")

                self.gc.runtime_stats.observeFeederSignals(
                    {
                        "wait_chute": False,
                        "wait_classification_ready": ch3_held,
                        "wait_ch2_dropzone_clear": analysis.ch2_dropzone_occupied,
                        "wait_ch3_dropzone_clear": analysis.ch3_dropzone_occupied,
                        "wait_stepper_busy": wait_stepper_busy and pulse_intent and (not pulse_sent),
                        "pulse_intent_ch1": ch1_pulse_intent,
                        "pulse_intent_ch2": ch2_pulse_intent,
                        "pulse_intent_ch3": ch3_pulse_intent,
                        "stepper_busy_ch1": ch1_stepper_busy,
                        "stepper_busy_ch2": ch2_stepper_busy,
                        "stepper_busy_ch3": ch3_stepper_busy,
                        "pulse_sent_any": pulse_sent,
                        "stable": (not ch3_held) and (not pulse_intent) and (not analysis.ch2_dropzone_occupied) and (not analysis.ch3_dropzone_occupied),
                    },
                    now_monotonic=now,
                )

            self._stop_event.wait(LOOP_TICK_MS / 1000.0)

    def cleanup(self) -> None:
        self._ch1_pause_enqueued = False
        self._feeder_detection_pause_enqueued = False
        super().cleanup()
