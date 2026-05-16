import time
from typing import Optional, TYPE_CHECKING
import server.shared_state as shared_state
from states.base_state import BaseState
from subsystems.channels import C1Station, C2Station, C3Station, FeederTickContext
from subsystems.shared_variables import SharedVariables
from subsystems.bus import StationId
from .states import FeederState
from .analysis import ChannelAction, analyzeFeederChannels
from .admission import (
    CLASSIFICATION_CHANNEL_ID,
    classification_channel_admission_blocked as _classification_channel_admission_blocked,
    estimate_piece_count_for_channel as _estimate_piece_count_for_channel,
)
from .ch2_separation import Ch2SeparationDriver
from .dropzone_incidents import DropzoneStuckIncidentManager
from .strategies import C1JamRecoveryStrategy, C3HoldoverStrategy
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager
from defs.events import PauseCommandData, PauseCommandEvent
from subsystems.sample_collection_speed import (
    microsteps_from_stepper_config,
    sample_collection_effective_speed_microsteps_per_second,
)

CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0
CH1_STALL_ALERT_PREFIX = "Feeder transport blocked"
FEEDER_DETECTION_ALERT_PREFIX = "Feeder camera detection unavailable"
FEEDER_DETECTION_UNAVAILABLE_GRACE_S = 3.0
FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND = "feeder_detection_unavailable"
# Grace window after a C3 pulse during which classification-channel
# admission stays blocked regardless of what the vision/transport state
# reports. Covers the race between the C3 stepper cooldown ending and the
# new piece being registered into C4's zone manager — without it, the
# next feeder tick can see "C4 empty", fire a second pulse, and double-
# drop both pieces into the same C4 sector.
CLASSIFICATION_CHANNEL_PENDING_ADMISSION_MS = 1500
# C4 publishes a request, then switches the gate to "awaiting_piece" while it
# waits for C3 to actually drop. Treat that request as the feeder admission
# lease; otherwise C3 can miss the one-tick open gate and stall until timeout.
CLASSIFICATION_INTAKE_REQUEST_LEASE_S = 2.0
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
# C2 slip-stick is now represented as an incident candidate, but disabled
# because uncontrolled move_at_speed phases can make the rotor accelerate
# unexpectedly during tuning.
CH2_SEPARATION_INCIDENT_ENABLED = False
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


def _classification_channel_structural_admission_blocked(
    detections: list,
    *,
    track_count: int,
    transport_piece_count: int,
    zone_manager,
    config,
) -> bool:
    """Return extra feeder-side C4 admission blocking.

    In dynamic C4 mode the classification-channel runner owns the real intake
    gate and publishes it through ``shared.classification_ready``. Repeating a
    second, coarser count/zone check here serializes the platter again because
    it cannot apply the runner's context such as drop-committed exclusions.
    Keep this fallback only for non-dynamic / legacy setups; the post-C3-pulse
    grace window below still protects against double-drops while a newly fired
    piece is in flight.
    """
    if (
        zone_manager is not None
        and config is not None
        and bool(getattr(config, "use_dynamic_zones", False))
    ):
        return False
    return _classification_channel_admission_blocked(
        detections,
        track_count=track_count,
        transport_piece_count=transport_piece_count,
        zone_manager=zone_manager,
        config=config,
    )


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
        self._motion_until: dict[str, float] = {}
        # Block follow-up C3 pulses for this long after a delivery to the
        # classification channel, even if the vision/transport state still
        # looks "empty" because the piece hasn't been registered yet. The
        # race: piece A is in flight (~80 ms to land + ~100 ms for 2 tracker
        # hits + 1 running tick to register), but C3's precise cooldown is
        # also 1000 ms — if vision lags the cooldown end by more than a
        # frame, admission_blocked returns False and C3 happily fires
        # another pulse, double-dropping into the same sector. 1500 ms is
        # generous enough to cover the slowest registration path while
        # still allowing back-to-back deliveries once C4 has acknowledged.
        self._classification_channel_pending_admission_until: float = 0.0
        self._last_ch2_activity_at: float = time.monotonic()
        self._ch1_pulses_since_ch2_activity: int = 0
        self._last_ch1_pulse_at: float = 0.0
        self._ch1_pause_enqueued: bool = False
        self._feeder_detection_unavailable_since: float | None = None
        self._feeder_detection_pause_enqueued: bool = False
        self._sample_speed_limit_cache: dict[str, int] = {}
        self._dropzone_incidents = DropzoneStuckIncidentManager(gc=self.gc)
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
        # Kept wired so active motion can be cancelled, but automatic starts
        # are disabled and routed through a dormant incident path for now.
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
            separation_incident_enabled=CH2_SEPARATION_INCIDENT_ENABLED,
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
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is not None and hasattr(runtime_stats, "activeIncident"):
            try:
                active = runtime_stats.activeIncident()
            except Exception:
                active = None
            if (
                isinstance(active, dict)
                and active.get("kind") == FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND
                and hasattr(runtime_stats, "clearActiveIncident")
            ):
                runtime_stats.clearActiveIncident(
                    kind=FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND
                )

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

    def _publishFeederDetectionUnavailableIncident(
        self,
        detail: str | None,
        unavailable_for_s: float,
    ) -> None:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
            return
        active = None
        if hasattr(runtime_stats, "activeIncident"):
            try:
                active = runtime_stats.activeIncident()
            except Exception:
                active = None
        if isinstance(active, dict):
            if active.get("kind") == FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND:
                return
            return
        runtime_stats.setActiveIncident(
            {
                "kind": FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND,
                "severity": "critical",
                "status": "waiting_for_operator",
                "awaiting_operator": True,
                "scope": "feeder",
                "channel": "feeder",
                "role": "feeder_detection",
                "channel_label": "Feeder Cameras",
                "triggered_at": time.time(),
                "unavailable_ms": int(max(0.0, unavailable_for_s) * 1000.0),
                "detail": detail or "",
                "rule": "feeder_detection_unavailable_after_grace",
                "resolution": "operator_restore_camera_detection_or_clear_incident",
            }
        )

    def _pauseMachineForDetectionUnavailable(
        self,
        detail: str | None,
        unavailable_for_s: float,
    ) -> None:
        self._publishFeederDetectionUnavailableIncident(detail, unavailable_for_s)
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

    def _isStepperMotionActive(self, stepper: "StepperMotor", now_mono: float) -> bool:
        return float(now_mono) < self._motion_until.get(stepper._name, 0.0)

    def _rotatingChannelIds(self, now_mono: float) -> set[int]:
        rotating: set[int] = set()
        if self._isStepperMotionActive(self.irl.c_channel_2_rotor_stepper, now_mono):
            rotating.add(2)
        if self._isStepperMotionActive(self.irl.c_channel_3_rotor_stepper, now_mono):
            rotating.add(3)
        return rotating

    def _activeDropzoneIncident(
        self,
        channel: str | None = None,
        global_id: int | None = None,
    ) -> dict:
        active = self.gc.runtime_stats.activeIncident()
        if not isinstance(active, dict) or active.get("kind") != "channel_dropzone_stuck":
            raise RuntimeError("No C2/C3 dropzone incident is waiting.")
        if channel is not None and active.get("channel") != channel:
            raise ValueError("The active dropzone incident belongs to another channel.")
        if global_id is not None and int(active.get("global_id") or -1) != int(global_id):
            raise ValueError("The active dropzone incident belongs to another tracker id.")
        return active

    def acknowledgeDropzoneStuckIncident(
        self,
        channel: str | None = None,
        global_id: int | None = None,
    ) -> dict:
        active = self._activeDropzoneIncident(channel, global_id)
        return self._dropzone_incidents.acknowledge_active_incident(
            active,
            time.monotonic(),
        )

    def clearDropzoneStuckIncident(
        self,
        channel: str | None = None,
        global_id: int | None = None,
    ) -> dict:
        active = self._activeDropzoneIncident(channel, global_id)
        return self._dropzone_incidents.clear_active_incident(active)

    def _classificationChannelHasPendingAdmission(self) -> bool:
        """True while the post-C3-pulse grace window is still active.

        Set by ``_sendPulse`` on every successful ch3 pulse; consulted by
        ``_tick_once`` to keep ``classification_channel_block`` True until
        either the timer expires or the structural admission check picks
        the new piece up (whichever comes first). The grace covers the
        race between the C3 stepper cooldown ending and the new piece
        being registered into C4's zone manager.
        """
        return (
            time.monotonic()
            < self._classification_channel_pending_admission_until
        )

    def _classificationIntakeRequestPending(self, now_mono: float) -> bool:
        if not hasattr(self.shared, "has_pending_piece_request"):
            return False
        return bool(
            self.shared.has_pending_piece_request(
                source=StationId.CLASSIFICATION,
                target=StationId.C3,
                now_mono=now_mono,
                timeout_s=CLASSIFICATION_INTAKE_REQUEST_LEASE_S,
            )
        )

    def _sampleCollectionRoleForPulseLabel(self, label: str) -> str | None:
        if label.startswith("ch1"):
            return "c_channel_1"
        if label.startswith("ch2"):
            return "c_channel_2"
        if label.startswith("ch3"):
            return "c_channel_3"
        return None

    def _stepperConfigForSampleRole(self, role: str):
        if role == "c_channel_1":
            return getattr(self.irl_config, "c_channel_1_rotor_stepper", None)
        if role == "c_channel_2":
            return getattr(self.irl_config, "c_channel_2_rotor_stepper", None)
        if role == "c_channel_3":
            return getattr(self.irl_config, "c_channel_3_rotor_stepper", None)
        return None

    def _setCachedSpeedLimit(self, cache_key: str, stepper: "StepperMotor", speed: int) -> None:
        if self._sample_speed_limit_cache.get(cache_key) == int(speed):
            return
        stepper.set_speed_limits(16, int(speed))
        self._sample_speed_limit_cache[cache_key] = int(speed)

    def _applySampleCollectionSpeedLimit(
        self,
        label: str,
        stepper: "StepperMotor",
        cfg: "RotorPulseConfig",
    ) -> int | None:
        role = self._sampleCollectionRoleForPulseLabel(label)
        if role is None:
            return None
        default_speed = int(getattr(cfg, "microsteps_per_second", 0) or 0)
        if default_speed <= 0:
            return None

        cache_key = f"{role}:{getattr(stepper, '_name', label)}"
        if not self.shared.sample_collection_mode:
            if cache_key in self._sample_speed_limit_cache:
                try:
                    self._setCachedSpeedLimit(cache_key, stepper, default_speed)
                finally:
                    self._sample_speed_limit_cache.pop(cache_key, None)
                return default_speed
            return None

        microsteps = microsteps_from_stepper_config(
            self._stepperConfigForSampleRole(role),
            fallback=getattr(stepper, "_microsteps", 8),
        )
        speed = sample_collection_effective_speed_microsteps_per_second(
            role,
            default_microsteps_per_second=default_speed,
            microsteps=microsteps,
            enabled=True,
        )
        if speed is None:
            return None
        try:
            self._setCachedSpeedLimit(cache_key, stepper, int(speed))
        except Exception as exc:
            self.gc.logger.warning(
                f"Feeder: could not apply sample speed for {role}: {exc}"
            )
            return None
        return int(speed)

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
        effective_speed_limit = self._applySampleCollectionSpeedLimit(label, stepper, cfg)
        with prof.timer(f"feeder.move_cmd.{label}_ms"):
            success = stepper.move_degrees(pulse_degrees)
        exec_ms = stepper.estimateMoveDegreesMs(
            pulse_degrees,
            max_speed=effective_speed_limit or 5000,
        )
        if success:
            cooldown_ms = max(exec_ms, cfg.delay_between_pulse_ms)
            self._motion_until[stepper._name] = time.monotonic() + max(0.0, exec_ms) / 1000.0
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
                if label == "ch3_precise" and hasattr(
                    self.shared, "publish_piece_delivered"
                ):
                    self.shared.publish_piece_delivered(
                        source=StationId.C3,
                        target=StationId.CLASSIFICATION,
                        delivered_at_mono=now_mono,
                    )
                # A C3 pulse that targets the classification channel is a
                # piece-in-flight commitment. Hold admission until C4 has
                # had time to register the new piece in its zone manager
                # — otherwise the next feeder tick reads "C4 empty" and
                # fires a second pulse, double-dropping into the same
                # sector. We pin the timer here unconditionally for any
                # successful ch3 pulse; non-classification_channel setups
                # ignore it via _classificationChannelPendingAdmission().
                self._classification_channel_pending_admission_until = (
                    time.monotonic()
                    + (CLASSIFICATION_CHANNEL_PENDING_ADMISSION_MS / 1000.0)
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
                    self._pauseMachineForDetectionUnavailable(
                        detection_reason,
                        unavailable_for,
                    )

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

            dropzone_incident_published = self._dropzone_incidents.update(
                detections,
                now,
                rotating_channel_ids=self._rotatingChannelIds(now),
            )
            if dropzone_incident_published:
                self.gc.runtime_stats.observeBlockedReason("feeder", "dropzone_stuck_incident")
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
                self._c1_station.set_state("feeding.wait_dropzone_incident_review")
                self._c2_station.set_state("feeding.wait_dropzone_incident_review")
                self._c3_station.set_state("feeding.wait_dropzone_incident_review")
                return

            with prof.timer("feeder.analyze_state_ms"):
                analysis = analyzeFeederChannels(
                    self.gc,
                    detections,
                    ignored_dropzone_detection_ids=self._dropzone_incidents.ignored_detection_ids(),
                )

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
            classification_gate_open = bool(self.shared.classification_ready)
            classification_intake_request_pending = (
                self._classificationIntakeRequestPending(now)
            )
            classification_ready_for_ch3 = (
                classification_gate_open or classification_intake_request_pending
            )
            classification_ready_block = (
                not classification_ready_for_ch3
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
                    classification_channel_track_count = len(
                        self.vision.getFeederTracks("carousel")
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
                classification_channel_block = _classification_channel_structural_admission_blocked(
                    detections,
                    track_count=classification_channel_track_count,
                    transport_piece_count=transport_piece_count,
                    zone_manager=zone_manager,
                    config=classification_channel_config,
                )
                # Additional grace: even when the structural checks above
                # say "intake clear", any C3 pulse fired in the last
                # CLASSIFICATION_CHANNEL_PENDING_ADMISSION_MS still has a
                # piece in flight that hasn't been registered yet. Hold
                # admission until either the timer expires or the piece
                # gets registered (which makes the structural check fail
                # naturally on the next tick).
                if (
                    not classification_channel_block
                    and self._classificationChannelHasPendingAdmission()
                ):
                    classification_channel_block = True
                    prof.hit("feeder.skip.classification_channel_pending_admission")
            ch3_held = (
                classification_ready_block or classification_channel_block
            )
            # Sample-collection mode: bypass the downstream gate so C3 keeps
            # advancing pieces past the cameras even when the classification
            # channel is stalled (e.g. clogged by ghost detections we are
            # trying to record samples to fix).
            if self.shared.sample_collection_mode:
                ch3_held = False
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
                classification_ready=classification_ready_for_ch3,
                ch2_action=ch2_action.value,
                ch3_action=ch3_action.value,
            )

            if not can_run:
                self.gc.runtime_stats.observeFeederSignals(
                    {
                        "wait_chute": True,
                        "wait_classification_ready": ch3_held,
                        "classification_intake_request_pending": classification_intake_request_pending,
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
                sample_collection_mode=bool(self.shared.sample_collection_mode),
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
                    "classification_intake_request_pending": classification_intake_request_pending,
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
