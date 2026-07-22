import time
from enum import Enum
from typing import Optional

from defs.known_object import (
    ClassificationStatus,
    KnownObject,
    PieceStage,
    RecognitionImage,
)

from . import crop_quality
from .simple_state_machine_rev01.base import Rev01BaseState
from .simple_state_machine_rev01.channel_clear import (
    ChannelClearResult,
    clearChannelByAdvancing,
)
from .simple_state_machine_rev01.constants import C4_TRAVEL_SIGN
from .simple_state_machine_rev01.context import SimpleStateMachineRev01Context

LOG_TAG = "[C4-2PIECE]"

# perception.arcs._region_lookup / PieceObservation.zone_code values. The
# classification channel is a rotating platter viewed from above; pieces travel
# FORWARD (one way, never reversed) through these zones in this order:
#   DROP  -> PRECISE (the holding region) -> EXIT (the fall-off)
# Anything that has LEFT the drop zone (PRECISE, EXIT, or the unnamed gap NONE
# between them) is "forward" and part of the processing queue.
_ZONE_NONE = 0
_ZONE_DROP = 1
# (2 = exit / the fall-off, 3 = precise / the holding region; we only branch on
# DROP vs not-DROP — "left the drop zone" is what matters for the queue.)

# Identity is the source of truth (PieceObservation.sv_bt_track_id). A track id
# that has been missing from perception for longer than this is treated as gone
# (the piece left the channel). Long enough to ride out a detector blink, short
# enough to react within a cycle.
_TRACK_GONE_RETIRE_S = 0.7
# The ejecting piece is "ejected" the instant its track id stays gone this long.
# Slightly under the retire window so we commit the discharge before the bookkeep
# prune runs. This is the user's rule: "if that ID has disappeared, the piece has
# been ejected."
_EJECT_GONE_CONFIRM_S = 0.35
# A forward (already left the drop zone) piece that was NEVER captured/classified
# — a stray, a detector-churn leftover, or the trailing piece of a multi-drop
# that skipped the drop zone — is routed to misc after this long so it can be
# ejected instead of deadlocking as an un-shippable head.
_STRAY_MISC_S = 4.0
# Fixed forward nudge (output deg) used while STAGING once the leading piece has
# already reached/passed precise but the drop zone still isn't clear — keeps
# pushing the clump out of the drop zone without a gap to size against.
_STAGE_STEP_DEG = 25.0

# Safety ceilings so a move that never resolves can't wedge the machine forever.
_EJECT_TIMEOUT_S = 15.0
_STAGE_TIMEOUT_S = 15.0

# Stall-watchdog progress signal: a tracked piece's gap-to-exit must change by
# more than this (output deg) to count as the piece actually moving. Well above
# per-frame detection jitter on a stationary piece, well below any real nudge.
_PROGRESS_MOVE_DEG = 5.0


class _Phase(Enum):
    # Platter STOPPED. Observe, photograph the drop-zone piece, classify, and aim
    # the chute for the head piece. The only place we accept a new piece.
    WAITING = "waiting"
    # Rotating the head piece off the fall-off. Done when its track id is gone.
    EJECTING = "ejecting"
    # Rotating the clump forward until the drop zone is clear (the new piece, plus
    # any multi-drop siblings, have all left the drop zone).
    STAGING = "staging"


class _TrackedPiece:
    """One physical piece on the channel, keyed by its perception track id. Owns
    a private capture/classify worker (its own KnownObject + burst context) so two
    pieces never share classification state."""

    def __init__(self, track_id: int, worker: Rev01BaseState, now: float) -> None:
        self.track_id = track_id
        self.worker = worker
        self.zone = _ZONE_NONE
        self.bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
        self.gap_to_exit: Optional[float] = None
        # Gap at the last time this piece was credited with real movement (the
        # stall watchdog's "has it moved substantially" reference point).
        self.progress_gap: Optional[float] = None
        self.created_at = now
        self.last_seen = now
        # Burst capture (drop zone only) has finished -> safe to rotate the piece
        # out of the drop zone.
        self.capture_done = False
        # Classification result has been written onto the KnownObject.
        self.result_applied = False
        # Handed to distribution (chute is aiming / aimed for it).
        self.placed = False
        # Two+ pieces landed in the drop zone at once -> can't classify reliably,
        # route to the misc bin. multi_drop_group ties the clump's distinct track
        # ids together as one logical multi-drop (None when not a multi-drop).
        self.double_feed = False
        self.multi_drop_group: Optional[int] = None

    @property
    def known_object(self) -> Optional[KnownObject]:
        return self.worker.ctx.known_object


class TwoPieceClassificationChannel(Rev01BaseState):
    """Hold up to two pieces on the classification channel, one cycle ahead of
    the chute: a HEAD being classified + aimed + ejected, and a fresh piece
    captured in the drop zone. The platter only ever turns FORWARD (clockwise);
    no move is reversed.

    SOURCE OF TRUTH = perception track ids (``PieceObservation.sv_bt_track_id``):
    a piece's id leaving the drop zone confirms it staged; a piece's id
    DISAPPEARING confirms it was ejected off the fall-off.

    The channel is treated as an ORDERED QUEUE (most-forward = head), not a fixed
    "one in precise, one in drop" pair — so a multi-drop clump or a stray that
    lands between zones is always part of the queue and never stranded.

    State machine (platter-level; per-piece classification runs concurrently):

      WAITING (stopped) --------------------------------------------------+
        - photograph the drop piece (drop zone only), classify off-thread |
        - aim the chute for the head once it's classified                 |
        - feeder may add a piece only here (drop clear + stopped)         |
        - ROTATE when there is a captured drop piece AND                  |
            (no head            -> STAGING, or                            |
             head is ready      -> EJECTING)                              |
                                                                          |
      EJECTING (moving) -- push the head off the fall-off                 |
        - done when its track id is gone -> commit it to distribution     |
          -> STAGING                                                      |
                                                                          |
      STAGING (moving) -- advance until the DROP ZONE IS CLEAR (whole     |
        clump leaves drop) -> WAITING ------------------------------------+

    "Ready" for the head = classified AND the distribution chute is aimed for it.
    A multi-drop's pieces stay distinct but share a ``multi_drop_group`` id and
    all route to misc, draining one per cycle.

    The single-piece SIMPLE_STATE_MACHINE_REV01 path is untouched.
    """

    def __init__(
        self,
        irl,
        irl_config,
        gc,
        shared,
        transport,
        vision,
        event_queue,
        context: SimpleStateMachineRev01Context,
    ):
        super().__init__(
            irl, irl_config, gc, shared, transport, vision, event_queue, context
        )
        self._deps = (irl, irl_config, gc, shared, transport, vision, event_queue)
        self._pieces: dict[int, _TrackedPiece] = {}
        self._phase = _Phase.WAITING
        self._eject_target: Optional[_TrackedPiece] = None
        self._stage_target: Optional[_TrackedPiece] = None
        self._phase_started_at = 0.0
        # Stall-watchdog progress signal (read by ClassificationChannelStateMachine):
        # last time the flow demonstrably moved forward — a real piece leaving
        # the channel, substantial piece movement, or a capture/classify/place
        # milestone. Deliberately NOT credited: phase changes (timeout ping-pong),
        # new track ids appearing, churn tracks retiring, and motor moves whose
        # piece never moved — those are exactly the wedges the watchdog must catch.
        self.last_progress_at = time.monotonic()
        # Multi-feed debounce: consecutive distinct frames showing >1 drop-zone id.
        self._multi_drop_streak = 0
        self._multi_drop_last_ts = -1.0
        # Monotonic counter for multi_drop_group ids; advanced once per new clump.
        self._multi_drop_seq = 0
        self.ctx.reset()
        self.ctx.known_object = None

    # ------------------------------------------------------------- watchdog API

    def noteProgress(self) -> None:
        self.last_progress_at = time.monotonic()

    def phaseName(self) -> str:
        return self._phase.value

    def attemptStallAutoClear(self, *, max_output_deg: float) -> ChannelClearResult:
        """Forced recovery for a wedged channel: rotate forward (occupancy-checked,
        blocking) until perception sees the channel empty or the budget runs out.
        A placed head is committed to distribution first — the chute is already
        aimed for it, so the forced rotation drops it exactly where the normal
        eject would have. Everything else on the channel falls wherever the chute
        happens to point; their in-flight objects are abandoned."""
        placed = next((tp for tp in self._pieces.values() if tp.placed), None)
        if placed is not None:
            obj = placed.known_object
            if obj is not None and obj.stage == PieceStage.distributing:
                self.transport.advanceTransport()
                self.logger.info(
                    f"{LOG_TAG} stall auto-clear: committed placed head "
                    f"track={placed.track_id} to distribution"
                )
        result = clearChannelByAdvancing(
            self.gc,
            self.irl,
            self.irl_config,
            vision=self.cv._vision,
            max_output_deg=max_output_deg,
            label=LOG_TAG,
        )
        if result.cleared:
            for tp in self._pieces.values():
                try:
                    tp.worker.abandonInFlightObject(
                        "stall auto-clear forced the piece off the channel"
                    )
                except Exception:
                    pass
            self._pieces = {}
            self._eject_target = None
            self._stage_target = None
            self._multi_drop_streak = 0
            self._multi_drop_last_ts = -1.0
            self._enterPhase(_Phase.WAITING)
        return result

    # ------------------------------------------------------------------ main

    def step(self) -> None:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is None:
            return
        state = perception_service.read_state(4)
        stepper = getattr(self.irl, "carousel_stepper", None)
        stopped = bool(getattr(stepper, "stopped", True))
        now = time.monotonic()

        self._observe(state, now)

        # The classification channel OWNS the feeder admission gate. Ready only
        # when we are idle between cycles (not mid-rotation) AND the drop zone is
        # clear AND the platter has settled — i.e. "rotation complete, drop empty".
        ready = self._phase == _Phase.WAITING and (not state.in_drop) and stopped
        self.setClassificationReady(ready, "waiting + drop clear + stopped")

        # Classification results arrive on background threads — apply them every
        # tick regardless of phase.
        self._applyResults(now)

        if self._phase == _Phase.WAITING:
            if stopped:
                self._captureDropPieces(perception_service, now)
                self._aimChuteForHead(now)
                self._maybeStartRotation()
        elif self._phase == _Phase.EJECTING:
            self._ejecting(state, stopped, now)
        elif self._phase == _Phase.STAGING:
            self._staging(state, stopped, now)

    # ------------------------------------------------- perception reconciliation

    def _observe(self, state, now: float) -> None:
        """Match this frame's observations to tracked pieces by track id, create
        pieces for new ids, retire pieces whose id has been gone too long, and
        flag double feeds."""
        for po in getattr(state, "pieces", ()):
            tid = po.sv_bt_track_id
            if tid is None:
                continue  # untracked box — counts for zone occupancy, not identity
            tp = self._pieces.get(tid)
            if tp is None:
                tp = self._createPiece(tid, now)
            tp.zone = int(po.zone_code)
            b = po.bbox
            tp.bbox = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
            tp.gap_to_exit = po.com_forward_to_exit_deg
            tp.last_seen = now
            # Watchdog progress: the piece physically moved a substantial amount.
            if tp.gap_to_exit is not None:
                gap = float(tp.gap_to_exit)
                if tp.progress_gap is None:
                    tp.progress_gap = gap
                elif abs(gap - tp.progress_gap) > _PROGRESS_MOVE_DEG:
                    tp.progress_gap = gap
                    self.noteProgress()

        self._retireGonePieces(now)
        self._flagDoubleFeeds(state)

    def _createPiece(self, track_id: int, now: float) -> _TrackedPiece:
        # Track the id for position immediately, but DEFER the KnownObject: it's
        # created only when the piece is actually photographed (a real drop
        # arrival) or routed to distribution (see _ensureKnownObject). A transient
        # detection that appears mid-channel and does neither is tracked but never
        # becomes a UI 'piece' — no spam of pending objects, no false multi-drop.
        worker = Rev01BaseState(*self._deps, SimpleStateMachineRev01Context())
        worker.ctx.reset()
        worker.ctx.known_object = None
        tp = _TrackedPiece(track_id, worker, now)
        self._pieces[track_id] = tp
        return tp

    def _ensureKnownObject(self, tp: _TrackedPiece) -> None:
        if tp.worker.ctx.known_object is not None:
            return
        tp.worker.ctx.known_object = KnownObject(
            stage=PieceStage.created,
            classification_status=ClassificationStatus.pending,
            first_carousel_seen_ts=time.time(),
        )
        tp.worker.emitKnownObject()
        self.logger.info(f"{LOG_TAG} new piece track={tp.track_id}")

    def _retireGonePieces(self, now: float) -> None:
        for tid in [
            tid
            for tid, tp in self._pieces.items()
            if (now - tp.last_seen) > _TRACK_GONE_RETIRE_S
        ]:
            tp = self._pieces.pop(tid)
            # A piece already handed to distribution has a terminal status, so
            # abandonInFlightObject is a no-op for it. Only an in-flight piece
            # (photographed but never classified/distributed) is dropped from the
            # UI — e.g. a stray that fell off before it could be processed.
            tp.worker.abandonInFlightObject("track id gone (left channel)")
            # Watchdog progress: a REAL piece (one that became a UI object) left
            # the channel. Churn tracks (no KnownObject) get no credit, so id
            # flapping can't mask a wedge.
            if tp.known_object is not None:
                self.noteProgress()
            self.logger.info(f"{LOG_TAG} retired piece track={tid}")

    def _flagDoubleFeeds(self, state) -> None:
        drop = [tp for tp in self._pieces.values() if tp.zone == _ZONE_DROP]
        frame_ts = float(getattr(state, "ts", 0.0))
        if frame_ts != self._multi_drop_last_ts:
            self._multi_drop_last_ts = frame_ts
            self._multi_drop_streak = self._multi_drop_streak + 1 if len(drop) > 1 else 0
        threshold = max(1, int(self.ctx.config.multi_feed_confirm_reads))
        if self._multi_drop_streak < threshold:
            return
        # Bind this whole clump under one multi_drop_group id. Reuse an existing
        # group already present in the drop zone so a third piece joining a known
        # clump is tied to the same logical multi-drop rather than starting a new one.
        group = next(
            (tp.multi_drop_group for tp in drop if tp.multi_drop_group is not None),
            None,
        )
        if group is None:
            self._multi_drop_seq += 1
            group = self._multi_drop_seq
        for tp in drop:
            if not tp.double_feed:
                self._markDoubleFeed(tp, group)

    def _markDoubleFeed(self, tp: _TrackedPiece, group: int) -> None:
        # Two+ pieces in the drop zone at once: classification can't be trusted, so
        # skip it and route the piece to the misc bin. It still rides the normal
        # bucket-brigade (staged, then ejected) — just to misc. All members of the
        # clump share one multi_drop_group so they read as a single multi-drop.
        tp.double_feed = True
        tp.multi_drop_group = group
        tp.capture_done = True
        tp.result_applied = True
        self.noteProgress()
        self._ensureKnownObject(tp)
        obj = tp.known_object
        if obj is not None:
            obj.classification_status = ClassificationStatus.multi_drop_fail
            obj.part_id = None
            tp.worker.emitKnownObject()
        self.logger.warning(
            f"{LOG_TAG} double feed -> misc (track={tp.track_id}, group={group})"
        )

    # --------------------------------------------------- ordered-queue accessors

    def _headPiece(self) -> Optional[_TrackedPiece]:
        # The head of the queue: the most-forward piece that has LEFT the drop zone
        # (in precise, the exit approach, or the unnamed gap between drop and
        # precise). This is the piece we classify-aim and eject next. Including the
        # gap (zone NONE) is what keeps a clump piece that overshot precise, or a
        # stray that landed mid-channel, from being stranded.
        fwd = [tp for tp in self._pieces.values() if tp.zone != _ZONE_DROP]
        if not fwd:
            return None
        return min(fwd, key=lambda tp: tp.gap_to_exit if tp.gap_to_exit is not None else 1e9)

    def _dropPiece(self) -> Optional[_TrackedPiece]:
        drop = [tp for tp in self._pieces.values() if tp.zone == _ZONE_DROP]
        if not drop:
            return None
        return min(drop, key=lambda tp: tp.gap_to_exit if tp.gap_to_exit is not None else 1e9)

    # -------------------------------------------- capture / classify / aim chute

    def _captureDropPieces(self, perception_service, now: float) -> None:
        # Photograph pieces ONLY while they sit at rest in the drop zone (the
        # user's rule). Each piece is cropped from its OWN tracked bbox, so two
        # pieces never cross-contaminate each other's burst.
        raw = None
        for tp in list(self._pieces.values()):
            if tp.zone != _ZONE_DROP or tp.capture_done or tp.double_feed:
                continue
            if raw is None:
                raw = perception_service.read_bboxes_and_frame(4)
                if raw is None:
                    return
            _bboxes, perc_frame = raw
            self._ensureKnownObject(tp)  # real drop arrival -> becomes a UI piece
            ctx = tp.worker.ctx
            if ctx.capturing_started_at == 0.0:
                ctx.capturing_started_at = now
            self._cropBurstFrame(tp.worker, tp.bbox, perc_frame)
            done, reason = tp.worker.burstCaptureComplete(ctx, now)
            if done:
                tp.capture_done = True
                self.noteProgress()
                ctx.classify_started_at = now
                caps = list(ctx.captured_crops)
                if caps:
                    tp.worker.spawnClassifyThread(caps)
                else:
                    ctx.classification_error = "no_captures"
                self.logger.info(
                    f"{LOG_TAG} captured track={tp.track_id} "
                    f"({len(caps)} crops, stop={reason}); classifying"
                )

    def _applyResults(self, now: float) -> None:
        for tp in self._pieces.values():
            if tp.result_applied or tp.double_feed:
                continue
            ctx = tp.worker.ctx
            if ctx.classify_started_at == 0.0:
                continue
            with ctx.classify_lock:
                result = ctx.classification_result
                error = ctx.classification_error
            if result is not None or error is not None:
                tp.worker.updateKnownObjectWithResult(result, error)
                tp.result_applied = True
                self.noteProgress()
            elif (now - ctx.classify_started_at) > ctx.config.classify_timeout_s:
                self.logger.error(f"{LOG_TAG} classify timeout track={tp.track_id} -> unknown")
                tp.worker.updateKnownObjectWithResult(None, "timeout")
                tp.result_applied = True
                self.noteProgress()

    def _aimChuteForHead(self, now: float) -> None:
        # Hand the head to distribution so the chute aims while the next piece is
        # captured (the throughput overlap). Distribution has a single slot, so
        # only ever place the head; the next piece is placed after this one ejects
        # and frees the slot.
        tp = self._headPiece()
        if tp is None or tp.placed:
            return
        if not tp.result_applied:
            # A forward piece that was never even captured (stray / churn leftover /
            # a multi-drop sibling that skipped the drop zone) would otherwise sit
            # as an un-shippable head forever. After a grace period, send it to misc
            # so it can be ejected and the queue drains.
            if tp.worker.ctx.classify_started_at == 0.0 and (now - tp.created_at) > _STRAY_MISC_S:
                self._ensureKnownObject(tp)
                obj0 = tp.known_object
                if obj0 is not None:
                    obj0.classification_status = ClassificationStatus.unknown
                    obj0.part_id = None
                    tp.worker.emitKnownObject()
                tp.result_applied = True
                self.logger.warning(
                    f"{LOG_TAG} stray head track={tp.track_id} never classified -> misc"
                )
            else:
                return
        self._ensureKnownObject(tp)
        obj = tp.known_object
        if obj is None:
            return
        if obj.part_id is None and obj.classification_status in (
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        ):
            obj.classification_status = ClassificationStatus.unknown
        self.transport.placePieceForDistribution(obj)
        tp.placed = True
        self.noteProgress()
        self.logger.info(
            f"{LOG_TAG} aiming chute for head track={tp.track_id} "
            f"(status={obj.classification_status})"
        )

    def _headReady(self, tp: _TrackedPiece) -> bool:
        # Classified AND the chute is physically aimed for this piece.
        obj = tp.known_object
        return bool(
            tp.placed
            and self.shared.distribution_ready
            and obj is not None
            and obj.stage == PieceStage.distributing
        )

    # ----------------------------------------------------------------- movement

    def _maybeStartRotation(self) -> None:
        # The ONLY two rotation triggers, both requiring a captured drop piece to
        # bring into the channel:
        #   1. no head on the channel       -> stage the drop piece (no eject)
        #   2. head ready to ship           -> eject it AND stage the drop piece
        # If a head exists but is not ready yet, we wait (don't rotate a not-ready
        # piece toward the fall-off).
        drop = self._dropPiece()
        if drop is None or not drop.capture_done:
            return
        head = self._headPiece()
        if head is None:
            self._stage_target = drop
            self._eject_target = None
            self._enterPhase(_Phase.STAGING)
            self.logger.info(f"{LOG_TAG} ROTATE: stage track={drop.track_id} (no head)")
        elif self._headReady(head):
            self._stage_target = drop
            self._eject_target = head
            self._enterPhase(_Phase.EJECTING)
            self.logger.info(
                f"{LOG_TAG} ROTATE: eject track={head.track_id} + stage track={drop.track_id}"
            )

    def _ejecting(self, state, stopped: bool, now: float) -> None:
        target = self._eject_target
        if target is None:
            self._enterPhase(_Phase.STAGING)
            return
        gone_for = now - target.last_seen
        timed_out = (now - self._phase_started_at) > _EJECT_TIMEOUT_S
        if gone_for >= _EJECT_GONE_CONFIRM_S or timed_out:
            # Track id gone (debounced) == the piece dropped off the fall-off ==
            # ejected. Commit it to distribution; the chute was already aimed.
            self.transport.advanceTransport()
            if timed_out and gone_for < _EJECT_GONE_CONFIRM_S:
                self.logger.warning(
                    f"{LOG_TAG} EJECT timeout track={target.track_id} — committing anyway"
                )
            else:
                self.logger.info(f"{LOG_TAG} ejected track={target.track_id} (id gone)")
            self._eject_target = None
            self._enterPhase(_Phase.STAGING)
            return
        if gone_for > 0.0:
            return  # id missing (likely just dropped) — stop pushing, let it confirm
        if stopped:
            gap = state.exit_com_forward_to_center_deg
            if gap is not None and gap > self.ctx.config.discharge_center_tolerance_deg:
                move = min(self.ctx.config.discharge_max_move_output_deg, gap)
                self.startOutputMove(
                    C4_TRAVEL_SIGN * move, self.ctx.config.discharge_speed_usteps_per_s
                )

    def _staging(self, state, stopped: bool, now: float) -> None:
        # Advance the platter until the DROP ZONE IS CLEAR — i.e. the new piece and
        # any multi-drop siblings have all left the drop zone (into the holding
        # area). Keying on "drop clear" rather than "one chosen piece reached
        # precise" is what moves a clump through together instead of stranding the
        # trailing piece.
        if (now - self._phase_started_at) > _STAGE_TIMEOUT_S:
            self.logger.warning(f"{LOG_TAG} STAGE timeout — giving up")
            self._stage_target = None
            self._enterPhase(_Phase.WAITING)
            return
        if not stopped:
            return
        drop_clear = (not state.in_drop) and not any(
            tp.zone == _ZONE_DROP for tp in self._pieces.values()
        )
        if drop_clear:
            self.logger.info(f"{LOG_TAG} staged -> holding (drop clear)")
            self._stage_target = None
            self._enterPhase(_Phase.WAITING)
            return
        # Size the nudge by the leading piece's gap to the precise entry so the head
        # converges onto the holding band; once the leading piece is already at/past
        # precise (gap <= tol) but the drop zone still isn't clear, fall back to a
        # fixed step to keep pushing the clump out.
        gap = state.exit_com_forward_to_precise_deg
        move = _STAGE_STEP_DEG
        tol = self.ctx.config.precise_center_tolerance_deg
        if gap is not None:
            lead_to_exit = state.exit_com_forward_deg
            # comForwardToPreciseEntryDeg wraps to (-180, 180]; a piece that lands
            # far up the drop zone reads as a small/negative gap when it is really a
            # near-full turn short. Un-wrap when the leading gap-to-exit shows it is
            # clearly upstream.
            if gap <= tol and lead_to_exit is not None and lead_to_exit > 180.0:
                gap += 360.0
            if gap > tol:
                move = min(self.ctx.config.discharge_max_move_output_deg, gap)
        self.startOutputMove(
            C4_TRAVEL_SIGN * move, self.ctx.config.precise_converge_speed_usteps_per_s
        )

    def _enterPhase(self, phase: _Phase) -> None:
        # Deliberately NOT a watchdog progress credit: the eject/stage timeouts
        # re-enter phases every _*_TIMEOUT_S, so a wedged piece would ping-pong
        # STAGING <-> WAITING forever and never trip the stall incident. Real
        # progress is credited where pieces demonstrably move or complete a
        # milestone instead.
        self._phase = phase
        self._phase_started_at = time.monotonic()

    # ------------------------------------------------------------------ helpers

    def _cropBurstFrame(self, worker: Rev01BaseState, bbox, perc_frame) -> None:
        ctx = worker.ctx
        if perc_frame.bgr is None or bbox is None:
            return
        frame_ts = float(perc_frame.timestamp)
        if frame_ts <= ctx.last_capture_frame_ts:
            return
        crop = self.cv.cropBbox(perc_frame.bgr, bbox, ctx.config.crop_padding_px)
        if crop is None:
            return
        sharp = self.sharpness(crop)
        quality = crop_quality.scoreCrop(crop)
        ctx.captured_crops.append(crop)
        ctx.captured_crop_sharpness.append(sharp)
        ctx.captured_crop_quality.append(quality)
        ctx.captured_crop_timestamps.append(frame_ts)
        ctx.last_capture_frame_ts = frame_ts
        obj = ctx.known_object
        if obj is not None:
            encoded = self.encodeFrame(crop)
            if encoded is not None:
                obj.latest_captured_crop = encoded
                obj.latest_captured_crop_ts = frame_ts
                obj.recognition_image_set.append(
                    RecognitionImage(
                        image=encoded,
                        source="c4_burst",
                        used=False,
                        ts=frame_ts,
                        channel=4,
                        created_at=frame_ts,
                        sharpness=sharp,
                    )
                )
            worker.emitKnownObject()

    def cleanup(self) -> None:
        for tp in self._pieces.values():
            try:
                tp.worker.abandonInFlightObject("two-piece classification channel teardown")
            except Exception:
                pass
        self._pieces = {}
        self._phase = _Phase.WAITING
        self._eject_target = None
        self._stage_target = None
        self._multi_drop_streak = 0
        self._multi_drop_last_ts = -1.0
        # Fresh watchdog window on the next start — a pause must not count
        # toward "stalled".
        self.last_progress_at = time.monotonic()
        self.ctx.reset()
        self.ctx.known_object = None
