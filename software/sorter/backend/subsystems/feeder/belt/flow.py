import time
from typing import Optional, TYPE_CHECKING

from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from subsystems.shared_variables import SharedVariables
from vision import VisionManager

from ..states import FeederState
from ..pulse_perception.flow import PulsePerceptionFeeding, _CONFIG_TTL_S
from .config import BeltFeederConfig

# B1 belt topology (machine_setup "belt_feeder"): a cleated inclined conveyor
# replaces the C1 bulk bucket AND the C2 buffer channel. The belt lifts a few
# pieces per cleat out of the boat and drops them into C3; surplus tumbles back
# into the boat, so the belt self-meters and self-recirculates.
#
# Control model — constant-speed feeding instead of stop/go:
#   - C3 keeps the pulse-perception exit metering unchanged (final singulation
#     into the classification channel). We inherit that wholesale from
#     PulsePerceptionFeeding and force ch1/ch2 off — those motors don't exist
#     in this topology.
#   - The belt runs CONTINUOUSLY via move_at_speed, scaled by C3's perception
#     fill level (ChannelState.n_pieces): full speed while C3 wants pieces,
#     linear ramp down to a stop as C3 fills up. Because the boat buffers and
#     the cleats self-meter, this controller can be lazy — no per-piece
#     reactions, just a slow closed loop on channel occupancy.

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor


class BeltFeeding(PulsePerceptionFeeding):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision: VisionManager,
    ):
        super().__init__(irl, irl_config, gc, shared, vision)
        self._belt_config: BeltFeederConfig = BeltFeederConfig()
        self._belt_config_loaded_at: float = 0.0
        # Last speed actually commanded to the motor (signed, µsteps/s) and the
        # earliest time we may issue the next change.
        self._belt_cmd_speed: int = 0
        self._belt_next_cmd_at: float = 0.0
        self._belt_speed_limit: int = 0
        # Jam detection: the belt has been running since ``_belt_running_since``
        # and the last new piece appeared in C3 at ``_last_arrival_at``.
        self._belt_running_since: float | None = None
        self._last_arrival_at: float = 0.0
        self._last_c3_pieces: int = 0
        # Live introspection for the tuning page / debugging: one dict, updated
        # in place every tick and reachable via gc (read by the tuning router).
        self._status: dict = {"reason": "idle", "ts": 0.0}
        self._last_blocked_reason: str | None = None
        gc.belt_feeder_status = self._status

    def _cfg(self):
        # The C1/C2 rotors don't exist in the belt topology; the inherited C3
        # exit metering (and its tuning page) is used unchanged.
        cfg = super()._cfg()
        cfg.enable_ch1 = False
        cfg.enable_ch2 = False
        return cfg

    def _belt_cfg(self) -> BeltFeederConfig:
        now = time.monotonic()
        if now - self._belt_config_loaded_at >= _CONFIG_TTL_S:
            try:
                from toml_config import getBeltFeederConfig
                from .config import configFromDict
                self._belt_config = configFromDict(getBeltFeederConfig())
            except Exception as exc:
                self.gc.logger.warning(f"BeltFeeding: config load failed: {exc}")
            self._belt_config_loaded_at = now
        return self._belt_config

    def step(self) -> Optional[FeederState]:
        next_state = super().step()
        self._step_belt()
        return next_state

    def _step_belt(self) -> None:
        stepper: "StepperMotor | None" = getattr(self.irl, "belt_stepper", None)
        if stepper is None:
            self._publish_status(None, 0, None, "no_belt_stepper")
            return
        cfg = self._belt_cfg()
        now = time.monotonic()

        c3_pieces = self._c3_piece_count()
        if c3_pieces is None:
            # Perception not up yet — never run the belt blind.
            self._command_belt_speed(stepper, 0, cfg, now)
            self._publish_status(cfg, 0, None, "no_perception")
            return

        if c3_pieces > self._last_c3_pieces:
            self._last_arrival_at = now
        self._last_c3_pieces = c3_pieces

        target = self._target_speed(cfg, c3_pieces)
        self._command_belt_speed(stepper, target, cfg, now)
        self._check_jam(cfg, now)

        if not cfg.enable_belt:
            reason = "disabled"
        elif target == 0:
            reason = "stopped_c3_full"
        elif target < abs(cfg.belt_speed_usteps_per_s):
            reason = "throttled"
        else:
            reason = "running"
        self._publish_status(cfg, target, c3_pieces, reason)

    def _publish_status(
        self,
        cfg: BeltFeederConfig | None,
        target: int,
        c3_pieces: int | None,
        reason: str,
    ) -> None:
        now = time.monotonic()
        quiet_since = max(self._belt_running_since or 0.0, self._last_arrival_at)
        self._status.update(
            {
                "ts": time.time(),
                "reason": reason,
                "commanded_speed_usteps_per_s": self._belt_cmd_speed,
                "target_speed_usteps_per_s": target,
                "base_speed_usteps_per_s": cfg.belt_speed_usteps_per_s if cfg else None,
                "c3_pieces": c3_pieces,
                "c3_full_speed_pieces": cfg.c3_full_speed_pieces if cfg else None,
                "c3_stop_pieces": cfg.c3_stop_pieces if cfg else None,
                "running_for_s": (
                    round(now - self._belt_running_since, 1)
                    if self._belt_running_since is not None
                    else None
                ),
                "since_last_arrival_s": (
                    round(now - self._last_arrival_at, 1) if self._last_arrival_at else None
                ),
                "jam_timeout_s": cfg.jam_timeout_s if cfg else None,
                "jam_countdown_s": (
                    round(max(0.0, cfg.jam_timeout_s - (now - quiet_since)), 1)
                    if cfg and cfg.jam_timeout_s > 0 and self._belt_running_since is not None
                    else None
                ),
            }
        )
        # Count blocked reasons on the change edge only (not per tick).
        if reason in ("running", "throttled"):
            self._last_blocked_reason = None
        elif reason != self._last_blocked_reason:
            self._last_blocked_reason = reason
            runtime_stats = getattr(self.gc, "runtime_stats", None)
            if runtime_stats is not None and hasattr(runtime_stats, "observeBlockedReason"):
                runtime_stats.observeBlockedReason("belt", reason)

    def _c3_piece_count(self) -> int | None:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return None
        from perception.state import EMPTY_STATE, EMPTY_STATE_TS

        c3 = perception_service.read_states().get(3, EMPTY_STATE)
        if c3.ts == EMPTY_STATE_TS:
            return None
        return c3.n_pieces

    def _target_speed(self, cfg: BeltFeederConfig, c3_pieces: int) -> int:
        if not cfg.enable_belt:
            return 0
        full = max(0, cfg.c3_full_speed_pieces)
        stop = max(full + 1, cfg.c3_stop_pieces)
        if c3_pieces <= full:
            fraction = 1.0
        elif c3_pieces >= stop:
            fraction = 0.0
        else:
            fraction = (stop - c3_pieces) / (stop - full)
        return int(round(abs(cfg.belt_speed_usteps_per_s) * fraction))

    def _command_belt_speed(
        self,
        stepper: "StepperMotor",
        target: int,
        cfg: BeltFeederConfig,
        now: float,
    ) -> None:
        sign = 1 if cfg.forward_direction_sign >= 0 else -1
        signed_target = sign * target
        if signed_target == self._belt_cmd_speed:
            return
        # An emergency stop may always go out immediately; speed-ups and
        # ramp-downs respect the update interval.
        if target != 0 and now < self._belt_next_cmd_at:
            return
        if target > self._belt_speed_limit:
            try:
                stepper.set_speed_limits(0, target)
                self._belt_speed_limit = target
            except Exception as exc:
                self.gc.logger.warning(f"BeltFeeding: speed limit set failed: {exc}")
        success = stepper.move_at_speed(signed_target)
        if not success:
            self.gc.logger.warning(
                f"BeltFeeding: move_at_speed({signed_target}) not acknowledged"
            )
            return
        was_stopped = self._belt_cmd_speed == 0
        self._belt_cmd_speed = signed_target
        self._belt_next_cmd_at = now + max(0, cfg.speed_update_interval_ms) / 1000.0
        if target == 0:
            self._belt_running_since = None
        elif was_stopped:
            self._belt_running_since = now

    def _check_jam(self, cfg: BeltFeederConfig, now: float) -> None:
        if cfg.jam_timeout_s <= 0 or self._belt_running_since is None:
            return
        quiet_since = max(self._belt_running_since, self._last_arrival_at)
        quiet_s = now - quiet_since
        if quiet_s < cfg.jam_timeout_s:
            return
        from subsystems.channels.base import publish_belt_feeder_stalled_incident

        publish_belt_feeder_stalled_incident(
            self.gc,
            stalled_ms=int(quiet_s * 1000),
            belt_speed_usteps_per_s=abs(self._belt_cmd_speed),
            jam_timeout_s=cfg.jam_timeout_s,
        )
        # Re-arm so the incident (or a false alarm on an empty boat) doesn't
        # re-fire every tick.
        self._last_arrival_at = now

    def cleanup(self) -> None:
        # Leaving FEEDING (pause/stop/incident) must always stop the belt.
        stepper: "StepperMotor | None" = getattr(self.irl, "belt_stepper", None)
        if stepper is not None and self._belt_cmd_speed != 0:
            try:
                stepper.move_at_speed(0)
            except Exception as exc:
                self.gc.logger.warning(f"BeltFeeding: cleanup belt stop failed: {exc}")
            self._belt_cmd_speed = 0
            self._belt_running_since = None
        self._status.update({"ts": time.time(), "reason": "idle"})
        super().cleanup()
