import time
from dataclasses import replace
from typing import Optional, TYPE_CHECKING

from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from subsystems.bus import StationId
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from vision import VisionManager

from ..states import FeederState
from .config import PulsePerceptionConfig

# A deliberately simple pulsing state machine on the new perception stack.
#
# It reads ChannelState booleans from the perception service (exactly like the
# go-to-angle flow's perception path) and, per channel, does one of three
# things each tick:
#   - piece in the EXIT zone + downstream ready   -> pulse exit_pulse_output_deg,
#                                                     pause exit_pulse_pause_ms
#   - piece in the EXIT zone + downstream NOT ready -> hold still (never pulse a
#                                                     piece off the edge into a
#                                                     busy downstream channel)
#   - piece in the DROP zone only                 -> pulse drop_pulse_output_deg,
#                                                     pause drop_pulse_pause_ms
#   - empty channel                               -> idle
#
# No fast-eject, no COM closed loop, no jitter recovery — that all lives in the
# go-to-angle flow. "The other stack will be removed in time"; this is the
# minimal perception-native feeder.

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor

# Motor-shaft to channel-output gear ratio. One output (LEGO wheel) degree
# requires this many motor degrees. Matches the go-to-angle flow's constant.
CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0

# Re-read the tuning config from disk at most this often so the tuning page
# takes effect live without a restart, without hammering the filesystem.
_CONFIG_TTL_S = 1.0

# After a C3 exit dispense, keep C3 blocked this long so the in-flight piece
# can register downstream before we consider another move.
CLASSIFICATION_PENDING_ADMISSION_MS = 1500


class PulsePerceptionFeeding(BaseState):
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
        self._config: PulsePerceptionConfig = PulsePerceptionConfig()
        self._config_loaded_at: float = 0.0
        self._classification_pending_until: float = 0.0
        self._ch3_was_at_exit: bool = False
        # Per-channel monotonic timestamp of the last frame that reported a piece
        # in the drop zone. Drives the C2/C3 drop-zone occupancy latch.
        self._drop_seen_at: dict[int, float] = {}
        machine_setup = getattr(irl_config, "machine_setup", None)
        self._classification_setup = bool(
            machine_setup is not None
            and getattr(machine_setup, "uses_classification_channel", False)
        )

    def _cfg(self) -> PulsePerceptionConfig:
        now = time.monotonic()
        if now - self._config_loaded_at >= _CONFIG_TTL_S:
            try:
                from toml_config import getPulsePerceptionConfig
                from .config import configFromDict
                self._config = configFromDict(getPulsePerceptionConfig())
            except Exception as exc:
                self.gc.logger.warning(f"PulsePerception: config load failed: {exc}")
            self._config_loaded_at = now
        return self._config

    def _busy(self, stepper: "StepperMotor") -> bool:
        return time.monotonic() < self._busy_until.get(stepper._name, 0.0)

    def _move(
        self,
        label: str,
        stepper: "StepperMotor",
        output_deg: float,
        pause_ms: int,
        cfg: PulsePerceptionConfig,
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
            self.gc.logger.warning(f"PulsePerception: {label} speed set failed: {exc}")
        success = stepper.move_degrees(motor_deg)
        exec_ms = stepper.estimateMoveDegreesMs(abs(motor_deg), max_speed=speed or 5000)
        cooldown_ms = (max(0, exec_ms) + max(0, pause_ms)) if success else 500
        self._busy_until[stepper._name] = time.monotonic() + cooldown_ms / 1000.0
        self.gc.logger.info(
            f"PulsePerception: {label} pulse output={output_deg:.1f}° motor={motor_deg:.1f}° "
            f"success={success} exec_ms={exec_ms} pause_ms={pause_ms}"
        )
        return success

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

    def _classification_ready(self, cfg: PulsePerceptionConfig) -> bool:
        if not cfg.gate_ch3_on_classification_ready or not self._classification_setup:
            return True
        if time.monotonic() < self._classification_pending_until:
            return False
        return bool(self.shared.classification_ready)

    def _latch_drop(self, ch: int, state, now: float, cfg: PulsePerceptionConfig):
        """Persist drop-zone occupancy for one feeder channel.

        Once a piece is seen in the drop zone we consider the zone occupied for
        ``drop_zone_persistence_ms`` after the last positive frame — a one/two
        frame detection dropout no longer reads as 'empty'. Only ``in_drop`` is
        latched; the exit fields pass through untouched so exit handling still
        sees the live state. 0 disables the latch."""
        window_ms = cfg.drop_zone_persistence_ms
        if window_ms <= 0:
            return state
        if state.in_drop:
            self._drop_seen_at[ch] = now
            return state
        last = self._drop_seen_at.get(ch)
        if last is not None and (now - last) * 1000.0 <= window_ms:
            return replace(state, in_drop=True)
        return state

    def step(self) -> Optional[FeederState]:
        cfg = self._cfg()

        can_run = self.gc.rotary_channel_steppers_can_operate_in_parallel or (
            not self.shared.chute_move_in_progress
        )
        if not can_run:
            return FeederState.FEEDING

        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return FeederState.FEEDING

        from perception.cascade import Action, feederChannelAction, c1Action
        from perception.state import EMPTY_STATE

        states = perception_service.read_states()
        c2 = states.get(2, EMPTY_STATE)
        c3 = states.get(3, EMPTY_STATE)
        c4 = states.get(4, EMPTY_STATE)

        now_mono = time.monotonic()
        # Hold C2/C3 drop-zone occupancy across brief detector dropouts so the
        # per-channel action (and the ``not c3.in_drop`` upstream gate below) see
        # a stable "occupied" instead of flickering empty for a frame.
        c2 = self._latch_drop(2, c2, now_mono, cfg)
        c3 = self._latch_drop(3, c3, now_mono, cfg)

        if cfg.enable_ch3:
            # C3's downstream is the classification channel (C4). The feeder does
            # NOT define "ready" itself — that determination is owned and exposed
            # by the classification channel (shared.classification_ready, set per
            # its active mode: single-piece = whole channel empty, two-piece = drop
            # zone clear). The feeder just asks. The only feeder-side gate is the
            # post-dispense admission window (let an in-flight piece register first).
            c3_downstream_ready = (
                now_mono >= self._classification_pending_until
                and self._classification_ready(cfg)
            )
            action = feederChannelAction(
                c3, downstream_clear=c3_downstream_ready, greedy=cfg.ch3_greedy_enabled
            )
            self._apply_action(
                "ch3", action, self.irl.c_channel_3_rotor_stepper, c3, cfg
            )
            # A piece counts as delivered the moment it clears C3's exit zone
            # (the precise pulses stop on their own once perception no longer
            # sees it there). Fire the downstream notification + admission window
            # once on that falling edge, not on every micro-pulse.
            ch3_at_exit_now = c3.in_exit
            if self._ch3_was_at_exit and not ch3_at_exit_now:
                self._on_ch3_dispense()
            self._ch3_was_at_exit = ch3_at_exit_now

        if cfg.enable_ch2:
            # C2's downstream is C3. "Clear" = C3's drop zone is not occupied,
            # so we never pulse a C2 piece off the edge into a busy C3.
            action = feederChannelAction(
                c2, downstream_clear=not c3.in_drop, greedy=cfg.ch2_greedy_enabled
            )
            self._apply_action(
                "ch2", action, self.irl.c_channel_2_rotor_stepper, c2, cfg
            )

        if cfg.enable_ch1:
            # C1 has no exit zone of its own; it just advances unless C2's drop
            # zone is occupied.
            stepper = self.irl.c_channel_1_rotor_stepper
            if c1Action(c2) == Action.ADVANCE and not self._busy(stepper):
                self._move(
                    "ch1",
                    stepper,
                    cfg.ch1_pulse_output_deg,
                    cfg.ch1_pulse_pause_ms,
                    cfg,
                )

        return FeederState.FEEDING

    def _apply_action(
        self,
        label: str,
        action,
        stepper: "StepperMotor",
        state,
        cfg: PulsePerceptionConfig,
    ) -> None:
        from perception.cascade import Action

        if self._busy(stepper):
            return
        if action == Action.ADVANCE:
            # Free advance pulse, but never push the most-forward piece off the
            # edge into the exit zone: cap the move to its forward clearance to
            # the exit edge. Once a piece reaches the exit, the PRECISE/FREEZE
            # branch (gated on downstream readiness) meters it out instead.
            # A piece still in the drop zone uses the drop-zone params; a greedy
            # advance of a piece that has already left the drop zone uses the
            # greedy params (only reachable when greedy mode is on for this
            # channel — the cascade returns IDLE here otherwise).
            if state.in_drop:
                output_deg = cfg.drop_pulse_output_deg
                pause_ms = cfg.drop_pulse_pause_ms
                move_label = f"{label}_drop"
            else:
                output_deg = cfg.greedy_pulse_output_deg
                pause_ms = cfg.greedy_pulse_pause_ms
                move_label = f"{label}_greedy"
            enforce_min = True
            clearance = getattr(state, "advance_clearance_deg", None)
            if clearance is not None and clearance < output_deg:
                output_deg = clearance
                enforce_min = False
            self._move(
                move_label,
                stepper,
                output_deg,
                pause_ms,
                cfg,
                enforce_min=enforce_min,
            )
        elif action == Action.PRECISE:
            self._move(
                f"{label}_exit",
                stepper,
                cfg.exit_pulse_output_deg,
                cfg.exit_pulse_pause_ms,
                cfg,
                enforce_min=False,
            )
        # IDLE / FREEZE: no move.

    def cleanup(self) -> None:
        super().cleanup()
