import time
from enum import Enum
from typing import Optional

from defs.known_object import (
    ClassificationStatus,
    KnownObject,
    PieceStage,
    RecognitionImage,
)

from .simple_state_machine_rev01.base import Rev01BaseState
from .simple_state_machine_rev01.constants import C4_TRAVEL_SIGN
from .simple_state_machine_rev01.context import SimpleStateMachineRev01Context

LOG_TAG = "[C4-2PIECE]"

# perception.arcs._region_lookup / PieceObservation.zone_code values. The
# classification channel is a rotating platter viewed from above; pieces travel
# FORWARD (one way, never reversed) through these zones in this order:
#   DROP  -> PRECISE (the holding region) -> EXIT (the fall-off)
_ZONE_NONE = 0
_ZONE_DROP = 1
_ZONE_PRECISE = 3  # the holding region (a.k.a. "precise"); 2 = exit (the fall-off)

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

# Safety ceilings so a move that never resolves can't wedge the machine forever.
_EJECT_TIMEOUT_S = 15.0
_STAGE_TIMEOUT_S = 15.0


class _Phase(Enum):
    # Platter STOPPED. Observe, photograph the drop-zone piece, classify, and aim
    # the chute for the holding piece. The only place we accept a new piece.
    WAITING = "waiting"
    # Rotating the holding piece off the fall-off. Done when its track id is gone.
    EJECTING = "ejecting"
    # Rotating the drop piece forward into the holding region. Done when its track
    # id reads in the precise zone.
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
        self.created_at = now
        self.last_seen = now
        # Burst capture (drop zone only) has finished -> safe to rotate the piece
        # out of the drop zone.
        self.capture_done = False
        # Classification result has been written onto the KnownObject.
        self.result_applied = False
        # Handed to distribution (chute is aiming / aimed for it).
        self.placed = False
        # Two pieces landed in the drop zone at once -> can't classify reliably,
        # route to the misc bin.
        self.double_feed = False

    @property
    def known_object(self) -> Optional[KnownObject]:
        return self.worker.ctx.known_object


class TwoPieceClassificationChannel(Rev01BaseState):
    """Hold up to two pieces on the classification channel, one cycle ahead of
    the chute: one staged in the holding (precise) region being classified +
    aimed, one waiting in the drop zone. The platter only ever turns FORWARD
    (clockwise); no move is reversed.

    SOURCE OF TRUTH = perception track ids (``PieceObservation.sv_bt_track_id``),
    not heuristics: a piece's id moving DROP -> PRECISE confirms it staged; a
    piece's id DISAPPEARING confirms it was ejected off the fall-off.

    State machine (platter-level; per-piece classification runs concurrently):

      WAITING (stopped) --------------------------------------------------+
        - photograph the drop piece (drop zone only), classify off-thread |
        - once the holding piece is classified, aim the chute for it      |
        - feeder may add a piece only here (drop clear + stopped)         |
        - ROTATE when there is a captured drop piece AND                  |
            (holding empty            -> STAGING, or                      |
             holding piece is ready   -> EJECTING)                        |
                                                                          |
      EJECTING (moving) -- push holding piece off the fall-off            |
        - done when its track id is gone -> commit it to distribution     |
          -> STAGING                                                      |
                                                                          |
      STAGING (moving) -- bring the drop piece into the holding region    |
        - done when its track id reads in the precise zone -> WAITING ----+

    "Ready" for the holding piece = classified AND the distribution chute is
    aimed for it. We never eject the holding piece unless a drop piece is there to
    take its place, so one rotation always both ejects and refills.

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
        # Multi-feed debounce: consecutive distinct frames showing >1 drop-zone id.
        self._multi_drop_streak = 0
        self._multi_drop_last_ts = -1.0
        self.ctx.reset()
        self.ctx.known_object = None

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
                self._aimChuteForHoldingPiece()
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

        self._retireGonePieces(now)
        self._flagDoubleFeeds(state)

    def _createPiece(self, track_id: int, now: float) -> _TrackedPiece:
        worker = Rev01BaseState(*self._deps, SimpleStateMachineRev01Context())
        worker.ctx.reset()
        worker.ctx.known_object = KnownObject(
            stage=PieceStage.created,
            classification_status=ClassificationStatus.pending,
            first_carousel_seen_ts=time.time(),
        )
        worker.emitKnownObject()
        tp = _TrackedPiece(track_id, worker, now)
        self._pieces[track_id] = tp
        self.logger.info(f"{LOG_TAG} new piece track={track_id}")
        return tp

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
        for tp in drop:
            if not tp.double_feed:
                self._markDoubleFeed(tp)

    def _markDoubleFeed(self, tp: _TrackedPiece) -> None:
        # Two pieces in the drop zone at once: classification can't be trusted, so
        # skip it and route the piece to the misc bin. It still rides the normal
        # bucket-brigade (staged to holding, then ejected) — just to misc.
        tp.double_feed = True
        tp.capture_done = True
        tp.result_applied = True
        obj = tp.known_object
        if obj is not None:
            obj.classification_status = ClassificationStatus.multi_drop_fail
            obj.part_id = None
            tp.worker.emitKnownObject()
        self.logger.warning(f"{LOG_TAG} double feed -> misc (track={tp.track_id})")

    # --------------------------------------------------- ordered-zone accessors

    def _holdingPiece(self) -> Optional[_TrackedPiece]:
        # Most-forward piece in the holding region (smallest gap to exit leads).
        held = [tp for tp in self._pieces.values() if tp.zone == _ZONE_PRECISE]
        if not held:
            return None
        return min(held, key=lambda tp: tp.gap_to_exit if tp.gap_to_exit is not None else 1e9)

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
            ctx = tp.worker.ctx
            if ctx.capturing_started_at == 0.0:
                ctx.capturing_started_at = now
            self._cropBurstFrame(tp.worker, tp.bbox, perc_frame)
            done, reason = tp.worker.burstCaptureComplete(ctx, now)
            if done:
                tp.capture_done = True
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
            elif (now - ctx.classify_started_at) > ctx.config.classify_timeout_s:
                self.logger.error(f"{LOG_TAG} classify timeout track={tp.track_id} -> unknown")
                tp.worker.updateKnownObjectWithResult(None, "timeout")
                tp.result_applied = True

    def _aimChuteForHoldingPiece(self) -> None:
        # Hand the holding piece to distribution so the chute aims while the next
        # piece is captured (the throughput overlap). Distribution has a single
        # slot, so only ever place the leading holding piece; the next one is
        # placed after this one ejects and frees the slot.
        tp = self._holdingPiece()
        if tp is None or tp.placed or not tp.result_applied:
            return
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
        self.logger.info(
            f"{LOG_TAG} aiming chute for holding piece track={tp.track_id} "
            f"(status={obj.classification_status})"
        )

    def _holdingReady(self, tp: _TrackedPiece) -> bool:
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
        # bring into holding:
        #   1. holding empty                 -> stage the drop piece (no eject)
        #   2. holding piece ready to ship   -> eject it AND stage the drop piece
        # If the holding piece is not ready yet, we wait (don't rotate a not-ready
        # piece toward the fall-off).
        drop = self._dropPiece()
        if drop is None or not drop.capture_done:
            return
        holding = self._holdingPiece()
        if holding is None:
            self._stage_target = drop
            self._eject_target = None
            self._enterPhase(_Phase.STAGING)
            self.logger.info(f"{LOG_TAG} ROTATE: stage track={drop.track_id} (holding empty)")
        elif self._holdingReady(holding):
            self._stage_target = drop
            self._eject_target = holding
            self._enterPhase(_Phase.EJECTING)
            self.logger.info(
                f"{LOG_TAG} ROTATE: eject track={holding.track_id} + stage track={drop.track_id}"
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
        target = self._stage_target
        if target is None or target.track_id not in self._pieces:
            self._enterPhase(_Phase.WAITING)
            return
        if target.zone == _ZONE_PRECISE:
            # Drop -> holding confirmed by the track id reading in the precise
            # zone: "basically successful."
            self.logger.info(f"{LOG_TAG} staged track={target.track_id} -> holding")
            self._stage_target = None
            self._enterPhase(_Phase.WAITING)
            return
        if (now - self._phase_started_at) > _STAGE_TIMEOUT_S:
            self.logger.warning(
                f"{LOG_TAG} STAGE timeout track={target.track_id} (zone={target.zone}) — giving up"
            )
            self._stage_target = None
            self._enterPhase(_Phase.WAITING)
            return
        if stopped:
            gap = state.exit_com_forward_to_precise_deg
            if gap is None:
                return
            # comForwardToPreciseEntryDeg wraps to (-180, 180]; a piece that lands
            # far up the drop zone reads as a small/negative gap ("already past
            # precise") when it is really a near-full turn short. Un-wrap when the
            # reliable gap-to-exit shows it is clearly upstream.
            if gap <= self.ctx.config.precise_center_tolerance_deg and (
                target.gap_to_exit is not None and target.gap_to_exit > 180.0
            ):
                gap += 360.0
            if gap > self.ctx.config.precise_center_tolerance_deg:
                move = min(self.ctx.config.discharge_max_move_output_deg, gap)
                self.startOutputMove(
                    C4_TRAVEL_SIGN * move,
                    self.ctx.config.precise_converge_speed_usteps_per_s,
                )

    def _enterPhase(self, phase: _Phase) -> None:
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
        ctx.captured_crops.append(crop)
        ctx.captured_crop_sharpness.append(sharp)
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
        self.ctx.reset()
        self.ctx.known_object = None
