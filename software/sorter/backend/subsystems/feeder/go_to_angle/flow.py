import time
from typing import Optional, TYPE_CHECKING

from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from subsystems.bus import StationId
from defs.channel import ChannelDetection
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager

from subsystems.common.jitter_recovery import JitterParams, JitterPhase, JitterSequence

from ..states import FeederState
from ..analysis import analyzeFeederChannels
from .config import GoToAngleConfig
from . import geometry

# Jitter unstick (per-channel, exit-only dwell → up to 3 oscillations) is wired
# into the Rev04 perception sub-path only — see ``_jitter_tick`` and its calls
# from ``_step_perception``. The legacy-vision sub-path (``_step_detections``)
# intentionally does not run the jitter recovery.

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
        # Per-channel exit-only dwell tracker (when the start condition fires).
        # The jitter sequence itself lives in ``_jitter_seqs`` and is lazily
        # constructed on first trigger (steppers may not be ready at __init__
        # in test contexts).
        self._exit_only_dwell_started: dict[int, Optional[float]] = {2: None, 3: None}
        self._jitter_seqs: dict[int, JitterSequence] = {}
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
        output_deg = abs(output_deg)
        if enforce_min:
            output_deg = max(cfg.min_move_output_deg, output_deg)
        output_deg = min(cfg.max_move_output_deg, output_deg)
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        motor_deg = sign * output_deg * CHANNEL_OUTPUT_GEAR_RATIO
        try:
            stepper.set_speed_limits(0, int(cfg.move_speed_usteps_per_s))
            stepper.set_acceleration(int(cfg.move_acceleration_usteps_per_s2))
        except Exception as exc:
            self.gc.logger.warning(f"GoToAngle: {label} speed/accel set failed: {exc}")
        success = stepper.move_degrees(motor_deg)
        exec_ms = stepper.estimateMoveDegreesMs(
            abs(motor_deg), max_speed=int(cfg.move_speed_usteps_per_s) or 5000
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
    # Jitter unstick — perception path only.
    #
    # When a piece sits in the exit-only sub-arc (NOT the precise arc — the
    # precise zone is the normal hand-off region to the classification
    # channel and is expected to be occupied during precise pulses) for
    # ``jitter_exit_dwell_ms`` continuously, oscillate the channel rotor to
    # unstick it. Up to 3 attempts per continuous dwell, with a short pause
    # between attempts. If the piece leaves the exit-only zone at any point
    # the recovery is abandoned and the attempt counter resets on the next
    # entry. After 3 attempts the channel resumes normal advance/precise
    # behavior (no extra forward nudge).
    #
    # Jitter itself is run-to-completion on the firmware. Python never
    # re-issues a jitter while ``is_jittering()`` is True, and skips all
    # normal motion for the channel while jitter or its inter-attempt pause
    # is active so we don't fight the oscillation.
    # ---------------------------------------------------------------------

    def _channel_stepper(self, ch: int):
        if ch == 2:
            return self.irl.c_channel_2_rotor_stepper
        if ch == 3:
            return self.irl.c_channel_3_rotor_stepper
        return None

    def _get_jitter_seq(self, ch: int, cfg: GoToAngleConfig) -> Optional[JitterSequence]:
        seq = self._jitter_seqs.get(ch)
        if seq is not None:
            return seq
        stepper = self._channel_stepper(ch)
        if stepper is None:
            return None
        seq = JitterSequence(
            stepper,
            JitterParams(
                amplitude_motor_deg=cfg.jitter_amplitude_motor_deg,
                cycles=int(cfg.jitter_cycles),
                speed_usteps_per_s=int(cfg.jitter_speed_usteps_per_s),
                accel_usteps_per_s2=int(cfg.jitter_accel_usteps_per_s2),
                pause_ms=int(cfg.jitter_pause_ms),
                max_attempts=3,
            ),
            label=f"GoToAngle: ch{ch}",
            logger=self.gc.logger,
        )
        self._jitter_seqs[ch] = seq
        return seq

    def _jitter_tick(
        self,
        ch: int,
        in_exit_majority: bool,
        cfg: GoToAngleConfig,
        now: float,
    ) -> bool:
        """Drive the per-channel jitter recovery for one tick.

        ``in_exit_majority`` is True when the piece's bbox has strictly more
        sample points in the exit-only sub-arc than in the precise arc — i.e.
        the piece is "mostly in the exit zone, not the precise zone." This is
        the dwell trigger condition.

        Returns True if the caller must skip normal advance/precise for this
        channel this tick (firmware is jittering, or we are in the
        inter-attempt pause, or we just issued a jitter).
        """
        seq = self._get_jitter_seq(ch, cfg)
        if seq is None:
            return False

        # Majority-in-exit-zone dwell trigger. Reset both the dwell timer AND
        # the sequence when the piece is no longer majority-in-exit — the next
        # entry gets a fresh 3 attempts.
        if not in_exit_majority:
            self._exit_only_dwell_started[ch] = None
            if seq.is_active:
                seq.reset()
            return False

        dwell_start = self._exit_only_dwell_started.get(ch)
        if dwell_start is None:
            dwell_start = now
            self._exit_only_dwell_started[ch] = dwell_start
            self.gc.logger.info(
                f"[jitter ch{ch}] exit-majority dwell timer STARTED "
                f"(threshold={cfg.jitter_exit_dwell_ms}ms)"
            )
        dwell_ms = (now - dwell_start) * 1000.0

        if not seq.is_active and dwell_ms >= cfg.jitter_exit_dwell_ms:
            self.gc.logger.info(
                f"[jitter ch{ch}] TRIGGERED — dwell={dwell_ms:.0f}ms "
                f">= threshold={cfg.jitter_exit_dwell_ms}ms, starting JitterSequence"
            )
            seq.start()

        if not seq.is_active:
            return False

        phase = seq.tick(still_stuck=in_exit_majority, now=now)
        # CLEARED / EXHAUSTED both leave seq IDLE. After exhaustion the feeder
        # has no recovery action — the channel just resumes normal motion next
        # tick, which is what the caller wants when we return False.
        return phase not in (JitterPhase.IDLE, JitterPhase.CLEARED, JitterPhase.EXHAUSTED)

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
        c1 = states.get(1, EMPTY_STATE)
        c2 = states.get(2, EMPTY_STATE)
        c3 = states.get(3, EMPTY_STATE)
        c4 = states.get(4, EMPTY_STATE)
        actions = cascade(c2, c3, c4)

        now_mono = time.monotonic()

        if cfg.enable_ch3:
            if not self._jitter_tick(
                3, bool(c3.in_exit_majority), cfg, now_mono
            ):
                self._apply_action(
                    "ch3", actions.c3, self.irl.c_channel_3_rotor_stepper, cfg,
                    advance_clearance_deg=c3.advance_clearance_deg,
                )
        if cfg.enable_ch2:
            if not self._jitter_tick(
                2, bool(c2.in_exit_majority), cfg, now_mono
            ):
                self._apply_action(
                    "ch2", actions.c2, self.irl.c_channel_2_rotor_stepper, cfg,
                    advance_clearance_deg=c2.advance_clearance_deg,
                )
        # C1 has no exit zone of its own — no jitter recovery applies.
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
        for seq in self._jitter_seqs.values():
            seq.reset()
        self._exit_only_dwell_started = {2: None, 3: None}
