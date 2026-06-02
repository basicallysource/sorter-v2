import time
from typing import Optional

from subsystems.classification_channel.incidents import (
    CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND,
    clear_classification_exit_stuck_incident,
    publish_classification_exit_stuck_incident,
)
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.common.jitter_recovery import JitterParams, JitterPhase, JitterSequence

from .base import Rev01BaseState
from .constants import LOG_TAG


class Discharging(Rev01BaseState):
    """Closed-loop discharge (active perception path).

    Success is defined by ONE signal: the channel reading physically clear
    (``n_pieces == 0`` for a confirmed streak). Everything else — the COM gap,
    ``in_exit`` — is only guidance for how to move, never proof the piece left.

    Each tick we drive the leading piece's center-of-mass toward the CENTER of
    the fall-off zone with bounded forward moves, re-reading perception after
    each. While the gap keeps shrinking we keep converging. If forward progress
    stalls (no improvement for ``discharge_stall_ms`` — whether the piece is
    parked at the exit and won't drop, OR jammed somewhere earlier on the
    channel) we fire a jitter burst to unstick it. A single overall budget
    (``discharge_total_timeout_ms``, NOT reset per move) and jitter exhaustion
    are the only escapes other than success: either raises a stuck incident and
    holds the channel gate not-ready until perception sees it physically clear,
    then auto-resumes.

    The piece is committed to distribution (``_releaseOnce``) ONLY on confirmed
    clear, so a piece that never actually leaves is never mis-recorded as
    dropped. On operator clear of a stuck piece the bin is credited anyway.

    The loop repeats until EVERY piece is off the channel, so a multi-feed (two
    pieces sharing one cycle) clears both — the trailing piece included.

    On the non-perception fallback path there is no per-piece COM signal, so it
    degrades to the legacy single fixed kick-off move and returns to IDLE.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._discharge_started_at: Optional[float] = None
        self._last_progress_at: Optional[float] = None
        self._best_gap: float = float("inf")
        self._released = False
        self._incident_raised = False
        self._gave_up = False
        self._clear_streak = 0
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
            self._last_progress_at = now

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

        stepper = getattr(self.irl, "carousel_stepper", None)
        moving = stepper is not None and not bool(stepper.stopped)

        # "My piece has been discharged" is NOT the same as "the channel is
        # globally empty." A new piece can arrive at the ENTRY end while we push
        # the current one off the EXIT end — multi-feed (two pieces shared the
        # cycle), or a piece already in transit when discharge began. Keying
        # completion off n==0 then never fires: n stays >=1 because of the
        # newcomer at the entry, so we keep jittering and eventually raise a
        # FALSE stuck on a piece that already dropped. So completion is either:
        #   - the channel is fully clear (n==0, the simple case / fallback), OR
        #   - our piece reached the exit/fall-off zone and has now left it
        #     (in_exit went True then False), even if something new is sitting
        #     back at the entry. That newcomer is the NEXT IDLE cycle's job.
        # The runtime detector blinks, and a moving frame is motion-unreliable,
        # so require a confirmed streak while stopped before believing it.
        exit_gone = self._reached_exit and not in_exit
        clear_now = (n == 0) or exit_gone
        if clear_now and not moving:
            self._clear_streak += 1
        elif not clear_now:
            self._clear_streak = 0

        # SUCCESS — our piece is confirmed off the channel. This is the ONLY
        # commit point: the piece is recorded to distribution here, never on a
        # timeout. The bin is credited even if an operator pulled it by hand.
        if self._clear_streak >= int(cfg.discharge_clear_confirm_reads) and not moving:
            self._releaseOnce()
            if self._incident_raised:
                clear_classification_exit_stuck_incident(self.gc)
                self._incident_raised = False
                self.logger.info(f"{LOG_TAG} DISCHARGING: channel cleared — resuming")
            reason = "channel empty" if n == 0 else f"piece left exit (n={n} at entry)"
            self.logger.info(
                f"{LOG_TAG} DISCHARGING -> IDLE ({reason}, "
                f"{self._clear_streak} confirmed reads)"
            )
            return ClassificationChannelState.IDLE

        # Gave up: an operator incident is up asking to remove the stuck part.
        # We do nothing autonomous — just hold until that incident is resolved
        # (operator removed the piece and clicked Resolve, or it was force-
        # cleared). The moment it's gone, credit the piece and hand back to IDLE,
        # which re-reads the channel from scratch and resumes the normal feed
        # flow. If no incident was actually raised (handling off), don't wedge
        # silently — fall back to IDLE so the channel keeps moving.
        if self._gave_up:
            if not self._incident_raised or not self._incidentActive():
                self._releaseOnce()
                self.logger.info(
                    f"{LOG_TAG} DISCHARGING: stuck incident resolved — returning to IDLE"
                )
                return ClassificationChannelState.IDLE
            return None

        # Let an in-flight jitter sequence run to resolution before anything else.
        # "still stuck" is the inverse of our completion test (NOT just n>0): a
        # newcomer at the entry keeps n>0 after our piece has left the exit, and
        # we must not let jitter exhaust into a false stuck on an already-dropped
        # piece.
        seq = self._seq
        if seq is not None and seq.is_active:
            phase = seq.tick(still_stuck=(not clear_now), now=now)
            if phase == JitterPhase.CLEARED:
                self.logger.info(f"{LOG_TAG} DISCHARGING: jitter cleared the piece")
                self._markProgress(now)
                return None
            if phase == JitterPhase.EXHAUSTED:
                self._raiseStuck(now)
                return None
            return None  # JITTERING / PAUSE — let it finish

        # A discrete converge move must finish before we re-read and re-issue.
        if moving:
            return None

        # Hard total budget — the real escape hatch, from ANY position on the
        # channel (not just the exit zone). One clock for the whole discharge,
        # never reset per move, so a jammed piece cannot loop forever.
        total_ms = (now - self._discharge_started_at) * 1000.0
        if total_ms >= float(cfg.discharge_total_timeout_ms):
            self.logger.error(
                f"{LOG_TAG} DISCHARGING: total budget {cfg.discharge_total_timeout_ms}ms "
                f"spent, channel still occupied (n={n}) — giving up"
            )
            self._raiseStuck(now)
            return None

        # Track forward progress on the COM-to-fall-off-centre gap. A shrinking
        # gap resets the stall clock; a flat gap (parked, or physically jammed)
        # lets it run out and triggers jitter.
        real_gap = state.exit_com_forward_to_center_deg
        if real_gap is None:
            real_gap = state.exit_com_forward_deg
        if real_gap is not None and abs(real_gap) < self._best_gap - float(
            cfg.discharge_progress_eps_deg
        ):
            self._best_gap = abs(real_gap)
            self._last_progress_at = now

        last_progress = self._last_progress_at if self._last_progress_at is not None else now
        stalled = (now - last_progress) * 1000.0 >= float(cfg.discharge_stall_ms)
        if stalled:
            self._startJitter(cfg, now)
            return None

        # Closed-loop converge: drive the COM toward the fall-off centre. With no
        # center signal but a piece present, nudge forward by a default step.
        move_gap = (
            real_gap
            if real_gap is not None
            else min(float(cfg.discharge_max_move_output_deg), 30.0)
        )
        if abs(move_gap) <= float(cfg.discharge_center_tolerance_deg):
            # At centre but not yet clear — wait; the stall timer will jitter it.
            return None
        move = min(max(0.0, move_gap), float(cfg.discharge_max_move_output_deg))
        if move <= 0.0:
            return None
        self.startOutputMove(move, cfg.discharge_speed_usteps_per_s)
        return None

    def _markProgress(self, now: float) -> None:
        # Reopen a fresh converge progress window (e.g. after jitter shifts the
        # piece) so the stall timer measures time since the LAST useful move.
        self._best_gap = float("inf")
        self._last_progress_at = now

    def _startJitter(self, cfg, now: float) -> None:
        seq = self._getOrBuildSeq(cfg)
        if seq is None:
            self.logger.warning(
                f"{LOG_TAG} DISCHARGING: jitter unavailable — raising stuck incident"
            )
            self._raiseStuck(now)
            return
        if not seq.is_active:
            self.logger.info(
                f"{LOG_TAG} DISCHARGING: no forward progress for "
                f"{cfg.discharge_stall_ms}ms — jitter unstick"
            )
            seq.start()

    def _raiseStuck(self, now: float) -> None:
        total_ms = 0.0
        if self._discharge_started_at is not None:
            total_ms = (now - self._discharge_started_at) * 1000.0
        attempts = self._seq.attempts_made if self._seq is not None else 0
        self.logger.error(
            f"{LOG_TAG} DISCHARGING: piece could not be discharged after "
            f"{attempts} jitter attempt(s) / {total_ms:.0f}ms — raising stuck "
            f"incident, holding until cleared"
        )
        published = publish_classification_exit_stuck_incident(
            self.gc,
            piece=self.ctx.known_object,
            jitter_attempts=int(attempts),
            converge_ms=float(total_ms),
        )
        self._incident_raised = bool(published)
        self._gave_up = True
        self.stopStepper()

    def _incidentActive(self) -> bool:
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
            return False
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            return False
        return (
            isinstance(active, dict)
            and active.get("kind") == CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND
        )

    def _releaseOnce(self) -> None:
        if self._released:
            return
        obj = self.ctx.known_object
        # advanceTransport (non-dynamic) shifts wait -> exit so the piece
        # distribution positioned for now occupies the drop slot it reads from.
        self.transport.advanceTransport()
        self.shared.set_distribution_gate(False, reason="rev01_discharged")
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
            output_deg = float(cfg.kick_off_output_deg)
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
        self._last_progress_at = None
        self._best_gap = float("inf")
        self._released = False
        self._incident_raised = False
        self._gave_up = False
        self._clear_streak = 0
        self._reached_exit = False
        self._kick_started = False
        self._kick_done_at = None
