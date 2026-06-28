import time
from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.common.jitter_recovery import JitterParams, JitterPhase, JitterSequence

from .base import Rev01BaseState
from .constants import C4_TRAVEL_SIGN, LOG_TAG


class Discharging(Rev01BaseState):
    """Closed-loop discharge (active perception path).

    The carousel drives the piece's center-of-mass to the centre of the fall-off
    zone so it can drop. Completion is ONE signal: the channel reads physically
    clear (``n_pieces == 0``, or our piece reached the exit and left it) for a
    short continuous window.

    Jitter has exactly ONE trigger: a piece sitting in the FALL-OFF region (the
    exit-only sub-arc — ``in_exit_majority`` — NOT the precise staging band) for
    longer than ``discharge_jitter_dwell_ms``. A piece that drops on its own is
    only in the fall-off for a frame or two, so it never arms the jitter; only a
    piece that parks there and won't fall does. There is no gap/no-progress stall
    heuristic — that fired the jitter on pieces that had already dropped.

    Giving up (the total-budget backstop, or jitter exhausted) does NOT raise an
    operator incident: it settles for ``discharge_giveup_settle_ms`` then credits
    the piece and returns to IDLE — the same as an operator clicking
    Resolve-without-removing on the old stuck dialog.

    The piece is committed to distribution (``_releaseOnce``) on confirmed clear
    or on the give-up settle. The loop repeats until every piece is off, so a
    multi-feed clears both. On the non-perception fallback path there is no
    per-piece signal, so it degrades to a single fixed kick-off move.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._discharge_started_at: Optional[float] = None
        self._released = False
        self._gave_up = False
        self._gave_up_at: Optional[float] = None
        self._clear_since: Optional[float] = None
        self._in_falloff_since: Optional[float] = None
        self._reached_exit = False
        self._seq: Optional[JitterSequence] = None
        # legacy fallback only
        self._kick_started = False
        self._kick_done_at: Optional[float] = None

    def step(self) -> Optional[ClassificationChannelState]:
        self.setClassificationReady(False, "discharging")
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return self._step_legacy_fallback()
        return self._step_perception(perception_service)

    # ---- active perception path ----

    def _step_perception(self, perception_service) -> Optional[ClassificationChannelState]:
        now = time.monotonic()
        cfg = self.ctx.config
        if self._discharge_started_at is None:
            self._discharge_started_at = now

        state = perception_service.read_state(4)
        n = int(state.n_pieces)

        if self.ctx.observeMultiFeed(n, float(state.ts), cfg.multi_feed_confirm_reads):
            self.logger.info(
                f"{LOG_TAG} DISCHARGING: multi-feed confirmed "
                f"({n} pieces over {cfg.multi_feed_confirm_reads} frames)"
            )

        in_exit = bool(state.in_exit)
        if in_exit:
            self._reached_exit = True

        # The ONLY thing that arms the jitter: the piece is in the FALL-OFF part
        # of the exit zone (the exit-only sub-arc, NOT the precise staging band).
        # ``in_exit_majority`` is exactly "majority in the fall-off region, not
        # precise". Track how long it has held continuously.
        in_falloff = bool(state.in_exit_majority)
        if in_falloff:
            if self._in_falloff_since is None:
                self._in_falloff_since = now
        else:
            self._in_falloff_since = None

        stepper = getattr(self.irl, "carousel_stepper", None)
        moving = stepper is not None and not bool(stepper.stopped)

        # Completion: channel fully clear (n==0) OR our piece reached the exit
        # and has since left it (in_exit True->False), even if a newcomer sits at
        # the entry. Require it to hold continuously so a one-frame detector blink
        # can't false-finish.
        exit_gone = self._reached_exit and not in_exit
        clear_now = (n == 0) or exit_gone
        if clear_now:
            if self._clear_since is None:
                self._clear_since = now
        else:
            self._clear_since = None

        # SUCCESS — clear held long enough; commit the piece. This is the ONLY
        # commit point, never on a timeout.
        clear_ms = 0.0 if self._clear_since is None else (now - self._clear_since) * 1000.0
        if self._clear_since is not None and clear_ms >= float(cfg.discharge_clear_confirm_ms):
            self._releaseOnce()
            reason = "channel empty" if n == 0 else f"piece left exit (n={n} at entry)"
            self.logger.info(
                f"{LOG_TAG} DISCHARGING -> IDLE ({reason}, clear for {clear_ms:.0f}ms)"
            )
            return ClassificationChannelState.IDLE

        # Gave up (total-budget backstop or jitter exhausted): settle, credit the
        # piece, return to IDLE — no operator incident.
        if self._gave_up:
            settle_s = float(cfg.discharge_giveup_settle_ms) / 1000.0
            settled = self._gave_up_at is not None and (now - self._gave_up_at) >= settle_s
            if settled:
                self._releaseOnce()
                self.logger.info(
                    f"{LOG_TAG} DISCHARGING: gave up after {settle_s * 1000.0:.0f}ms "
                    f"settle — crediting piece and returning to IDLE"
                )
                return ClassificationChannelState.IDLE
            return None

        # Let an in-flight jitter run to resolution first.
        seq = self._seq
        if seq is not None and seq.is_active:
            phase = seq.tick(still_stuck=(not clear_now), now=now)
            if phase == JitterPhase.CLEARED:
                self.logger.info(f"{LOG_TAG} DISCHARGING: jitter cleared the piece")
                self._in_falloff_since = None
                return None
            if phase == JitterPhase.EXHAUSTED:
                self._giveUp(now)
                return None
            return None  # JITTERING / PAUSE — let it finish

        # A discrete converge move must finish before we re-read and re-issue.
        if moving:
            return None

        # Hard total budget — the only "stuck anywhere on the channel" backstop.
        total_ms = (now - self._discharge_started_at) * 1000.0
        if total_ms >= float(cfg.discharge_total_timeout_ms):
            self.logger.error(
                f"{LOG_TAG} DISCHARGING: total budget {cfg.discharge_total_timeout_ms}ms "
                f"spent, channel still occupied (n={n}) — giving up"
            )
            self._giveUp(now)
            return None

        # JITTER — the one and only trigger: a piece parked in the fall-off
        # region for longer than the dwell. Pieces that drop on their own pass
        # through too fast to ever reach it.
        falloff_ms = (
            0.0 if self._in_falloff_since is None else (now - self._in_falloff_since) * 1000.0
        )
        if self._in_falloff_since is not None and falloff_ms >= float(
            cfg.discharge_jitter_dwell_ms
        ):
            self._startJitter(cfg, now, falloff_ms)
            return None

        # Closed-loop converge: drive the COM toward the fall-off centre so the
        # piece is delivered to where it can drop. With no center signal but a
        # piece present, nudge forward by a default step.
        real_gap = state.exit_com_forward_to_center_deg
        if real_gap is None:
            real_gap = state.exit_com_forward_deg
        move_gap = (
            real_gap
            if real_gap is not None
            else min(float(cfg.discharge_max_move_output_deg), 30.0)
        )
        if abs(move_gap) <= float(cfg.discharge_center_tolerance_deg):
            # Delivered to the fall-off centre — wait. If it drops, clear-confirm
            # ends the cycle; if it parks here, the fall-off dwell arms the jitter.
            return None
        move = min(max(0.0, move_gap), float(cfg.discharge_max_move_output_deg))
        if move <= 0.0:
            return None
        # Reverse: perception returns the gap as a positive advance-toward-the-
        # fall-off magnitude; the physical move is negative output degrees.
        self.startOutputMove(C4_TRAVEL_SIGN * move, cfg.discharge_speed_usteps_per_s)
        return None

    def _startJitter(self, cfg, now: float, falloff_ms: float) -> None:
        seq = self._getOrBuildSeq(cfg)
        if seq is None:
            self.logger.warning(
                f"{LOG_TAG} DISCHARGING: jitter unavailable — giving up (settle then auto-credit)"
            )
            self._giveUp(now)
            return
        if not seq.is_active:
            self.logger.info(
                f"{LOG_TAG} DISCHARGING: piece stuck in fall-off region for "
                f"{falloff_ms:.0f}ms — jitter unstick"
            )
            seq.start()

    def _giveUp(self, now: float) -> None:
        total_ms = 0.0
        if self._discharge_started_at is not None:
            total_ms = (now - self._discharge_started_at) * 1000.0
        attempts = self._seq.attempts_made if self._seq is not None else 0
        self.logger.warning(
            f"{LOG_TAG} DISCHARGING: could not confirm channel clear after "
            f"{attempts} jitter attempt(s) / {total_ms:.0f}ms — almost certainly "
            f"the piece already dropped and a newcomer is holding n>0; settling "
            f"then auto-crediting (no operator incident)"
        )
        self._gave_up = True
        self._gave_up_at = now
        self.stopStepper()

    def _releaseOnce(self) -> None:
        if self._released:
            return
        obj = self.ctx.known_object
        # advanceTransport (non-dynamic) shifts wait -> exit so the piece
        # distribution positioned now occupies the drop slot it reads from.
        # Distribution watches that slot transition itself (Ready -> Sending) to
        # know the piece was flung. Classification does NOT touch
        # ``distribution_ready`` — distribution is the sole owner of that gate.
        # The old cross-subsystem False edge here could be lost in a race and
        # wedge distribution in READY forever; the durable slot signal can't be.
        self.transport.advanceTransport()
        self._released = True
        if obj is not None:
            self.logger.info(
                f"{LOG_TAG} DISCHARGING: released piece {obj.uuid[:8]} to distribution"
            )

    def _getOrBuildSeq(self, cfg) -> Optional[JitterSequence]:
        if self._seq is not None:
            return self._seq
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None:
            return None
        self._seq = JitterSequence(
            stepper,
            JitterParams(
                amplitude_motor_deg=cfg.jitter_amplitude_motor_deg,
                cycles=int(cfg.jitter_cycles),
                speed_usteps_per_s=int(cfg.jitter_speed_usteps_per_s),
                accel_usteps_per_s2=int(cfg.jitter_accel_usteps_per_s2),
                pause_ms=int(cfg.jitter_pause_ms),
                max_attempts=int(cfg.verify_discharge_max_jitter_attempts),
            ),
            label=f"{LOG_TAG} discharge",
            logger=self.logger,
        )
        return self._seq

    # ---- legacy (non-perception) fallback ----

    def _step_legacy_fallback(self) -> Optional[ClassificationChannelState]:
        cfg = self.ctx.config
        if not self._kick_started:
            self.ctx.discharging_started_at = time.monotonic()
            output_deg = C4_TRAVEL_SIGN * float(cfg.kick_off_output_deg)
            if not self.startOutputMove(output_deg, cfg.discharge_speed_usteps_per_s):
                self.logger.error(f"{LOG_TAG} could not start discharge move — abort to IDLE")
                return ClassificationChannelState.IDLE
            self._kick_started = True
            self.logger.info(
                f"{LOG_TAG} DISCHARGING (legacy) fixed kick (output={output_deg:.1f}°)"
            )

        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is not None and not bool(stepper.stopped):
            return None

        if self._kick_done_at is None:
            self._kick_done_at = time.monotonic()
            self._releaseOnce()

        if time.monotonic() - self._kick_done_at < cfg.post_discharge_pause_ms / 1000.0:
            return None
        return ClassificationChannelState.IDLE

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        if self._seq is not None:
            self._seq.reset()
        self._discharge_started_at = None
        self._released = False
        self._gave_up = False
        self._gave_up_at = None
        self._clear_since = None
        self._in_falloff_since = None
        self._reached_exit = False
        self._kick_started = False
        self._kick_done_at = None
