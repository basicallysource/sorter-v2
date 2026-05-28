"""Per-channel closed-loop eject + fall-recovery controller.

The alternative to precise-pulse hand-off. When a channel runs in fast-eject
mode (C3 by default), this state machine replaces the metered ``PRECISE``
pulsing at the exit:

  IDLE → ADVANCING → AWAITING_FALL → (RECOVERING) → IDLE

- IDLE: the leading piece's COM is within the trigger distance of the REAL exit
  (fall-off) region AND the downstream channel is ready → snapshot the
  downstream piece count, → ADVANCING. (The trigger is measured against the
  exit-only zone, NOT the precise zone — a piece sitting in the precise zone
  must never start an eject.)
- ADVANCING (slippage-robust core): each iteration re-reads the ACTUAL COM gap
  to the exit-zone entry edge and commands a normal move of that remaining gap
  (floored at ``fast_eject_min_step_deg``, never touching acceleration). The
  piece may slip and move fewer degrees than commanded — that's fine, we just
  re-measure and command the new remaining gap next iteration. When the gap
  reaches ``<= 0`` the piece is >= 50% into the exit (COM = centroid past the
  edge) → AWAITING_FALL. A safety cap (``fast_eject_max_advance_iterations``)
  kicks a hopelessly stuck/slipping piece to RECOVERING.
- AWAITING_FALL: success ONLY when a NEW detection appears in the DOWNSTREAM
  channel's region (its ``n_pieces`` rose above the snapshot — the piece fell
  and arrived). The piece vanishing from THIS channel's over-exposed exit view
  is NOT success — we keep assuming it's there. After ``fall_confirm_timeout_ms``
  with no downstream rise → RECOVERING.
- RECOVERING: jitter-and-pause up to N attempts (shared ``JitterSequence``). A
  downstream rise → success. If the piece reappears out of the exit zone
  (``gap > 0``) → back to ADVANCING to re-approach. Exhausted with nothing ever
  downstream → assume the detection was a vision glitch, give up, resume normal
  flow.

The controller is driven one ``tick`` per coordinator loop and returns whether
it consumed the channel this tick (True ⇒ caller skips normal advance/idle). It
issues moves through callbacks owned by the feeder flow and owns only the jitter
command directly.

Nothing here runs inference or touches VisionManager — it reads the scalars the
perception workers already published. Keep it that way (see the perception perf
rules).
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Optional, TYPE_CHECKING

from subsystems.common.jitter_recovery import JitterParams, JitterPhase, JitterSequence

if TYPE_CHECKING:
    from perception.state import ChannelState
    from .config import GoToAngleConfig


class EjectPhase(str, Enum):
    IDLE = "idle"
    ADVANCING = "advancing"
    AWAITING_FALL = "awaiting_fall"
    RECOVERING = "recovering"


class EjectController:
    def __init__(
        self,
        *,
        channel_id: int,
        stepper,
        is_stopped: Callable[[], bool],
        advance_move: Callable[[float], bool],
        on_success: Callable[[], None],
        logger,
    ) -> None:
        self.channel_id = channel_id
        self._stepper = stepper
        self._is_stopped = is_stopped
        self._advance_move = advance_move
        self._on_success = on_success
        self._logger = logger

        self._phase: EjectPhase = EjectPhase.IDLE
        self._awaiting_since: float = 0.0
        self._downstream_baseline: int = 0
        self._advance_iters: int = 0
        self._seq: Optional[JitterSequence] = None

    @property
    def phase(self) -> EjectPhase:
        return self._phase

    def reset(self) -> None:
        self._phase = EjectPhase.IDLE
        self._awaiting_since = 0.0
        self._downstream_baseline = 0
        self._advance_iters = 0
        if self._seq is not None:
            self._seq.reset()

    def _downstream_new(self, downstream: "ChannelState") -> bool:
        return int(downstream.n_pieces) > self._downstream_baseline

    def _succeed(self, reason: str) -> bool:
        self._logger.info(
            f"[eject ch{self.channel_id}] success ({reason}) — resuming normal flow"
        )
        try:
            self._on_success()
        except Exception:
            pass
        self.reset()
        return True

    def tick(
        self,
        *,
        state: "ChannelState",
        downstream: "ChannelState",
        downstream_ready: bool,
        cfg: "GoToAngleConfig",
        now: float,
    ) -> bool:
        """Returns True when the controller has taken charge of this channel for
        the tick (caller must NOT also run normal advance/idle)."""
        if self._phase == EjectPhase.IDLE:
            return self._tick_idle(state, downstream, downstream_ready, cfg, now)
        if self._phase == EjectPhase.ADVANCING:
            return self._tick_advancing(state, downstream_ready, cfg, now)
        if self._phase == EjectPhase.AWAITING_FALL:
            return self._tick_awaiting(downstream, cfg, now)
        if self._phase == EjectPhase.RECOVERING:
            return self._tick_recovering(state, downstream, now)
        return False

    # --- phases ---------------------------------------------------------

    def _tick_idle(
        self,
        state: "ChannelState",
        downstream: "ChannelState",
        downstream_ready: bool,
        cfg: "GoToAngleConfig",
        now: float,
    ) -> bool:
        gap = state.exit_com_forward_deg
        if state.n_pieces <= 0 or gap is None:
            return False  # nothing on this channel — let normal flow run
        # The eject starts ONLY when the leading piece's COM is in the precise
        # (staging) zone, or it is already in the exit (gap <= 0). A piece short
        # of the precise zone is carried in by the normal advance — we do not
        # jump toward the exit while it is still outside that region.
        if not (bool(state.exit_com_in_precise) or gap <= 0.0):
            return False
        # A piece is staged at the exit. From here this is our channel.
        if not downstream_ready:
            return True  # hold (freeze) until the downstream channel can accept
        # Commit: snapshot what downstream looks like now so a later rise = our drop.
        self._downstream_baseline = int(downstream.n_pieces)
        self._advance_iters = 0
        self._phase = EjectPhase.ADVANCING
        self._logger.info(
            f"[eject ch{self.channel_id}] start ADVANCING (gap={gap:.1f}° "
            f"in_precise={bool(state.exit_com_in_precise)} downstream_baseline="
            f"{self._downstream_baseline})"
        )
        # Act this tick rather than burning one.
        return self._tick_advancing(state, downstream_ready, cfg, now)

    def _tick_advancing(
        self,
        state: "ChannelState",
        downstream_ready: bool,
        cfg: "GoToAngleConfig",
        now: float,
    ) -> bool:
        gap = state.exit_com_forward_deg
        if state.n_pieces <= 0 or gap is None:
            # Piece left this channel mid-approach. It may have fallen — let
            # AWAITING_FALL confirm via downstream (and time out → jitter → glitch
            # give-up if not). Local disappearance alone is never success.
            self._phase = EjectPhase.AWAITING_FALL
            self._awaiting_since = now
            self._logger.info(
                f"[eject ch{self.channel_id}] piece left channel mid-advance — "
                f"awaiting downstream confirmation"
            )
            return True
        if gap <= 0.0:
            # COM crossed the exit-zone entry edge → piece is >= 50% in. Stop
            # advancing and wait for it to fall.
            self._phase = EjectPhase.AWAITING_FALL
            self._awaiting_since = now
            self._logger.info(
                f"[eject ch{self.channel_id}] reached exit zone (gap={gap:.1f}° "
                f"≥50% in) — awaiting fall"
            )
            return True
        if not downstream_ready:
            return True  # freeze mid-approach; downstream can't accept right now
        if not self._is_stopped():
            return True  # previous advance move still running

        self._advance_iters += 1
        if self._advance_iters > int(cfg.fast_eject_max_advance_iterations):
            self._logger.warning(
                f"[eject ch{self.channel_id}] {self._advance_iters - 1} advance "
                f"moves without reaching the exit zone (gap still {gap:.1f}°) — "
                f"piece stuck/slipping, kicking to jitter recovery"
            )
            self._begin_recovery(cfg, reason="advance stalled")
            return True

        step = max(float(cfg.fast_eject_min_step_deg), float(gap))
        ok = self._advance_move(step)
        self._logger.info(
            f"[eject ch{self.channel_id}] ADVANCE gap={gap:.1f}° step={step:.1f}° "
            f"iter={self._advance_iters} ok={ok}"
        )
        return True

    def _tick_awaiting(
        self,
        downstream: "ChannelState",
        cfg: "GoToAngleConfig",
        now: float,
    ) -> bool:
        if self._downstream_new(downstream):
            return self._succeed("appeared downstream")
        # Give the piece the full window to fall and register downstream. Only the
        # downstream rise counts — the piece sitting in our over-exposed exit view
        # is the expected state, not a stuck signal.
        elapsed_ms = (now - self._awaiting_since) * 1000.0
        if elapsed_ms >= float(cfg.fall_confirm_timeout_ms):
            self._begin_recovery(cfg, reason=f"no downstream within {int(cfg.fall_confirm_timeout_ms)}ms")
        return True

    def _begin_recovery(self, cfg: "GoToAngleConfig", reason: str) -> None:
        seq = self._get_seq(cfg)
        if seq is None:
            self._logger.warning(
                f"[eject ch{self.channel_id}] no stepper for jitter recovery — "
                f"giving up, resuming normal flow"
            )
            self.reset()
            return
        self._logger.info(
            f"[eject ch{self.channel_id}] {reason} — starting jitter recovery "
            f"(up to {cfg.fall_recovery_max_jitter_attempts})"
        )
        self._phase = EjectPhase.RECOVERING
        seq.start()

    def _tick_recovering(
        self,
        state: "ChannelState",
        downstream: "ChannelState",
        now: float,
    ) -> bool:
        if self._downstream_new(downstream):
            return self._succeed("appeared downstream during recovery")
        # If the jitter knocked the piece back out of the exit zone, re-approach.
        gap = state.exit_com_forward_deg
        if state.n_pieces > 0 and gap is not None and gap > 0.0:
            self._logger.info(
                f"[eject ch{self.channel_id}] piece back out of exit (gap={gap:.1f}°) "
                f"after jitter — re-approaching"
            )
            self._advance_iters = 0
            self._phase = EjectPhase.ADVANCING
            if self._seq is not None:
                self._seq.reset()
            return True
        seq = self._seq
        if seq is None:
            self.reset()
            return False
        phase = seq.tick(still_stuck=True, now=now)
        if phase == JitterPhase.EXHAUSTED:
            self._logger.warning(
                f"[eject ch{self.channel_id}] piece never registered downstream "
                f"after jitter recovery — assuming vision glitch, resuming normal flow"
            )
            self.reset()
            return False
        return True

    def _get_seq(self, cfg: "GoToAngleConfig") -> Optional[JitterSequence]:
        if self._seq is not None:
            return self._seq
        if self._stepper is None:
            return None
        self._seq = JitterSequence(
            self._stepper,
            JitterParams(
                amplitude_motor_deg=cfg.jitter_amplitude_motor_deg,
                cycles=int(cfg.jitter_cycles),
                speed_usteps_per_s=int(cfg.jitter_speed_usteps_per_s),
                accel_usteps_per_s2=int(cfg.jitter_accel_usteps_per_s2),
                pause_ms=int(cfg.jitter_pause_ms),
                max_attempts=int(cfg.fall_recovery_max_jitter_attempts),
            ),
            label=f"[eject ch{self.channel_id}]",
            logger=self._logger,
        )
        return self._seq
