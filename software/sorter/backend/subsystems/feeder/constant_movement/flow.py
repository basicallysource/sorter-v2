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
from .config import ConstantMovementConfig

# Constant-movement feeder on the perception stack.
#
# Inverts the pulse model: instead of "stationary by default, pulse forward
# when perception says go", each channel runs CONTINUOUSLY at its own constant
# speed and is only STOPPED when a specific condition holds:
#   - C1 stops while C2's drop zone is occupied
#   - C2 stops while C3's drop zone is occupied
#   - C3 stops while a piece is at its exit edge AND the classification channel
#     cannot accept it (drop zone occupied, not ready, or inside the
#     post-dispense window). With nothing at the exit edge C3 keeps running
#     even when classification is busy — the hold only matters when a piece is
#     about to go over the edge.
# All-stop conditions: paused/teardown (cleanup), active incident or manual
# feed (hold_motion via the coordinator), chute move in progress when the
# rotary channels may not run in parallel, or no perception service.
#
# Motion uses the firmware's continuous velocity command (move_at_speed); a
# stop is move_at_speed(0). Commands are only sent on speed CHANGES, so the
# steady state adds no serial traffic.

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor

# Motor-shaft to channel-output gear ratio. One output (LEGO wheel) degree
# requires this many motor degrees. Matches the other feeder flows' constant.
CHANNEL_OUTPUT_GEAR_RATIO = 130.0 / 12.0

# Microsteps per motor revolution (200 full steps x 8 microsteps) — used to
# convert output deg/s to the firmware's µsteps/s.
MICROSTEPS_PER_MOTOR_REV = 1600

USTEPS_PER_OUTPUT_DEG = MICROSTEPS_PER_MOTOR_REV * CHANNEL_OUTPUT_GEAR_RATIO / 360.0

# Re-read the tuning config from disk at most this often so the tuning page
# takes effect live without a restart, without hammering the filesystem.
_CONFIG_TTL_S = 1.0


class ConstantMovementFeeding(BaseState):
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
        self._config: ConstantMovementConfig = ConstantMovementConfig()
        self._config_loaded_at: float = 0.0
        self._classification_pending_until: float = 0.0
        self._ch3_was_at_exit: bool = False
        # Last speed (signed logical µsteps/s) actually acknowledged per stepper;
        # commands are only sent when the desired speed differs.
        self._applied_speed: dict[str, int] = {}
        # Max speed already asserted via set_speed_limits, per stepper.
        self._applied_speed_limit: dict[str, int] = {}
        # Per-channel monotonic timestamp since which the channel's stop
        # condition has been continuously clear (drives resume_delay_ms).
        self._clear_since: dict[str, float] = {}
        # Per-channel monotonic timestamp of the last frame that reported a piece
        # in the drop zone. Drives the drop-zone occupancy latch.
        self._drop_seen_at: dict[int, float] = {}
        machine_setup = getattr(irl_config, "machine_setup", None)
        self._classification_setup = bool(
            machine_setup is not None
            and getattr(machine_setup, "uses_classification_channel", False)
        )

    def _cfg(self) -> ConstantMovementConfig:
        now = time.monotonic()
        if now - self._config_loaded_at >= _CONFIG_TTL_S:
            try:
                from toml_config import getConstantMovementConfig
                from .config import configFromDict
                self._config = configFromDict(getConstantMovementConfig())
            except Exception as exc:
                self.gc.logger.warning(f"ConstantMovement: config load failed: {exc}")
            self._config_loaded_at = now
        return self._config

    def _setSpeed(self, label: str, stepper: "StepperMotor", speed_usteps: int) -> None:
        name = stepper._name
        if self._applied_speed.get(name) == speed_usteps:
            return
        magnitude = abs(speed_usteps)
        if magnitude > 0 and self._applied_speed_limit.get(name) != magnitude:
            try:
                stepper.set_speed_limits(0, magnitude)
                self._applied_speed_limit[name] = magnitude
            except Exception as exc:
                self.gc.logger.warning(
                    f"ConstantMovement: {label} speed limit set failed: {exc}"
                )
        success = stepper.move_at_speed(speed_usteps)
        if success:
            self._applied_speed[name] = speed_usteps
            self.gc.logger.info(
                f"ConstantMovement: {label} "
                + ("stopped" if speed_usteps == 0 else f"running at {speed_usteps} µsteps/s")
            )
        else:
            # Leave the cache unset so the next tick retries the command.
            self._applied_speed.pop(name, None)
            self.gc.logger.warning(
                f"ConstantMovement: {label} move_at_speed({speed_usteps}) failed"
            )

    def _applyChannel(
        self,
        label: str,
        stepper: "StepperMotor",
        should_run: bool,
        speed_output_deg_per_s: float,
        cfg: ConstantMovementConfig,
        now: float,
    ) -> None:
        if not should_run:
            self._clear_since.pop(label, None)
            self._setSpeed(label, stepper, 0)
            return
        # Stop condition is clear — hold off restarting until it has stayed
        # clear for resume_delay_ms so detection flicker can't chatter the motor.
        since = self._clear_since.setdefault(label, now)
        if (now - since) * 1000.0 < max(0, cfg.resume_delay_ms):
            self._setSpeed(label, stepper, 0)
            return
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        speed_usteps = int(round(abs(speed_output_deg_per_s) * USTEPS_PER_OUTPUT_DEG))
        self._setSpeed(label, stepper, sign * speed_usteps)

    def _stopAll(self) -> None:
        self._clear_since.clear()
        self._setSpeed("ch1", self.irl.c_channel_1_rotor_stepper, 0)
        self._setSpeed("ch2", self.irl.c_channel_2_rotor_stepper, 0)
        self._setSpeed("ch3", self.irl.c_channel_3_rotor_stepper, 0)

    def hold_motion(self) -> None:
        """Stop all channels while the coordinator is not stepping the feeder
        (active incident, manual feed mode). Idempotent and cheap: sends stop
        commands only for channels currently running."""
        self._stopAll()

    def _on_ch3_dispense(self, cfg: ConstantMovementConfig) -> None:
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
            time.monotonic() + max(0, cfg.post_dispense_block_ms) / 1000.0
        )

    def _classificationReady(self, cfg: ConstantMovementConfig, now: float) -> bool:
        if now < self._classification_pending_until:
            return False
        if not cfg.gate_ch3_on_classification_ready or not self._classification_setup:
            return True
        return bool(self.shared.classification_ready)

    def _latchDrop(self, ch: int, state, now: float, cfg: ConstantMovementConfig):
        """Persist drop-zone occupancy across brief detector dropouts (same
        latch as the pulse-perception flow, but also applied to C4 since C3's
        stop rule reads C4's drop zone directly)."""
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
            self._stopAll()
            return FeederState.FEEDING

        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            self._stopAll()
            return FeederState.FEEDING

        from perception.state import EMPTY_STATE

        states = perception_service.read_states()
        c2 = states.get(2, EMPTY_STATE)
        c3 = states.get(3, EMPTY_STATE)
        c4 = states.get(4, EMPTY_STATE)

        now = time.monotonic()
        c2 = self._latchDrop(2, c2, now, cfg)
        c3 = self._latchDrop(3, c3, now, cfg)
        c4 = self._latchDrop(4, c4, now, cfg)

        # A piece counts as dispensed the moment it clears C3's exit zone. Fire
        # the downstream notification + post-dispense window once on that
        # falling edge.
        ch3_at_exit_now = c3.in_exit
        if self._ch3_was_at_exit and not ch3_at_exit_now:
            self._on_ch3_dispense(cfg)
        self._ch3_was_at_exit = ch3_at_exit_now

        # C3: keep running unless a piece is at the exit edge and its downstream
        # (the classification channel) cannot take it right now — drop zone
        # occupied, not ready, or inside the post-dispense window.
        c3_downstream_open = (not c4.in_drop) and self._classificationReady(cfg, now)
        ch3_run = cfg.enable_ch3 and (c3_downstream_open or not c3.in_exit)
        self._applyChannel(
            "ch3",
            self.irl.c_channel_3_rotor_stepper,
            ch3_run,
            cfg.ch3_speed_output_deg_per_s,
            cfg,
            now,
        )

        # C2: keep running unless C3's drop zone is occupied.
        ch2_run = cfg.enable_ch2 and not c3.in_drop
        self._applyChannel(
            "ch2",
            self.irl.c_channel_2_rotor_stepper,
            ch2_run,
            cfg.ch2_speed_output_deg_per_s,
            cfg,
            now,
        )

        # C1 (bulk, no camera): keep running unless C2's drop zone is occupied.
        ch1_run = cfg.enable_ch1 and not c2.in_drop
        self._applyChannel(
            "ch1",
            self.irl.c_channel_1_rotor_stepper,
            ch1_run,
            cfg.ch1_speed_output_deg_per_s,
            cfg,
            now,
        )

        return FeederState.FEEDING

    def cleanup(self) -> None:
        self._stopAll()
        # Force a re-send on the next step: the applied cache is only trusted
        # while this state is continuously stepping.
        self._applied_speed.clear()
        self._applied_speed_limit.clear()
        super().cleanup()
