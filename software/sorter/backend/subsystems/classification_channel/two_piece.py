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
    shakeChannelClear,
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
_ZONE_EXIT_ONLY = 2
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
# A head that was never photographed in the drop zone (it appeared forward)
# waits this long for orphan adoption, then gets a burst at rest; if no at-rest
# frame arrives by _STRAY_MISC_S it drains to misc unclassified.
_STRAY_CAPTURE_S = 4.0
_STRAY_MISC_S = 12.0
# Fixed forward nudge (output deg) used while STAGING once the leading piece has
# already reached/passed precise but the drop zone still isn't clear — keeps
# pushing the clump out of the drop zone without a gap to size against.
_STAGE_STEP_DEG = 25.0

# Safety ceilings so a move that never resolves can't wedge the machine forever.
_EJECT_TIMEOUT_S = 15.0
# A head that is classified and aimed but has no successor in the drop zone
# is ejected on its own after this grace. Short enough that a sparse feed
# (last piece of a batch, a slow C3) does not park the piece until the 30 s
# stall watchdog commits it; long enough that a paired eject+stage rotation,
# which keeps the flow overlapped, still wins under a continuous feed.
_LONE_HEAD_EJECT_S = 3.0
# A forward piece that already carries a capture/result and whose track id
# vanished is kept as an orphan for this long. The tracker re-issues ids on
# a piece that was pushed into the holding band (seen 2026-09-05: classified
# and aimed as track 7, back as track 8 four seconds later); the new id
# adopts the orphan instead of starting over as an unclassified stray.
_ORPHAN_ADOPT_S = 10.0
# A new track id whose box overlaps this much with a piece seen within
# ``_ALIAS_RECENT_S`` is the same physical piece under a second id (the
# tracker flips between two ids on one piece) — it is aliased, not created.
_ALIAS_IOU = 0.5
_ALIAS_RECENT_S = 1.0
_STAGE_TIMEOUT_S = 15.0

# Stall-watchdog progress signal: a tracked piece's gap-to-exit must change by
# more than this (output deg) to count as the piece actually moving. Well above
# per-frame detection jitter on a stationary piece, well below any real nudge.
_PROGRESS_MOVE_DEG = 5.0


# A box centre moving more than this between observations is real movement.
_STILL_MAX_SHIFT_PX = 8.0


# A piece in the unnamed gap counts as "still at the exit" only when its
# centre is this close to (or past) the exit-only entry edge; an upstream
# arrival swept into the gap behind the holding band has a large gap.
_EXIT_GAP_NEAR_DEG = 10.0


def _exitArcOccupied(state) -> bool:
    for po in getattr(state, "pieces", ()):
        zone = int(getattr(po, "zone_code", 0))
        if zone == _ZONE_EXIT_ONLY:
            return True
        if zone == _ZONE_NONE:
            gap = getattr(po, "com_forward_to_exit_deg", None)
            if gap is None or float(gap) <= _EXIT_GAP_NEAR_DEG:
                return True
    return False


def _topScore(result: object) -> Optional[float]:
    if not isinstance(result, dict):
        return None
    items = result.get("items") or []
    if not items or not isinstance(items[0], dict):
        return None
    score = items[0].get("score")
    try:
        return float(score) if score is not None else None
    except (TypeError, ValueError):
        return None


def retryImproves(new_score: Optional[float], first_score: Optional[float]) -> bool:
    """The second result replaces the first only when it scores higher."""
    if new_score is None:
        return False
    return first_score is None or new_score > first_score


def _bboxCenterShift(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    if a == (0, 0, 0, 0):
        return 0.0
    ax, ay = (a[0] + a[2]) / 2.0, (a[1] + a[3]) / 2.0
    bx, by = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    return max(abs(ax - bx), abs(ay - by))


def _bboxIou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter <= 0:
        return 0.0
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    union = area_a + area_b - inter
    return float(inter) / float(union) if union > 0 else 0.0


def _reidentificationCandidate(candidates, bbox):
    """Require nearby, similarly sized boxes and an unambiguous match.

    This deliberately refuses recovery after a large unobserved move. Until
    motion prediction is available, losing a result is preferable to assigning
    that result (and its bin) to a different physical piece.
    """
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if width <= 0 or height <= 0:
        return None
    ranked = []
    for tp in candidates:
        old = tp.bbox
        ow, oh = old[2] - old[0], old[3] - old[1]
        if ow <= 0 or oh <= 0:
            continue
        if not (0.5 <= width / ow <= 2.0 and 0.5 <= height / oh <= 2.0):
            continue
        distance = _bboxCenterShift(old, bbox) / max(width, height, ow, oh)
        if distance <= 1.5:
            ranked.append((distance, tp))
    ranked.sort(key=lambda item: item[0])
    if not ranked or (len(ranked) > 1 and ranked[1][0] - ranked[0][0] < 0.5):
        return None
    return ranked[0][1]


def _reidentificationRejection(candidates, bbox) -> str:
    """Why _reidentificationCandidate returned None — for the log only."""
    width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if width <= 0 or height <= 0:
        return "new box has no area"
    notes = []
    for tp in candidates:
        old = tp.bbox
        ow, oh = old[2] - old[0], old[3] - old[1]
        if ow <= 0 or oh <= 0:
            notes.append(f"track={tp.track_id}: no stored box")
            continue
        rw, rh = width / ow, height / oh
        distance = _bboxCenterShift(old, bbox) / max(width, height, ow, oh)
        notes.append(
            f"track={tp.track_id}: size ratio w={rw:.2f} h={rh:.2f} distance={distance:.2f} boxes"
        )
    if not notes:
        return "no candidates"
    return "; ".join(notes) + " — rule: 0.5<=ratio<=2, distance<=1.5, unambiguous by 0.5"


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
        # Since when the box has held still (re-armed on any real movement).
        self.still_since = now
        # Burst capture (drop zone only) has finished -> safe to rotate the piece
        # out of the drop zone.
        self.capture_done = False
        # Classification result has been written onto the KnownObject.
        self.result_applied = False
        # Handed to distribution (chute is aiming / aimed for it).
        self.placed = False
        self.placed_at = 0.0
        # Second burst at rest for a low-confidence result (see _retryHeadAtRest).
        self.retry_started = False
        self.retry_done = False
        self.first_score: Optional[float] = None
        # Crops already captured when the retry burst started (kept for the
        # combined request; the retry adds its own frames on top).
        self.retry_base = 0
        # Committed to distribution as ejected; its track id may linger for the
        # retire window, but it is no longer a head to aim or eject.
        self.ejected = False
        # Two+ pieces landed in the drop zone at once -> can't classify reliably,
        # route to the misc bin. multi_drop_group ties the clump's distinct track
        # ids together as one logical multi-drop (None when not a multi-drop).
        self.double_feed = False
        self.multi_drop_group: Optional[int] = None
        # Appeared forward of the drop zone, never photographed in flight: its
        # only burst is the at-rest one (see _startStrayCapture).
        self.stray = False

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
        # Forward pieces with a result whose id vanished, newest last: (piece, when).
        self._orphans: list[tuple[_TrackedPiece, float]] = []
        # Second ids the tracker issued for an already tracked piece -> its piece.
        self._aliases: dict[int, _TrackedPiece] = {}
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
        # Multi-feed debounce: consecutive distinct frames detecting >1 drop-zone id.
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
        A placed head is committed only after the channel is confirmed clear.
        Everything else on the channel falls wherever the chute
        happens to point; their in-flight objects are abandoned."""
        placed = next((tp for tp in self._pieces.values() if tp.placed and not tp.ejected), None)
        result = clearChannelByAdvancing(
            self.gc,
            self.irl,
            self.irl_config,
            vision=self.cv._vision,
            max_output_deg=max_output_deg,
            label=LOG_TAG,
        )
        if not result.cleared and result.reason == "budget_exhausted":
            # Rotation moved the platter under the piece without taking it
            # along (a tyre on the fall-off lip, a plate wedged at the rim):
            # shake it loose with the exit-release ladder instead.
            shaken = shakeChannelClear(
                self.gc, self.irl, self.irl_config, vision=self.cv._vision, label=LOG_TAG
            )
            result = ChannelClearResult(
                shaken.cleared, result.occupied_at_start, result.output_deg_moved, shaken.reason
            )
        if result.cleared:
            if placed is not None:
                obj = placed.known_object
                if obj is not None and obj.stage == PieceStage.distributing:
                    self.transport.advanceTransport()
                    placed.ejected = True
                    self.logger.info(f"{LOG_TAG} stall auto-clear: confirmed placed head track={placed.track_id} left")
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
                self._captureRetryHead(perception_service, now)
                self._aimChuteForHead(now)
                self._maybeStartRotation(now)
        elif self._phase == _Phase.EJECTING:
            if stopped:
                self._captureDropPieces(perception_service, now)  # a late arrival
            self._ejecting(state, stopped, now)
        elif self._phase == _Phase.STAGING:
            if stopped:
                self._captureDropPieces(perception_service, now)
            self._staging(state, stopped, now)

    # ------------------------------------------------- perception reconciliation

    def _observe(self, state, now: float) -> None:
        """Match this frame's observations to tracked pieces by track id, create
        pieces for new ids, retire pieces whose id has been gone too long, and
        flag double feeds."""
        seen: set[int] = set()
        # Determine this before iterating: matching must not depend on detector
        # ordering. A separately visible piece is not a lost track to recover.
        visible = {
            id(tp)
            for po in getattr(state, "pieces", ())
            if (tp := self._pieces.get(po.sv_bt_track_id) or self._aliases.get(po.sv_bt_track_id)) is not None
        }
        for po in getattr(state, "pieces", ()):
            tid = po.sv_bt_track_id
            if tid is None:
                continue  # untracked box — counts for zone occupancy, not identity
            b = po.bbox
            bbox = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
            tp = self._pieces.get(tid) or self._aliases.get(tid)
            if tp is None:
                tp = self._aliasOverlappingPiece(tid, bbox, now)
            if tp is None:
                zone = int(po.zone_code)
                if zone != _ZONE_DROP:
                    # Pieces arrive in the drop zone, never forward: a new
                    # forward id is a re-identification or a twin box.
                    tp = self._adoptOrphan(tid, bbox, now) or self._aliasNearestForwardPiece(tid, bbox, now, visible)
                if tp is None:
                    tp = self._createPiece(tid, now)
            if tp.track_id in seen:
                continue  # the same piece reported twice in one frame
            seen.add(tp.track_id)
            visible.add(id(tp))
            tp.zone = int(po.zone_code)
            if _bboxCenterShift(tp.bbox, bbox) > _STILL_MAX_SHIFT_PX:
                tp.still_since = now
            tp.bbox = bbox
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
        self._flagDoubleFeeds(state, seen)

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

    def _aliasOverlappingPiece(
        self, tid: int, bbox: tuple[int, int, int, int], now: float
    ) -> Optional[_TrackedPiece]:
        best: Optional[_TrackedPiece] = None
        best_iou = _ALIAS_IOU
        for tp in self._pieces.values():
            if (now - tp.last_seen) > _ALIAS_RECENT_S or tp.ejected:
                continue
            iou = _bboxIou(bbox, tp.bbox)
            if iou > best_iou:
                best, best_iou = tp, iou
        if best is None:
            return None
        self._aliases[tid] = best
        self.logger.info(
            f"{LOG_TAG} track={tid} overlaps track={best.track_id} (iou={best_iou:.2f}) — same piece"
        )
        return best

    def _aliasNearestForwardPiece(
        self, tid: int, bbox: tuple[int, int, int, int], now: float, visible: set[int]
    ) -> Optional[_TrackedPiece]:
        candidates = [tp for tp in self._pieces.values()
                      if tp.zone != _ZONE_DROP and not tp.ejected
                      and id(tp) not in visible and (now - tp.last_seen) <= _ALIAS_RECENT_S]
        best = _reidentificationCandidate(candidates, bbox)
        if best is None:
            if candidates:
                self.logger.info(
                    f"{LOG_TAG} track={tid} appeared forward, alias rejected: "
                    f"{_reidentificationRejection(candidates, bbox)}"
                )
            return None
        self._aliases[tid] = best
        self.logger.info(
            f"{LOG_TAG} track={tid} appeared forward next to track={best.track_id} "
            f"(shift={_bboxCenterShift(best.bbox, bbox):.0f}px) — same piece"
        )
        return best

    def _adoptOrphan(self, tid: int, bbox: tuple[int, int, int, int], now: float) -> Optional[_TrackedPiece]:
        candidates = [piece for piece, lost_at in self._orphans
                      if now - lost_at <= _ORPHAN_ADOPT_S and not piece.ejected]
        tp = _reidentificationCandidate(candidates, bbox)
        if tp is None:
            if candidates:
                self.logger.info(
                    f"{LOG_TAG} track={tid}: orphan adoption rejected: "
                    f"{_reidentificationRejection(candidates, bbox)}"
                )
            return None
        self._orphans = [(piece, lost_at) for piece, lost_at in self._orphans if piece is not tp]
        self.logger.info(f"{LOG_TAG} re-identified track={tp.track_id} as track={tid}")
        tp.track_id = tid
        tp.last_seen = now
        self._pieces[tid] = tp
        return tp

    def _expireOrphans(self, now: float) -> None:
        keep: list[tuple[_TrackedPiece, float]] = []
        for tp, orphaned_at in self._orphans:
            if (now - orphaned_at) <= _ORPHAN_ADOPT_S:
                keep.append((tp, orphaned_at))
                continue
            tp.worker.abandonInFlightObject("track id gone (left channel)")
            if tp.known_object is not None:
                self.noteProgress()
            self.logger.info(f"{LOG_TAG} retired piece track={tp.track_id} (orphan expired)")
        self._orphans = keep

    def _retireGonePieces(self, now: float) -> None:
        self._expireOrphans(now)
        for tid in [
            tid
            for tid, tp in self._pieces.items()
            if (now - tp.last_seen) > _TRACK_GONE_RETIRE_S
        ]:
            tp = self._pieces.pop(tid)
            self._aliases = {a: t for a, t in self._aliases.items() if t is not tp}
            if tp.capture_done and not tp.ejected:
                # Carries a capture/result and has not been committed: keep it
                # adoptable. Includes a piece still coded DROP — its id can
                # vanish while the platter pushes it into the holding band.
                self._orphans.append((tp, now))
                self.logger.info(f"{LOG_TAG} track={tid} gone — kept as orphan for re-identification")
                continue
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

    def _flagDoubleFeeds(self, state, seen: set[int]) -> None:
        # Only ids detected in THIS frame count. A track that vanished but is
        # still inside its retire window (e.g. a piece first glimpsed as a sliver
        # at the frame edge, re-identified once fully visible) must not pair up
        # with its successor and fake a two-piece drop.
        drop = [
            tp
            for tid, tp in self._pieces.items()
            if tid in seen and tp.zone == _ZONE_DROP
        ]
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
        fwd = [tp for tp in self._pieces.values() if tp.zone != _ZONE_DROP and not tp.ejected]
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
        settle_s = float(self.ctx.config.capture_settle_ms) / 1000.0
        for tp in list(self._pieces.values()):
            if tp.zone != _ZONE_DROP or tp.capture_done or tp.double_feed:
                continue
            if (now - tp.still_since) < settle_s:
                continue  # still tumbling after landing — no blurred burst
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
                if tp.retry_started and not tp.retry_done:
                    tp.retry_done = True
                    tp.result_applied = True
                    new_score = _topScore(result)
                    if tp.stray:
                        # There is no first result to fall back on: take
                        # whatever the at-rest burst produced, error included.
                        tp.worker.updateKnownObjectWithResult(result, error)
                        self.logger.info(
                            f"{LOG_TAG} stray track={tp.track_id} classified at rest: score {new_score}"
                        )
                    elif error is None and retryImproves(new_score, tp.first_score):
                        tp.worker.updateKnownObjectWithResult(result, error)
                        self.logger.info(
                            f"{LOG_TAG} retry at rest track={tp.track_id}: "
                            f"{tp.first_score} -> {new_score:.2f}, applied"
                        )
                    else:
                        self.logger.info(
                            f"{LOG_TAG} retry at rest track={tp.track_id}: "
                            f"{tp.first_score} -> {new_score}, kept the first result"
                        )
                    self.noteProgress()
                    continue
                tp.worker.updateKnownObjectWithResult(result, error)
                tp.result_applied = True
                self.noteProgress()
            elif (now - ctx.classify_started_at) > ctx.config.classify_timeout_s:
                if tp.retry_started and not tp.retry_done:
                    tp.retry_done = True
                    tp.result_applied = True
                    self.logger.warning(f"{LOG_TAG} retry timeout track={tp.track_id}; keeping first result")
                    self.noteProgress()
                    continue
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
            if tp.retry_started and not tp.retry_done:
                if not (tp.stray and not tp.capture_done and (now - tp.created_at) > _STRAY_MISC_S):
                    return  # burst in flight — neither a stray nor an orphan case
                self._strayToMisc(tp)  # no at-rest frame ever came — drain the queue
            elif tp.worker.ctx.classify_started_at != 0.0:
                return  # first result still pending
            else:
                # An uncaptured head with an orphan waiting is that orphan under a
                # second id (two boxes on one piece from the first frame): take
                # over its capture, result and chute aim instead of starting a stray.
                if self._orphans:
                    adopted = self._adoptOrphan(tp.track_id, tp.bbox, now)
                    if adopted is not None:
                        adopted.zone = tp.zone
                        adopted.bbox = tp.bbox
                        adopted.gap_to_exit = tp.gap_to_exit
                        return
                # A forward piece that was never even captured (stray / churn
                # leftover / a multi-drop sibling that skipped the drop zone / a
                # piece the camera only saw once the platter turned) would
                # otherwise sit as an un-shippable head forever. After a grace
                # period, photograph it at rest instead of sending it to misc blind.
                if (now - tp.created_at) > _STRAY_CAPTURE_S:
                    self._startStrayCapture(tp)
                return
        self._ensureKnownObject(tp)
        obj = tp.known_object
        if obj is None:
            return
        if self._retryHeadAtRest(tp, obj):
            return  # second burst in progress — aim only once it is in
        if obj.part_id is None and obj.classification_status in (
            ClassificationStatus.pending,
            ClassificationStatus.classifying,
        ):
            obj.classification_status = ClassificationStatus.unknown
        self.transport.placePieceForDistribution(obj)
        tp.placed = True
        tp.placed_at = now
        self.noteProgress()
        self.logger.info(
            f"{LOG_TAG} aiming chute for head track={tp.track_id} "
            f"(status={obj.classification_status})"
        )

    def _startStrayCapture(self, tp: _TrackedPiece) -> None:
        """Give a never-photographed head the at-rest burst; the retry
        machinery captures, classifies and applies the result."""
        self._ensureKnownObject(tp)
        tp.stray = True
        tp.retry_started = True
        tp.retry_base = len(tp.worker.ctx.captured_crops)
        self.logger.warning(
            f"{LOG_TAG} stray head track={tp.track_id} never captured -> burst at rest"
        )

    def _strayToMisc(self, tp: _TrackedPiece) -> None:
        self._ensureKnownObject(tp)
        tp.retry_done = True
        tp.result_applied = True
        obj = tp.known_object
        if obj is not None:
            obj.classification_status = ClassificationStatus.unknown
            obj.part_id = None
            tp.worker.emitKnownObject()
        self.logger.warning(
            f"{LOG_TAG} stray head track={tp.track_id} never classified -> misc"
        )

    def _retryHeadAtRest(self, tp: _TrackedPiece, obj) -> bool:
        """Start (or keep waiting for) the second burst of a low-confidence
        head. Returns True while the aim must wait for it."""
        if tp.retry_done or not bool(getattr(self.ctx.config, "low_confidence_retry", True)):
            return False
        if obj.classification_status not in (
            ClassificationStatus.low_confidence,
            ClassificationStatus.not_found,
        ):
            return False
        if not tp.retry_started:
            ctx = tp.worker.ctx
            tp.first_score = float(obj.confidence) if obj.confidence is not None else None
            tp.retry_started = True
            tp.capture_done = False
            tp.result_applied = False
            # Keep the in-flight frames: the retry ADDS at-rest views and the
            # quality selection picks the best of both sets.
            tp.retry_base = len(ctx.captured_crops)
            ctx.capturing_started_at = 0.0
            ctx.classify_started_at = 0.0
            ctx.classification_result = None
            ctx.classification_error = None
            self.logger.info(
                f"{LOG_TAG} retry at rest track={tp.track_id}: first score {tp.first_score} — second burst"
            )
        return True

    def _captureRetryHead(self, perception_service, now: float) -> None:
        tp = self._headPiece()
        if tp is None or not tp.retry_started or tp.retry_done or tp.capture_done:
            return
        raw = perception_service.read_bboxes_and_frame(4)
        if raw is None:
            return
        _bboxes, perc_frame = raw
        ctx = tp.worker.ctx
        if ctx.capturing_started_at == 0.0:
            ctx.capturing_started_at = now
        self._cropBurstFrame(tp.worker, tp.bbox, perc_frame)
        cfg = ctx.config
        new_frames = len(ctx.captured_crops) - tp.retry_base
        elapsed_ms = (now - ctx.capturing_started_at) * 1000.0
        done = new_frames >= int(cfg.max_captures) or (
            new_frames > 0 and elapsed_ms >= float(cfg.capture_at_rest_ms)
        )
        reason = "frame_cap" if new_frames >= int(cfg.max_captures) else "window"
        if done:
            tp.capture_done = True
            ctx.classify_started_at = now
            caps = list(ctx.captured_crops)
            if caps:
                tp.worker.spawnClassifyThread(caps)
            else:
                ctx.classification_error = "no_captures"
            self.logger.info(
                f"{LOG_TAG} retry burst track={tp.track_id} (+{new_frames} at rest, "
                f"{len(caps)} crops total, stop={reason}); classifying"
            )

    def _dropBurstInProgress(self) -> bool:
        for tp in self._pieces.values():
            if tp.zone != _ZONE_DROP or tp.capture_done or tp.double_feed:
                continue
            if tp.worker.ctx.capturing_started_at > 0.0:
                return True
        return False

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

    def _maybeStartRotation(self, now: float) -> None:
        # Rotation triggers:
        #   1. no head on the channel       -> stage the drop piece (no eject)
        #   2. head ready to ship           -> eject it AND stage the drop piece
        #   3. head ready, nothing captured in the drop zone for a grace period
        #                                   -> eject the head on its own
        # If a head exists but is not ready yet, we wait (don't rotate a not-ready
        # piece toward the fall-off).
        drop = self._dropPiece()
        head = self._headPiece()
        if drop is None or not drop.capture_done:
            if (
                head is not None
                and self._headReady(head)
                and (now - head.placed_at) >= _LONE_HEAD_EJECT_S
            ):
                self._stage_target = None
                self._eject_target = head
                self._enterPhase(_Phase.EJECTING)
                self.logger.info(f"{LOG_TAG} ROTATE: eject track={head.track_id} (no successor)")
            return
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
        # Track id gone (debounced) AND nothing left in the exit-only arc == the
        # piece dropped off the fall-off. The id alone is not enough: a tracker
        # blink at the lip re-issues the id on a piece that never fell, and a
        # committed phantom then puts the real piece into the next target bin.
        # Exit-only OR the unnamed gap past it: a piece resting on the lip
        # beyond the exit arc is coded NONE and is still very much on board.
        exit_arc_empty = not _exitArcOccupied(state)
        if gone_for >= _EJECT_GONE_CONFIRM_S and exit_arc_empty:
            # Commit it to distribution; the chute was already aimed.
            self.transport.advanceTransport()
            target.ejected = True
            self.logger.info(f"{LOG_TAG} ejected track={target.track_id} (id gone, exit clear)")
            self._eject_target = None
            self._enterPhase(_Phase.STAGING)
            return
        if timed_out:
            # Retain ownership of the head and its target bin. The existing
            # no-progress watchdog performs recovery; a timer is not an exit
            # sensor and must never commit an occupied output.
            if not getattr(self, "_eject_timeout_logged", False):
                self.logger.warning(f"{LOG_TAG} EJECT timeout track={target.track_id}; waiting for confirmed exit or recovery")
                self._eject_timeout_logged = True
            return
        if gone_for > 0.0:
            return  # id missing (likely just dropped) — stop pushing, let it confirm
        if self._dropBurstInProgress():
            return  # a late arrival is being photographed — no rotation yet
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
        if self._stage_target is None:
            # Nothing was staged (a lone-head eject). Do not sweep a piece that
            # has just landed in the drop zone forward uncaptured — WAITING
            # photographs it first.
            self._enterPhase(_Phase.WAITING)
            return
        if (now - self._phase_started_at) > _STAGE_TIMEOUT_S:
            self.logger.warning(f"{LOG_TAG} STAGE timeout — giving up")
            self._stage_target = None
            self._enterPhase(_Phase.WAITING)
            return
        if not stopped:
            return
        if self._dropBurstInProgress():
            return  # finish the burst of a piece that landed mid-stage first
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
        self._eject_timeout_logged = False
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
        for tp in list(self._pieces.values()) + [tp for tp, _ in self._orphans]:
            try:
                tp.worker.abandonInFlightObject("two-piece classification channel teardown")
            except Exception:
                pass
        self._pieces = {}
        self._orphans = []
        self._aliases = {}
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
