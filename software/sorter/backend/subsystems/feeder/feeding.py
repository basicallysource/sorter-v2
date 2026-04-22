import time
from typing import Optional, TYPE_CHECKING
import server.shared_state as shared_state
from states.base_state import BaseState
from subsystems.channels import C1Station, C2Station, C3Station, FeederTickContext
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from .analysis import ChannelAction, analyzeFeederChannels
from .admission import (
    CLASSIFICATION_CHANNEL_ID,
    classification_channel_admission_blocked as _classification_channel_admission_blocked,
    estimate_piece_count_for_channel as _estimate_piece_count_for_channel,
)
from .ch2_separation import Ch2SeparationDriver
from .strategies import C1JamRecoveryStrategy, C3HoldoverStrategy
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager
from defs.events import PauseCommandData, PauseCommandEvent

CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0
CH1_STALL_ALERT_PREFIX = "Feeder transport blocked"
FEEDER_DETECTION_ALERT_PREFIX = "Feeder camera detection unavailable"
FEEDER_DETECTION_UNAVAILABLE_GRACE_S = 3.0
# Cap pieces on c_channel_2 before c_channel_1 may feed more in. Keeps the
# bulk feeder from piling up the transport channel — c_channel_3 can only
# swallow one piece at a time so anything beyond this number is dead weight.
MAX_CH2_PIECES_FOR_CH1_FEED = 5

# ---------------------------------------------------------------------------
# c_channel_2 agitation — when c_channel_3 is busy and we recently fed a
# piece onto c_channel_2, use the idle time to jog the channel back-and-
# forth a little so piled-up pieces separate.
# ---------------------------------------------------------------------------
# Legacy jog-agitation — superseded by the Ch2SeparationDriver slip-stick
# pattern below, which runs whenever ch2 carries pieces but nothing is at the
# exit yet. Flip back to True to restore the old jog-back-then-forward
# behavior in an emergency.
CH2_AGITATION_ENABLED = False
# Output-shaft (LEGO wheel) degrees for the reverse / forward jog. A slight
# net-forward bias (forward > reverse) keeps pieces drifting toward the
# exit so agitation doesn't undo real progress.
CH2_AGITATION_REVERSE_DEG_OUTPUT = 45.0
CH2_AGITATION_FORWARD_DEG_OUTPUT = 30.0
# Minimum gap between two agitations so we don't jackhammer the stepper.
CH2_AGITATION_MIN_INTERVAL_S = 2.0
# Only agitate within this window after a c_channel_1 pulse — beyond that
# we're probably idle for a real reason, not because c_channel_3 is eating.
CH2_AGITATION_RECENT_CH1_WINDOW_S = 10.0
# Forward-push schedule paired with shake escalation. After each shake at
# level N, push the bulk rotor forward by this many output degrees to drag
# any pieces stuck at the back of the bucket toward the ch2 dropzone.
# Starts gentle and ramps up — 90° was already noticeably aggressive on
# the first push, so we begin with a small nudge and only reach a full
# rotation at the top of the escalation.
CH1_RECOVERY_PUSH_OUTPUT_DEGREES = (15.0, 45.0, 90.0, 180.0, 360.0)

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
        self._last_ch2_activity_at: float = time.monotonic()
        self._ch1_pulses_since_ch2_activity: int = 0
        self._last_ch1_pulse_at: float = 0.0
        self._ch1_pause_enqueued: bool = False
        self._feeder_detection_unavailable_since: float | None = None
        self._feeder_detection_pause_enqueued: bool = False
        self._c1_jam_recovery = C1JamRecoveryStrategy(
            stepper=self.irl.c_channel_1_rotor_stepper,
            logger=self.gc.logger,
            profiler=self.gc.profiler,
            runtime_stats=self.gc.runtime_stats,
            feeder_config=self.irl_config.feeder_config,
            busy_until=self._busy_until,
            gear_ratio=CHANNEL_OUTPUT_GEAR_RATIO,
            push_output_degrees=CH1_RECOVERY_PUSH_OUTPUT_DEGREES,
        )
        self._c3_holdover = C3HoldoverStrategy()
        # Slip-stick separation driver for idle-time c_channel_2 agitation.
        # Owns the ch2 rotor in short windows where a piece is on the ring
        # but not yet at the exit; hard-cancels the instant anything else
        # needs the rotor or a piece reaches the exit zone.
        self._ch2_separation = Ch2SeparationDriver(
            self.irl.c_channel_2_rotor_stepper, self.gc.logger
        )
        self._c3_station = C3Station(
            gc=self.gc,
            stepper=self.irl.c_channel_3_rotor_stepper,
            send_pulse=self._sendPulse,
            feeder_config=self.irl_config.feeder_config,
            irl=self.irl,
            gear_ratio=CHANNEL_OUTPUT_GEAR_RATIO,
        )
        self._c2_station = C2Station(
            gc=self.gc,
            stepper=self.irl.c_channel_2_rotor_stepper,
            irl=self.irl,
            send_pulse=self._sendPulse,
            feeder_config=self.irl_config.feeder_config,
            separation_driver=self._ch2_separation,
            gear_ratio=CHANNEL_OUTPUT_GEAR_RATIO,
            agitation_enabled=CH2_AGITATION_ENABLED,
            agitation_reverse_deg_output=CH2_AGITATION_REVERSE_DEG_OUTPUT,
            agitation_forward_deg_output=CH2_AGITATION_FORWARD_DEG_OUTPUT,
            agitation_min_interval_s=CH2_AGITATION_MIN_INTERVAL_S,
            agitation_recent_ch1_window_s=CH2_AGITATION_RECENT_CH1_WINDOW_S,
        )
        self._c2_station.bind_last_ch1_pulse_at(lambda: self._last_ch1_pulse_at)
        self._c1_station = C1Station(
            gc=self.gc,
            stepper=self.irl.c_channel_1_rotor_stepper,
            vision=self.vision,
            irl_config=self.irl_config,
            send_pulse=self._sendPulse,
            jam_recovery=self._c1_jam_recovery,
            feeder_pause_for_ch1_stall=self._pauseMachineForCh1Stall,
            max_ch2_pieces_for_feed=MAX_CH2_PIECES_FOR_CH1_FEED,
            last_ch2_activity_at_ref=lambda: self._last_ch2_activity_at,
            ch1_pulses_since_ch2_activity_ref=lambda: self._ch1_pulses_since_ch2_activity,
            last_ch1_pulse_at_setter=self._set_last_ch1_pulse_at,
            ch1_pulses_since_ch2_activity_incrementer=self._increment_ch1_pulses_since_ch2_activity,
        )

    def _resetCh1JamTracking(self) -> None:
        self._ch1_pulses_since_ch2_activity = 0
        self._c1_jam_recovery.reset()
        self._ch1_pause_enqueued = False

    def _clearCh1StallAlertIfOwned(self) -> None:
        with shared_state.hardware_lifecycle_lock:
            if (
                isinstance(shared_state.hardware_error, str)
                and shared_state.hardware_error.startswith(CH1_STALL_ALERT_PREFIX)
            ):
                shared_state.setHardwareStatus(clear_error=True)

    def _clearFeederDetectionAlertIfOwned(self) -> None:
        with shared_state.hardware_lifecycle_lock:
            if (
                isinstance(shared_state.hardware_error, str)
                and shared_state.hardware_error.startswith(FEEDER_DETECTION_ALERT_PREFIX)
            ):
                shared_state.setHardwareStatus(clear_error=True)

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
            shared_state.setHardwareStatus(error=message)

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
            shared_state.setHardwareStatus(error=message)

        if shared_state.command_queue is not None:
            shared_state.command_queue.put(PauseCommandEvent(tag="pause", data=PauseCommandData()))

        self._feeder_detection_pause_enqueued = True

    def step(self) -> Optional[FeederState]:
        self._tick_once()
        return None

    def _set_last_ch1_pulse_at(self, now_mono: float) -> None:
        self._last_ch1_pulse_at = float(now_mono)

    def _increment_ch1_pulses_since_ch2_activity(self) -> None:
        self._ch1_pulses_since_ch2_activity += 1

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

    def _tick_once(self) -> None:
        prof = self.gc.profiler

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
                self._c1_station.set_state("feeding.wait_detection_available")
                self._c2_station.set_state("feeding.wait_detection_available")
                self._c3_station.set_state("feeding.wait_detection_available")
                return

            with prof.timer("feeder.analyze_state_ms"):
                analysis = analyzeFeederChannels(self.gc, detections)

            ch2_action = analysis.ch2_action
            ch3_action = analysis.ch3_action

            ch3_action = self._c3_holdover.apply(ch3_action, now)

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
            classification_ready_block = (
                not self.shared.classification_ready
                and ch3_action == ChannelAction.PULSE_PRECISE
            )
            classification_channel_block = False
            classification_channel_piece_count = 0
            machine_setup = getattr(self.irl_config, "machine_setup", None)
            classification_channel_setup = bool(
                machine_setup is not None
                and getattr(machine_setup, "uses_classification_channel", False)
            )
            if classification_channel_setup:
                try:
                    # Whitelist gate: admission-control piece count must
                    # exclude unconfirmed ghost tracks, otherwise an
                    # apparatus artefact on the carousel would hold ch3
                    # back indefinitely.
                    classification_channel_track_count = sum(
                        1
                        for track in self.vision.getFeederTracks("carousel")
                        if bool(getattr(track, "confirmed_real", False))
                    )
                except Exception:
                    classification_channel_track_count = 0
                transport_piece_count = 0
                zone_manager = None
                classification_channel_config = getattr(
                    self.irl_config,
                    "classification_channel_config",
                    None,
                )
                transport = self.shared.transport
                if transport is not None:
                    try:
                        transport_piece_count = int(transport.getActivePieceCount())
                    except Exception:
                        transport_piece_count = 0
                    zone_manager = getattr(transport, "zone_manager", None)
                classification_channel_piece_count = max(
                    _estimate_piece_count_for_channel(
                        detections,
                        channel_id=CLASSIFICATION_CHANNEL_ID,
                        track_count=classification_channel_track_count,
                    ),
                    int(zone_manager.zone_count()) if zone_manager is not None else 0,
                    transport_piece_count,
                )
                classification_channel_block = _classification_channel_admission_blocked(
                    detections,
                    track_count=classification_channel_track_count,
                    transport_piece_count=transport_piece_count,
                    zone_manager=zone_manager,
                    config=classification_channel_config,
                )
            ch3_held = classification_ready_block or classification_channel_block
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
                self._c1_station.set_state("feeding.wait_chute_move_in_progress")
                self._c2_station.set_state("feeding.wait_chute_move_in_progress")
                self._c3_station.set_state("feeding.wait_chute_move_in_progress")
                prof.hit("feeder.skip.chute_in_progress")
                self.gc.runtime_stats.observeBlockedReason("feeder", "chute_in_progress")
                return

            ctx = FeederTickContext(
                now_mono=now,
                detections=detections,
                analysis=analysis,
                ch2_action=ch2_action,
                ch3_action=ch3_action,
                can_run=can_run,
                ch3_held=ch3_held,
                classification_channel_block=classification_channel_block,
                classification_channel_piece_count=classification_channel_piece_count,
                ch1_pulse_intent=ch1_pulse_intent,
                ch2_pulse_intent=ch2_pulse_intent,
                ch3_pulse_intent=ch3_pulse_intent,
                ch1_stepper_busy=ch1_stepper_busy,
                ch2_stepper_busy=ch2_stepper_busy,
                ch3_stepper_busy=ch3_stepper_busy,
                wait_stepper_busy=wait_stepper_busy,
            )

            self._c3_station.step(ctx)
            self._c2_station.step(ctx)
            self._c1_station.step(ctx)
            if ctx.abort_tick:
                return
            self._c2_station.run_idle_strategies(ctx)
            self._c2_station.run_exit_wiggle(ctx)
            self._c3_station.run_exit_wiggle(ctx)

            self.gc.runtime_stats.observeFeederSignals(
                {
                    "wait_chute": False,
                    "wait_classification_ready": ch3_held,
                    "wait_ch2_dropzone_clear": analysis.ch2_dropzone_occupied,
                    "wait_ch3_dropzone_clear": analysis.ch3_dropzone_occupied,
                    "wait_stepper_busy": wait_stepper_busy and ctx.pulse_intent and (not ctx.pulse_sent),
                    "pulse_intent_ch1": ch1_pulse_intent,
                    "pulse_intent_ch2": ch2_pulse_intent,
                    "pulse_intent_ch3": ch3_pulse_intent,
                    "stepper_busy_ch1": ch1_stepper_busy,
                    "stepper_busy_ch2": ch2_stepper_busy,
                    "stepper_busy_ch3": ch3_stepper_busy,
                    "pulse_sent_any": ctx.pulse_sent,
                    "stable": (not ch3_held) and (not ctx.pulse_intent) and (not analysis.ch2_dropzone_occupied) and (not analysis.ch3_dropzone_occupied),
                },
                now_monotonic=now,
            )

    def cleanup(self) -> None:
        self._ch1_pause_enqueued = False
        self._feeder_detection_pause_enqueued = False
        self._c3_holdover.reset()
        self._c2_station.cleanup()
        super().cleanup()
