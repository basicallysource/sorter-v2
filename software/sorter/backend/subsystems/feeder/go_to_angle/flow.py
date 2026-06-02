import time
from typing import Optional, TYPE_CHECKING

from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from subsystems.bus import StationId
from defs.channel import ChannelDetection
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager

from ..states import FeederState
from ..analysis import analyzeFeederChannels
from .config import GoToAngleConfig
from .eject import EjectController
from . import geometry

# Exit handling is a per-channel strategy. A channel runs in either:
#  - precise-pulse mode (default): meter the piece into the exit one small pulse
#    at a time, gated on downstream readiness (``_apply_action`` PRECISE), or
#  - fast-eject mode (C3 by default): one quick move that balances the piece's
#    bbox COM on the exit's fall-off edge, then an explicit watch-for-fall +
#    jitter recovery (``EjectController`` in eject.py).
# Jitter now fires ONLY inside the fast-eject fall-recovery procedure — the old
# exit-dwell jitter has been removed. The perception sub-path (``_step_perception``)
# is where fast-eject lives; the legacy-vision sub-path keeps precise pulsing only.

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor

# Motor-shaft to channel-output gear ratio. One output (LEGO wheel) degree
# requires this many motor degrees. Matches the reactive flow's constant.
CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0

# Re-read the tuning config from disk at most this often so the tuning page
# takes effect live without a restart, without hammering the filesystem.
_CONFIG_TTL_S = 1.0

# After a C3 exit dispense, keep C3 blocked this long so the in-flight piece
# can register downstream before we consider another move.
CLASSIFICATION_PENDING_ADMISSION_MS = 1500


class GoToAngleFeeding(BaseState):
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
        self._busy_until: dict[str, float] = {}
        self._config: GoToAngleConfig = GoToAngleConfig()
        self._config_loaded_at: float = 0.0
        self._classification_pending_until: float = 0.0
        self._ch3_was_at_exit: bool = False
        # Per-channel fast-eject controllers, lazily built on first use (steppers
        # may not be ready at __init__ in test contexts). Only channels running
        # in fast-eject mode get one.
        self._eject_controllers: dict[int, EjectController] = {}
        machine_setup = getattr(irl_config, "machine_setup", None)
        self._classification_setup = bool(
            machine_setup is not None
            and getattr(machine_setup, "uses_classification_channel", False)
        )

    def _cfg(self) -> GoToAngleConfig:
        now = time.monotonic()
        if now - self._config_loaded_at >= _CONFIG_TTL_S:
            try:
                from toml_config import getGoToAngleConfig
                from .config import configFromDict
                self._config = configFromDict(getGoToAngleConfig())
            except Exception as exc:
                self.gc.logger.warning(f"GoToAngle: config load failed: {exc}")
            self._config_loaded_at = now
        return self._config

    def _busy(self, stepper: "StepperMotor") -> bool:
        return time.monotonic() < self._busy_until.get(stepper._name, 0.0)

    def _move(
        self,
        label: str,
        stepper: "StepperMotor",
        output_deg: float,
        settle_ms: int,
        cfg: GoToAngleConfig,
        enforce_min: bool = True,
    ) -> bool:
        if self._busy(stepper):
            return False
        speed = int(cfg.move_speed_usteps_per_s)
        output_deg = abs(output_deg)
        if enforce_min:
            output_deg = max(cfg.min_move_output_deg, output_deg)
        output_deg = min(cfg.max_move_output_deg, output_deg)
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        motor_deg = sign * output_deg * CHANNEL_OUTPUT_GEAR_RATIO
        # Set the move speed and tell the motor to move to the angle — that's it.
        # We NEVER set acceleration here; the motor keeps whatever acceleration it
        # already has.
        try:
            stepper.set_speed_limits(0, speed)
        except Exception as exc:
            self.gc.logger.warning(f"GoToAngle: {label} speed set failed: {exc}")
        success = stepper.move_degrees(motor_deg)
        exec_ms = stepper.estimateMoveDegreesMs(
            abs(motor_deg), max_speed=speed or 5000
        )
        cooldown_ms = (max(0, exec_ms) + max(0, settle_ms)) if success else 500
        self._busy_until[stepper._name] = time.monotonic() + cooldown_ms / 1000.0
        self.gc.logger.info(
            f"GoToAngle: {label} move output={output_deg:.1f}° motor={motor_deg:.1f}° "
            f"success={success} exec_ms={exec_ms} settle_ms={settle_ms}"
        )
        return success

    def _pieces_for_channel(
        self, detections: list[ChannelDetection], channel_id: int
    ) -> list[tuple[float, ChannelDetection]]:
        out: list[tuple[float, ChannelDetection]] = []
        for det in detections:
            if det.channel_id != channel_id:
                continue
            rel = geometry.pieceRelativeAngle(det.bbox, det.channel)
            out.append((rel, det))
        return out

    def _piece_at_exit(
        self, channel_id: int, detections: list[ChannelDetection]
    ) -> bool:
        pieces = self._pieces_for_channel(detections, channel_id)
        for rel, det in pieces:
            if geometry.sectionForRelativeAngle(rel) in det.channel.exit_sections:
                return True
        return False

    def _service_channel(
        self,
        label: str,
        channel_id: int,
        stepper: "StepperMotor",
        detections: list[ChannelDetection],
        downstream_ready: bool,
        cfg: GoToAngleConfig,
    ) -> bool:
        if self._busy(stepper):
            return False
        pieces = self._pieces_for_channel(detections, channel_id)
        if not pieces:
            return False
        channel = pieces[0][1].channel
        exit_sections = channel.exit_sections

        at_exit = any(
            geometry.sectionForRelativeAngle(rel) in exit_sections
            for (rel, _) in pieces
        )
        if at_exit:
            # The ONLY condition under which a channel holds still: it has a
            # piece at its exit and the downstream channel can't accept it yet.
            # Precise mode otherwise — nudge one small fixed angle at a time,
            # pausing between pulses so the downstream channel can register the
            # piece before we push again. Each tick re-reads vision, so we stop
            # as soon as the piece clears the exit instead of dumping the train.
            if not downstream_ready:
                return False
            return self._move(
                f"{label}_precise",
                stepper,
                cfg.precise_pulse_output_deg,
                cfg.precise_pulse_pause_ms,
                cfg,
                enforce_min=False,
            )

        # No piece at the exit: advance freely to carry pieces forward and clear
        # this channel's own drop zone. Downstream readiness is irrelevant here —
        # channels run in parallel and only the exit push waits on downstream.
        return self._move(
            f"{label}_advance", stepper, cfg.advance_output_deg, cfg.settle_after_move_ms, cfg
        )

    def _on_ch3_dispense(self) -> None:
        if hasattr(self.shared, "publish_piece_delivered"):
            try:
                self.shared.publish_piece_delivered(
                    source=StationId.C3,
                    target=StationId.CLASSIFICATION,
                    delivered_at_mono=time.monotonic(),
                )
            except Exception:
                pass
        self._classification_pending_until = (
            time.monotonic() + CLASSIFICATION_PENDING_ADMISSION_MS / 1000.0
        )

    def _classification_ready(self, cfg: GoToAngleConfig) -> bool:
        if not cfg.gate_ch3_on_classification_ready or not self._classification_setup:
            return True
        if time.monotonic() < self._classification_pending_until:
            return False
        return bool(self.shared.classification_ready)

    # ---------------------------------------------------------------------
    # Fast-eject controllers (perception path only).
    #
    # A channel running in fast-eject mode hands its exit handling to a
    # per-channel ``EjectController`` (see eject.py) instead of precise pulsing.
    # Controllers are built lazily on first use because the steppers may not be
    # ready at __init__ (e.g. in test contexts). Jitter recovery now lives
    # entirely inside the controller — it is the only place the feeder jitters.
    # ---------------------------------------------------------------------

    def _channel_stepper(self, ch: int):
        if ch == 2:
            return self.irl.c_channel_2_rotor_stepper
        if ch == 3:
            return self.irl.c_channel_3_rotor_stepper
        return None

    def _fast_eject_enabled(self, ch: int, cfg: GoToAngleConfig) -> bool:
        if ch == 2:
            return bool(cfg.ch2_fast_eject_enabled)
        if ch == 3:
            return bool(cfg.ch3_fast_eject_enabled)
        return False

    def _get_eject_controller(
        self, ch: int, cfg: GoToAngleConfig, perception_service
    ) -> Optional[EjectController]:
        ctrl = self._eject_controllers.get(ch)
        if ctrl is not None:
            return ctrl
        stepper = self._channel_stepper(ch)
        if stepper is None:
            return None

        def _advance_move(output_deg: float, _stepper=stepper) -> bool:
            # One closed-loop advance step: just tell the motor to move that many
            # channel-degrees at the normal move speed. Like every move here, it
            # never touches acceleration. Completion is detected by polling the
            # stepper's stopped state (see _is_stopped), not a time estimate.
            return self._move(
                f"ch{ch}_eject",
                _stepper,
                output_deg,
                cfg.settle_after_move_ms,
                cfg,
                enforce_min=False,
            )

        def _is_stopped(_stepper=stepper) -> bool:
            # One cheap firmware round-trip. On any query error, report stopped so
            # the controller keeps progressing rather than hanging mid-advance.
            try:
                return bool(_stepper.stopped)
            except Exception:
                return True

        on_success = self._on_ch3_dispense if ch == 3 else (lambda: None)
        ctrl = EjectController(
            channel_id=ch,
            stepper=stepper,
            is_stopped=_is_stopped,
            advance_move=_advance_move,
            on_success=on_success,
            logger=self.gc.logger,
        )
        self._eject_controllers[ch] = ctrl
        return ctrl

    def step(self) -> Optional[FeederState]:
        cfg = self._cfg()
        runtime_stats = self.gc.runtime_stats

        can_run_started = time.perf_counter()
        can_run = self.gc.rotary_channel_steppers_can_operate_in_parallel or (
            not self.shared.chute_move_in_progress
        )
        runtime_stats.observePerfMs(
            "feeder.go_to_angle.can_run_ms",
            (time.perf_counter() - can_run_started) * 1000.0,
        )
        if not can_run:
            return FeederState.FEEDING

        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is not None:
            return self._step_perception(cfg, perception_service)

        detections_started = time.perf_counter()
        detections = self.vision.getFeederHeatmapDetections()
        runtime_stats.observePerfMs(
            "feeder.go_to_angle.get_feeder_detections_ms",
            (time.perf_counter() - detections_started) * 1000.0,
        )
        detection_available_started = time.perf_counter()
        detection_available, _reason = self.vision.getFeederDetectionAvailability()
        runtime_stats.observePerfMs(
            "feeder.go_to_angle.detection_availability_ms",
            (time.perf_counter() - detection_available_started) * 1000.0,
        )
        if not detection_available:
            return FeederState.FEEDING

        analyze_started = time.perf_counter()
        analysis = analyzeFeederChannels(detections)
        runtime_stats.observePerfMs(
            "feeder.go_to_angle.analyze_state_ms",
            (time.perf_counter() - analyze_started) * 1000.0,
        )

        # Channels run in parallel and independently. Each one advances freely
        # to clear its own drop zone; only its exit push waits on the downstream
        # channel being ready to accept (C3 -> C4 classification, C2 -> C3,
        # C1 -> C2).
        if cfg.enable_ch3:
            classification_ready_started = time.perf_counter()
            classification_ready = self._classification_ready(cfg)
            runtime_stats.observePerfMs(
                "feeder.go_to_angle.classification_ready_ms",
                (time.perf_counter() - classification_ready_started) * 1000.0,
            )
            ch3_step_started = time.perf_counter()
            self._service_channel(
                "ch3",
                3,
                self.irl.c_channel_3_rotor_stepper,
                detections,
                downstream_ready=classification_ready,
                cfg=cfg,
            )
            runtime_stats.observePerfMs(
                "feeder.go_to_angle.ch3_step_ms",
                (time.perf_counter() - ch3_step_started) * 1000.0,
            )
            # A piece counts as delivered the moment it clears C3's exit zone
            # (the precise pulses stop on their own once vision no longer sees
            # it there). Fire the downstream notification + admission window
            # once on that falling edge, not on every micro-pulse.
            ch3_exit_check_started = time.perf_counter()
            ch3_at_exit_now = self._piece_at_exit(3, detections)
            runtime_stats.observePerfMs(
                "feeder.go_to_angle.ch3_exit_check_ms",
                (time.perf_counter() - ch3_exit_check_started) * 1000.0,
            )
            if self._ch3_was_at_exit and not ch3_at_exit_now:
                self._on_ch3_dispense()
            self._ch3_was_at_exit = ch3_at_exit_now
        if cfg.enable_ch2:
            ch2_step_started = time.perf_counter()
            self._service_channel(
                "ch2",
                2,
                self.irl.c_channel_2_rotor_stepper,
                detections,
                downstream_ready=not analysis.ch3_dropzone_occupied,
                cfg=cfg,
            )
            runtime_stats.observePerfMs(
                "feeder.go_to_angle.ch2_step_ms",
                (time.perf_counter() - ch2_step_started) * 1000.0,
            )
        if cfg.enable_ch1:
            stepper = self.irl.c_channel_1_rotor_stepper
            ch1_gate_started = time.perf_counter()
            ch1_can_move = not analysis.ch2_dropzone_occupied and not self._busy(stepper)
            runtime_stats.observePerfMs(
                "feeder.go_to_angle.ch1_gate_ms",
                (time.perf_counter() - ch1_gate_started) * 1000.0,
            )
            if ch1_can_move:
                ch1_step_started = time.perf_counter()
                self._move(
                    "ch1", stepper, cfg.ch1_advance_output_deg, cfg.ch1_settle_after_move_ms, cfg
                )
                runtime_stats.observePerfMs(
                    "feeder.go_to_angle.ch1_step_ms",
                    (time.perf_counter() - ch1_step_started) * 1000.0,
                )

        return FeederState.FEEDING

    # ---------------------------------------------------------------------
    # Rev04 perception path
    # ---------------------------------------------------------------------

    def _step_perception(self, cfg: GoToAngleConfig, perception_service) -> Optional[FeederState]:
        """The new mode-pair flow: read perception state, apply cascade, move.

        No detection list, no analyzeFeederChannels, no per-channel filter,
        no in-flow tracker/handoff. The cascade is a pure function over
        ``ChannelState`` booleans; this method just dispatches its output
        to the existing ``_move`` machinery.
        """
        from perception.cascade import Action, cascade
        from perception.state import EMPTY_STATE

        runtime_stats = self.gc.runtime_stats
        t0 = time.perf_counter()
        states = perception_service.read_states()
        runtime_stats.observePerfMs(
            "feeder.go_to_angle.read_states_ms",
            (time.perf_counter() - t0) * 1000.0,
        )
        c2 = states.get(2, EMPTY_STATE)
        c3 = states.get(3, EMPTY_STATE)
        c4 = states.get(4, EMPTY_STATE)
        actions = cascade(c2, c3, c4)

        now_mono = time.monotonic()

        if cfg.enable_ch3:
            # C3's downstream is the classification channel (C4). Ready = C4
            # empty AND past the post-dispense admission window.
            c3_downstream_ready = (
                c4.n_pieces == 0 and now_mono >= self._classification_pending_until
            )
            # Extra hold: if the classification camera sees a piece sitting in
            # C3's annotated exit zone (a secondary/foreign zone on channel 4)
            # while classification is not ready, freeze C3 so we don't shove it
            # forward into a busy C4. No-op until such a zone is drawn — the
            # accessor returns False when no C3 secondary zone exists.
            if (
                not self._classification_ready(cfg)
                and perception_service.secondary_zone_occupied(4, source_channel=3)
            ):
                c3_downstream_ready = False
            self._drive_channel(
                "ch3", 3, actions.c3, c3, c4, c3_downstream_ready,
                self.irl.c_channel_3_rotor_stepper, cfg, perception_service, now_mono,
            )
        if cfg.enable_ch2:
            self._drive_channel(
                "ch2", 2, actions.c2, c2, c3, not c3.in_drop,
                self.irl.c_channel_2_rotor_stepper, cfg, perception_service, now_mono,
            )
        # C1 has no exit zone of its own — no fast-eject / recovery applies.
        if cfg.enable_ch1:
            stepper = self.irl.c_channel_1_rotor_stepper
            if actions.c1 == Action.ADVANCE and not self._busy(stepper):
                self._move(
                    "ch1",
                    stepper,
                    cfg.ch1_advance_output_deg,
                    cfg.ch1_settle_after_move_ms,
                    cfg,
                )

        return FeederState.FEEDING

    def _drive_channel(
        self,
        label: str,
        ch: int,
        action,
        state,
        downstream,
        downstream_ready: bool,
        stepper: "StepperMotor",
        cfg: GoToAngleConfig,
        perception_service,
        now: float,
    ) -> None:
        """Drive one feeder channel for a perception tick. Fast-eject channels
        hand their exit handling to the per-channel EjectController; when the
        controller does not take the tick (piece not near the exit), or for
        precise-mode channels, fall back to the normal cascade action."""
        if self._fast_eject_enabled(ch, cfg):
            ctrl = self._get_eject_controller(ch, cfg, perception_service)
            if ctrl is not None:
                consumed = ctrl.tick(
                    state=state,
                    downstream=downstream,
                    downstream_ready=downstream_ready,
                    cfg=cfg,
                    now=now,
                )
                if consumed:
                    return
                # Not consumed ⇒ the controller is idle and the piece isn't near
                # the exit. Run the normal drop-zone advance/idle. The controller
                # owns every in-exit case, so ``action`` here is ADVANCE/IDLE,
                # never PRECISE.
        self._apply_action(
            label, action, stepper, cfg, advance_clearance_deg=state.advance_clearance_deg
        )

    def _apply_action(
        self,
        label: str,
        action,
        stepper: "StepperMotor",
        cfg: GoToAngleConfig,
        advance_clearance_deg: float | None = None,
    ) -> None:
        from perception.cascade import Action

        if self._busy(stepper):
            return
        if action == Action.ADVANCE:
            # Free advance to clear the drop zone, but never push the
            # most-forward piece into the exit zone: cap the move to its
            # forward distance to the exit edge. Once the piece reaches the
            # exit, the PRECISE/FREEZE branch (gated on downstream readiness)
            # meters it out instead of this ungated advance dumping it through.
            output_deg = cfg.advance_output_deg
            enforce_min = True
            if (
                advance_clearance_deg is not None
                and advance_clearance_deg < output_deg
            ):
                output_deg = advance_clearance_deg
                enforce_min = False
            self._move(
                f"{label}_advance",
                stepper,
                output_deg,
                cfg.settle_after_move_ms,
                cfg,
                enforce_min=enforce_min,
            )
        elif action == Action.PRECISE:
            self._move(
                f"{label}_precise",
                stepper,
                cfg.precise_pulse_output_deg,
                cfg.precise_pulse_pause_ms,
                cfg,
                enforce_min=False,
            )
        # IDLE / FREEZE: no move.

    def cleanup(self) -> None:
        super().cleanup()
        for ctrl in self._eject_controllers.values():
            ctrl.reset()
