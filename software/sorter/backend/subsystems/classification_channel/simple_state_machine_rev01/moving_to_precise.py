import time
from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import C4_TRAVEL_SIGN, LOG_TAG


class MovingToPrecise(Rev01BaseState):
    """Reverse closed-loop converge the piece to the PRECISE staging zone.

    Drives the leading piece's COM toward the centre of the precise arc with
    repeated bounded moves (issued REVERSE — negative output degrees — via
    ``C4_TRAVEL_SIGN``). The Brickognize request spawned at the end of CAPTURING
    runs concurrently; we do not block on it here. When the COM is parked in the
    precise band we hand off to AWAITING_DISTRIBUTION, which collects the result
    and waits for the chute. The piece is held short of the fall-off so it cannot
    drop before its bin is known.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._started_at = 0.0
        self._last_gap_seen_at = 0.0

    def step(self) -> Optional[ClassificationChannelState]:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return self._step_legacy()

        now = time.monotonic()
        self.setClassificationReady(False, "moving_to_precise")
        if self._started_at == 0.0:
            self._started_at = now

        cfg = self.ctx.config
        state = perception_service.read_state(4)
        stepper = getattr(self.irl, "carousel_stepper", None)
        moving = stepper is not None and not bool(stepper.stopped)

        if now - self._started_at > cfg.rotate_timeout_s:
            self.logger.error(
                f"{LOG_TAG} MOVING_TO_PRECISE timeout after {cfg.rotate_timeout_s}s "
                f"(in_precise={state.exit_com_in_precise}, "
                f"gap={state.exit_com_forward_to_precise_deg}) — proceeding to AWAITING"
            )
            self.stopStepper()
            return ClassificationChannelState.REV01_AWAITING_DISTRIBUTION

        gap = state.exit_com_forward_to_precise_deg
        within_tol = gap is not None and abs(gap) <= float(cfg.precise_center_tolerance_deg)
        arrived = bool(state.exit_com_in_precise) or within_tol

        if arrived and not moving:
            self.logger.info(
                f"{LOG_TAG} MOVING_TO_PRECISE -> AWAITING_DISTRIBUTION "
                f"(parked in precise; gap={gap}, in_precise={state.exit_com_in_precise})"
            )
            return ClassificationChannelState.REV01_AWAITING_DISTRIBUTION

        # A discrete converge move must finish before we re-read and re-issue.
        if moving:
            return None

        if gap is None:
            # No precise reading this frame. The reverse path crosses arcs the
            # C4 polygon cannot observe (discharge cut-out), so a piece mid-way
            # is EXPECTED to vanish for a stretch. Give detection a short grace,
            # then dead-reckon: keep issuing small reverse moves until the piece
            # re-emerges into a visible zone and the closed loop takes over.
            grace_s = float(cfg.precise_blind_grace_ms) / 1000.0
            blind_since = max(self._last_gap_seen_at, self._started_at)
            if grace_s > 0 and now - blind_since >= grace_s:
                nudge = abs(float(cfg.precise_blind_nudge_output_deg))
                if nudge > 0:
                    self.logger.info(
                        f"{LOG_TAG} MOVING_TO_PRECISE blind nudge {nudge:.1f}° "
                        f"(no detection for {(now - blind_since):.1f}s)"
                    )
                    self.startOutputMove(
                        C4_TRAVEL_SIGN * nudge, cfg.precise_converge_speed_usteps_per_s
                    )
            return None
        self._last_gap_seen_at = now

        # Sign carries direction: a negative gap (overshot the precise centre
        # toward the exit) flips C4_TRAVEL_SIGN so the carousel backs up.
        move = max(-float(cfg.discharge_max_move_output_deg),
                   min(gap, float(cfg.discharge_max_move_output_deg)))
        if abs(move) < float(cfg.precise_center_tolerance_deg):
            return None
        self.startOutputMove(C4_TRAVEL_SIGN * move, cfg.precise_converge_speed_usteps_per_s)
        return None

    # ---- legacy (non-perception) fallback: single fixed reverse move ----

    def _step_legacy(self) -> Optional[ClassificationChannelState]:
        cfg = self.ctx.config
        if self._started_at == 0.0:
            self._started_at = time.monotonic()
            self.startOutputMove(
                C4_TRAVEL_SIGN * float(cfg.capture_sweep_output_deg),
                cfg.precise_converge_speed_usteps_per_s,
            )
            self.logger.info(f"{LOG_TAG} MOVING_TO_PRECISE (legacy) fixed reverse move")
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is not None and not bool(stepper.stopped):
            return None
        return ClassificationChannelState.REV01_AWAITING_DISTRIBUTION

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        self._started_at = 0.0
        self._last_gap_seen_at = 0.0
