import time
from collections import Counter, deque
from enum import Enum
from typing import Optional

import incidents

from defs.known_object import (
    ClassificationStatus,
    KnownObject,
    PieceStage,
    RecognitionImage,
    notePieceProblem,
)
from piece_cycles import CycleRecorder
from runtime_stats import C4_WAITING_FOR_PIECE

from .. import crop_quality
from .base import Rev01BaseState
from .channel_clear import (
    ChannelClearResult,
    clearChannelByAdvancing,
)
from .constants import C4_TRAVEL_SIGN
from .context import SimpleStateMachineRev01Context

LOG_TAG = "[C4-2PIECE]"

# perception.arcs._region_lookup / PieceObservation.zone_code values. The
# classification channel is a rotating platter viewed from above; pieces travel
# FORWARD (one way, never reversed) through these zones in this order:
#   DROP  -> PRECISE (the holding region) -> EXIT (the fall-off)
# Anything that has LEFT the drop zone (PRECISE, EXIT, or the unnamed gap NONE
# between them) is "forward" and part of the processing queue.
_ZONE_NONE = 0
_ZONE_DROP = 1
_ZONE_EXIT = 2
_ZONE_PRECISE = 3


def _boxArea(po) -> float:
    b = po.bbox
    return max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))


def _boxCover(a, b) -> float:
    """How much of the smaller of two boxes the other covers, 0 to 1."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return ix * iy / small if small > 0 else 0.0


def _lined(a, b) -> bool:
    """One box lies along the other: its span across x, or across y, is mostly
    inside the other's. The parts of one object (a minifigure's head, torso and
    legs) stack like this; two loose pieces lying touching rarely line up."""
    for lo, hi in ((0, 2), (1, 3)):
        span = min(a[hi] - a[lo], b[hi] - b[lo])
        shared = min(a[hi], b[hi]) - max(a[lo], b[lo])
        if span > 0 and shared >= _LINED_SPAN * span:
            return True
    return False


def _apart(boxes) -> bool:
    """Two or more of the detector's boxes that look like separate pieces: none
    mostly inside another, and at least two of them not lined up."""
    pairs = [(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1:]]
    return (
        len(boxes) >= 2
        and all(_boxCover(a, b) < _NESTED_COVER for a, b in pairs)
        and any(not _lined(a, b) for a, b in pairs)
    )


def _closePair(drop: list) -> Optional[tuple]:
    """Two boxes of a similar size within _PAIR_DEG of each other, or None."""
    for i, a in enumerate(drop):
        for b in drop[i + 1:]:
            if abs(float(a.com_forward_to_exit_deg) - float(b.com_forward_to_exit_deg)) > _PAIR_DEG:
                continue
            small, big = sorted((_boxArea(a), _boxArea(b)))
            if big > 0 and small >= _PAIR_MIN_AREA_FRAC * big:
                return (a, b)
    return None
# (2 = exit / the fall-off, 3 = precise / the holding region; the queue only
# branches on DROP vs not-DROP — "left the drop zone" is what matters for it.)

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

# How many eject cycles distribution keeps every door open after we lose an
# unrouted multi-drop piece. A loose piece falls at the exit, so it goes on the
# very next turn of the platter; two cycles covers the one after it as well.
_BUCKET_HOLD_EJECTS = 2

# The head goes out with the turn that stages the next piece. When no next
# piece has come for this long (the feeder ran dry, or stalled), it goes out on
# its own, to its bin, instead of waiting for the stall watchdog to sweep the
# channel into the bucket.
_HEAD_ALONE_AFTER_S = 12.0

# A piece that does not fall off the exit (a tire's rubber grips the platter)
# rides on around the channel, past the camera, and comes back into the drop
# zone, where it is photographed and classified again: one piece, two records.
# Each eject is remembered this long, which covers riding one to three more
# cycles. A piece classified as the same part and colour within it is taken for
# the one that came back when it rolls (a wheel or tire), or when that eject
# timed out with the piece never seen to fall.
_CIRCLING_WINDOW_S = 30.0
_ROLLING_WORDS = ("tire", "tyre", "wheel")
PIECE_CIRCLING_INCIDENT_KIND = "piece_circling"

# A piece committed as ejected but still seen at the exit did not fall: its id
# blinked out just long enough to read as gone. Being the most forward piece it
# stays the head, so nothing else is aimed or ejected until the stall watchdog
# sweeps the whole channel into the bucket. While no other piece holds the
# chute (it is still aimed where this piece was going), turn the channel a
# little to push it off, a few times at most; the watchdog stays the fallback.
_LINGER_AFTER_EJECT_S = 1.0
_PUSH_OFF_DEG = 15.0
_PUSH_OFF_TRIES = 3

# The tracker sometimes gives a piece a new id: while it sits waiting for the
# chute, or while the channel turns it. The old id then looked gone and the new
# one like a piece nobody photographed, so the piece went to misc unidentified
# and its classification timed out on its own record. A piece lost this way is
# handed to a new id at its place: one seen on top of it while both existed, or
# one that turns up within _RELINK_WINDOW_S no further along than the channel
# can have carried it (_RELINK_STILL_DEG standing still, _RELINK_TURNED_DEG
# when it turned since).
_RELINK_WINDOW_S = 2.0
_RELINK_STILL_DEG = 15.0
_RELINK_TURNED_DEG = 120.0
# Two ids this close are one piece (a tracker double), not two pieces.
_SAME_PIECE_DEG = 8.0

# A second piece that lands while the channel is turning the last one off the
# drop zone came in unasked: the feeder only adds a piece while the channel
# stands still with the drop zone clear. Seen this long, it and the piece it
# came in behind are a double feed. It lands where the feeder drops pieces and
# is carried forward from there, so it is first seen no further from the exit
# than where the piece before it landed (plus the landing scatter). A track
# first seen further back came around from past the exit (a piece that did not
# fall, out of the camera's sight there): no feed, so no double feed.
_LATE_ARRIVAL_CONFIRM_S = 0.1
_LATE_LANDING_SLACK_DEG = 40.0
_LATE_ARRIVAL_MAX_GAP_DEG = 280.0

# Two pieces from one feed that land touching are fused into one box by the
# camera's merge of nearby boxes (one piece is often drawn as several), often
# from the very next frame, and tracked and photographed as one piece. The
# frame they land in can still show them apart: two boxes of a similar size
# (the smaller at least _PAIR_MIN_AREA_FRAC of the larger) within _PAIR_DEG of
# each other in the drop zone while the channel stands still. One such frame
# makes every piece there a double feed, and so does a piece that lands within
# _PAIR_FOLLOW_S after it (the fused box often gets its id a few frames later).
_PAIR_DEG = 25.0
_PAIR_MIN_AREA_FRAC = 0.3
_PAIR_FOLLOW_S = 1.0
# A second piece that lands against the one in the drop zone is fused into its
# box: the box grows. Measured from _GROW_SETTLE_S after the piece appeared
# (it has stopped bouncing), against the median of its first three readings
# at rest; _GROW_FACTOR in _GROW_FRAMES readings makes it a double feed.
_GROW_SETTLE_S = 0.25
_GROW_FACTOR = 1.6
_GROW_FRAMES = 2

# The camera merges touching boxes into one piece box, so two pieces that land
# touching are tracked as one. What the detector draws inside that box tells
# them apart: on two pieces it draws the same separate boxes frame after frame;
# on one piece drawn in parts (an assembly, a printed part) its boxes change
# from frame to frame and nest, one drawn around the whole piece and others
# around its parts. While a piece is photographed at rest, if at least
# _APART_FRAC of the frames show its boxes apart (none covering more than
# _NESTED_COVER of another) and at least _STEADY_FRAC show the same number of
# them, it is two pieces. An assembly whose parts lie side by side looks the
# same and goes to misc too: no bin is right for it either.
_NESTED_COVER = 0.5
# Boxes lined up along one axis (see _lined) are the parts of one object. A whole
# minifigure, drawn as a head box above a body box, went to misc without this.
_LINED_SPAN = 0.8
_APART_FRAC = 0.8
_STEADY_FRAC = 0.8
_APART_MIN_FRAMES = 6
# After it left the drop zone, a piece taken for one is still two if moving it
# shows two separate boxes for _APART_LATER_FRAMES frames in a row, or if a new
# id appears beside it (more than _SAME_PIECE_DEG, at most _SPLIT_DEG away) and
# stays _SPLIT_CONFIRM_S: they came apart, or another piece landed against it.
_APART_LATER_FRAMES = 15
_SPLIT_DEG = 35.0
_SPLIT_CONFIRM_S = 0.4

# No turn brings a waiting piece (one not being ejected) closer to the exit than
# this, so it can't drop into the bin the chute is aimed at for another piece.
_KEEP_ON_MIN_GAP_DEG = 25.0

# The flow is stepped every loop tick while the machine runs: a longer gap
# means it was paused, or held by an incident.
_RESUME_GAP_S = 1.0

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


def _logC4Piece(track_id: int, piece_uuid: str, took_over: Optional[int] = None) -> None:
    """Tie a C4 track to its piece in the control-data log, which names C4
    pieces only by track id, so the piece's earlier tracks on C2 and C3 can be
    found from it. A track that takes over a lost one names the lost id."""
    try:
        import control_data_store

        event = {"type": "event", "kind": "c4_piece", "track": track_id, "piece": piece_uuid}
        if took_over is not None:
            event["took_over"] = took_over
        control_data_store.record({**event, "t": time.time(), "mono": time.monotonic()})
    except Exception:
        pass


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
        # Committed to distribution as flung (advanceTransport). The track can
        # outlive the commit by a few frames; it no longer holds the slot.
        self.ejected = False
        # When it was committed, and how often it has been pushed since because
        # it was still seen at the exit (see _LINGER_AFTER_EJECT_S).
        self.ejected_at: Optional[float] = None
        self.push_offs = 0
        # Two+ pieces landed in the drop zone at once -> can't classify reliably,
        # route to the misc bin. multi_drop_group ties the clump's distinct track
        # ids together as one logical multi-drop (None when not a multi-drop).
        self.double_feed = False
        self.multi_drop_group: Optional[int] = None
        # Recent (time, gap_to_exit) readings, to tell a tracker double of a
        # lost piece from another piece (see _successorFor).
        self.history: deque[tuple[float, float]] = deque(maxlen=90)
        # Where it was first seen, as gap_to_exit: where it landed, for a piece
        # the feeder dropped (see _LATE_ARRIVAL_MAX_GAP_DEG).
        self.first_gap: Optional[float] = None
        # Its box's area in each frame at rest in the drop zone, once settled
        # (see _GROW_FACTOR).
        self.rest_areas: list[float] = []
        # The detector's boxes inside its box this frame (one when it was not
        # merged), and in each frame at rest with rest_areas (see _APART_FRAC).
        self.boxes: tuple = ()
        self.rest_boxes: list[tuple] = []
        # Frames in a row it has shown this many separate boxes since it left
        # the drop zone (see _APART_LATER_FRAMES).
        self.apart_frames = 0
        self.apart_count = 0
        # It came apart only after distribution had committed it to its bin.
        self.committed_whole = False

    @property
    def known_object(self) -> Optional[KnownObject]:
        return self.worker.ctx.known_object

    def gapAt(self, t: float, within: float = 0.25) -> Optional[float]:
        best: Optional[tuple[float, float]] = None
        for at, gap in self.history:
            d = abs(at - t)
            if d <= within and (best is None or d < best[0]):
                best = (d, gap)
        return None if best is None else best[1]

    def where(self) -> str:
        return {
            _ZONE_DROP: "in the drop zone",
            _ZONE_EXIT: "at the exit",
            _ZONE_PRECISE: "waiting in the holding area",
        }.get(self.zone, "on its way from the drop zone to the holding area")


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
        # A pair seen landing in the drop zone (see _PAIR_DEG): until when a
        # piece that lands still joins it, and its multi_drop_group.
        self._pair_until = 0.0
        self._pair_group: Optional[int] = None
        # Eject cycles for which distribution must keep every door open because a
        # multi-drop piece we never routed is probably still on the platter. It
        # will fall the next time the channel turns, and we cannot see where it
        # is, so nothing may claim a bin until it is out. See _holdBucket().
        self._bucket_hold_cycles = 0
        # Each piece's trip through the channel, for "where the time goes".
        self._cycles = CycleRecorder()
        # Recent ejects, newest last: (monotonic time, part_id, color_id, uuid,
        # timed out). See _CIRCLING_WINDOW_S.
        self._recent_ejects: deque[tuple[float, str, str, str, bool]] = deque(maxlen=16)
        self._was_ready = False
        # When the channel last became ready for a piece (None while not ready).
        self._ready_since: Optional[float] = None
        # Pieces whose id vanished before they were ejected, kept for a new id
        # at their place to take over (see _RELINK_WINDOW_S): (piece, lost at).
        self._lost: list[tuple[_TrackedPiece, float]] = []
        # Last step, to notice a pause (see _RESUME_GAP_S), and the last time
        # the platter was seen turning.
        self._last_step_at: Optional[float] = None
        self._turned_at = 0.0
        # When the current turn (eject and/or stage) began: a late arrival is
        # an id that appeared after it (see _flagLateArrivals).
        self._rotation_started_at = 0.0
        self.ctx.reset()
        self.ctx.known_object = None

    # ------------------------------------------------------------- watchdog API

    def noteProgress(self) -> None:
        self.last_progress_at = time.monotonic()

    # ------------------------------------------------------- loose-piece safety

    def _holdBucket(self, reason: str, cycles: int = _BUCKET_HOLD_EJECTS) -> None:
        """Route everything to the bottom bucket for the next few ejects.

        A multi-drop's pieces touch, so the detector merges and re-ids them and we
        routinely lose one mid-channel. The piece is still on the platter and will
        drop off the exit on some later turn; with a layer door closed for whatever
        piece distribution is aiming at, it lands in that customer bin. We cannot
        see it any more, so we cannot time it — instead nothing claims a bin until
        it has had a few cycles to fall.
        """
        was = self._bucket_hold_cycles
        self._bucket_hold_cycles = max(was, int(cycles))
        self.shared.bucket_passthrough_hold = True
        if was <= 0:
            self.logger.warning(
                f"{LOG_TAG} {reason} — holding every layer door open for the next "
                f"{self._bucket_hold_cycles} ejects so it cannot land in a sorted bin"
            )

    def _releaseBucket(self, reason: str) -> None:
        if self._bucket_hold_cycles <= 0 and not getattr(
            self.shared, "bucket_passthrough_hold", False
        ):
            return
        self._bucket_hold_cycles = 0
        self.shared.bucket_passthrough_hold = False
        self.logger.info(f"{LOG_TAG} bucket hold released ({reason}) — normal routing resumes")

    def phaseName(self) -> str:
        # WAITING with the drop zone clear is the channel waiting on the feeder
        # for its next piece, which the runtime stats leave out of C4's active
        # time; named apart, a stall there also says what it waited on.
        if self._phase == _Phase.WAITING and self.shared.classification_ready:
            return C4_WAITING_FOR_PIECE
        return self._phase.value

    def attemptStallAutoClear(self, *, max_output_deg: float) -> ChannelClearResult:
        """Forced recovery for a wedged channel: rotate forward (occupancy-checked,
        blocking) until perception sees the channel empty or the budget runs out.

        The sweep opens every layer door first (``clearChannelByAdvancing``), so
        the whole channel — the piece the chute was aimed for plus anything else
        riding the platter — goes to the bottom bucket. Nothing here has been
        routed piece-by-piece, and letting an unrouted mixture drop into a
        customer's sorted bin is worse than losing it to the bucket. A placed
        head whose chute is already aimed is still committed to distribution
        first (so distribution doesn't wedge waiting for a drop that a forced
        rotation already performed), but its bin is cleared so the record says
        where it actually went. The rest have their in-flight objects abandoned,
        and anything still in distribution's slot is withdrawn."""
        placed = self._pendingPlacedPiece()
        if placed is not None and self._headReady(placed):
            obj = placed.known_object
            if obj is not None and obj.destination_bin is not None:
                self.logger.warning(
                    f"{LOG_TAG} stall auto-clear: placed head track={placed.track_id} was aimed at "
                    f"bin {obj.destination_bin}, but the sweep runs with the doors open — "
                    f"recording it as a bucket passthrough"
                )
                obj.destination_bin = None
                obj.updated_at = time.time()
            notePieceProblem(
                obj,
                "swept",
                "The classification channel stopped making progress, so the machine turned it "
                "with every door open to clear it; this piece went to the bucket, not its bin.",
            )
            self._commitToDistribution(placed)
            self.logger.info(
                f"{LOG_TAG} stall auto-clear: committed placed head "
                f"track={placed.track_id} to distribution"
            )
        result = clearChannelByAdvancing(
            self.gc,
            self.irl,
            self.irl_config,
            max_output_deg=max_output_deg,
            label=LOG_TAG,
        )
        if result.cleared:
            for tp in self._pieces.values():
                if tp.ejected:
                    continue  # the placed head, committed above with its note
                notePieceProblem(
                    tp.known_object,
                    "swept",
                    "The classification channel stopped making progress, so the machine turned "
                    "it with every door open to clear it; this piece went to the bucket.",
                )
                try:
                    tp.worker.abandonInFlightObject(
                        "stall auto-clear forced the piece off the channel"
                    )
                except Exception:
                    pass
            # A placed piece that was not committed above just fell wherever the
            # chute pointed. Leaving it in the slot kept distribution waiting for
            # its drop forever, and every later stall dumped the channel again.
            if self.transport.clearPieceForDistribution():
                self.logger.warning(
                    f"{LOG_TAG} stall auto-clear: withdrew the uncommitted placed piece from distribution"
                )
            self._pieces = {}
            self._lost = []
            self._eject_target = None
            self._stage_target = None
            self._multi_drop_streak = 0
            self._multi_drop_last_ts = -1.0
            self._cycles.drop()
            # The sweep ran with every door open and emptied the channel, so no
            # loose piece is left to protect the bins from.
            self._releaseBucket("stall auto-clear emptied the channel")
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
        # The first step of a new run counts too: the watchdog's clock started
        # when this was built, and a home before the first resume would read as
        # a stall and sweep the channel.
        if self._last_step_at is None or now - self._last_step_at > _RESUME_GAP_S:
            self._resumeAfterPause(now)
        self._last_step_at = now
        if not stopped:
            self._turned_at = now

        self._observe(state, now)

        # The classification channel OWNS the feeder admission gate. Ready only
        # when we are idle between cycles (not mid-rotation) AND the drop zone is
        # clear AND the platter has settled — i.e. "rotation complete, drop empty".
        ready = self._phase == _Phase.WAITING and (not state.in_drop) and stopped
        self.setClassificationReady(ready, "waiting + drop clear + stopped")
        if not ready:
            self._ready_since = None
        elif self._ready_since is None:
            self._ready_since = now
        self._recordCycle(perception_service, state, ready)

        # An empty channel proves nothing is left riding the platter, so any
        # loose-piece hold can end early rather than costing more sorted pieces.
        if self._bucket_hold_cycles > 0 and not self._pieces and not int(
            getattr(state, "n_pieces", 0) or 0
        ):
            self._releaseBucket("channel is empty")

        # Classification results arrive on background threads — apply them every
        # tick regardless of phase.
        self._applyResults(now)

        if self._phase == _Phase.WAITING:
            if stopped:
                self._captureDropPieces(perception_service, now)
                if self._pushOffLingeringEject(now):
                    return
                self._aimChuteForHead(now)
                self._maybeStartRotation()
        elif self._phase == _Phase.EJECTING:
            self._ejecting(state, stopped, now)
        elif self._phase == _Phase.STAGING:
            self._staging(state, stopped, now)

    def _recordCycle(self, perception_service, state, ready: bool) -> None:
        # Bookkeeping for "where the time goes": it must never stop the channel.
        try:
            self._recordCycleStep(perception_service, state, ready)
        except Exception as exc:
            if not getattr(self, "_cycle_error_logged", False):
                self._cycle_error_logged = True
                self.logger.warning(f"{LOG_TAG} cycle record failed (not recording cycles): {exc}")

    def _recordCycleStep(self, perception_service, state, ready: bool) -> None:
        wall = time.time()
        runtime_stats = getattr(self.gc, "runtime_stats", None)
        self._cycles.step(
            wall, held=runtime_stats is not None and runtime_stats.activeIncident() is not None
        )
        if ready and not self._was_ready:
            states = perception_service.read_states()
            self._cycles.asked(
                wall,
                states.get(3),
                states.get(2),
                self.shared.feeder_hidden_pieces.get(3, 0),
            )
        self._was_ready = ready
        if self._cycles.waiting:
            mono = time.monotonic()
            moving_until = self.shared.feeder_moving_until
            self._cycles.tick(
                wall,
                c3_moving=mono < moving_until.get(3, 0.0),
                c2_moving=mono < moving_until.get(2, 0.0),
                chute_moving=bool(self.shared.chute_move_in_progress),
            )
            if self._phase == _Phase.WAITING and state.in_drop:
                self._cycles.landed(wall)

    # ------------------------------------------------- perception reconciliation

    def _observe(self, state, now: float) -> None:
        """Match this frame's observations to tracked pieces by track id, create
        pieces for new ids, retire pieces whose id has been gone too long, and
        flag double feeds."""
        created: list[_TrackedPiece] = []
        merged = {
            tuple(int(v) for v in box): tuple(tuple(int(v) for v in b) for b in members)
            for box, members in getattr(state, "merged", ())
        }
        for po in getattr(state, "pieces", ()):
            tid = po.sv_bt_track_id
            if tid is None:
                continue  # untracked box — counts for zone occupancy, not identity
            tp = self._pieces.get(tid)
            if tp is None:
                tp = self._createPiece(tid, now)
                created.append(tp)
            tp.zone = int(po.zone_code)
            b = po.bbox
            tp.bbox = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
            tp.boxes = merged.get(tp.bbox, (tp.bbox,))
            tp.gap_to_exit = po.com_forward_to_exit_deg
            tp.last_seen = now
            # Watchdog progress: the piece physically moved a substantial amount.
            if tp.gap_to_exit is not None:
                gap = float(tp.gap_to_exit)
                tp.history.append((now, gap))
                if tp.first_gap is None:
                    tp.first_gap = gap
                if tp.progress_gap is None:
                    tp.progress_gap = gap
                elif abs(gap - tp.progress_gap) > _PROGRESS_MOVE_DEG:
                    tp.progress_gap = gap
                    self.noteProgress()

        for tp in created:
            self._adoptLost(tp, now)
        self._retireGonePieces(now)
        self._expireLost(now)
        self._flagLateArrivals(now)
        self._flagCloseLandings(state, now, created)
        self._flagDoubleFeeds(state)
        self._flagComingApart(now)

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
        obj = KnownObject(
            stage=PieceStage.created,
            classification_status=ClassificationStatus.pending,
            first_carousel_seen_ts=time.time(),
        )
        tp.worker.ctx.known_object = obj
        tp.worker.emitKnownObject()
        self.logger.info(f"{LOG_TAG} new piece track={tp.track_id} piece={obj.uuid}")
        _logC4Piece(tp.track_id, obj.uuid)

    def _retireGonePieces(self, now: float) -> None:
        for tid in [
            tid
            for tid, tp in self._pieces.items()
            if (now - tp.last_seen) > _TRACK_GONE_RETIRE_S
        ]:
            tp = self._pieces.pop(tid)
            keeps_going = tp.known_object is not None and not tp.ejected and tp is not self._eject_target
            if keeps_going:
                successor = self._successorFor(tp, now)
                if successor is not None:
                    self._handOver(tp, successor)
                    continue
            # A piece already handed to distribution has a terminal status, so
            # abandonInFlightObject is a no-op for it. Only an in-flight piece
            # (photographed but never classified/distributed) is dropped from the
            # UI — e.g. a stray that fell off before it could be processed.
            tp.worker.abandonInFlightObject("track id gone (left channel)")
            # Lost while placed but never ejected (a tracker re-id or a
            # detection gap): withdraw it so distribution stops waiting for its
            # drop. The eject target is left alone: a slow tick can retire it
            # here just before _ejecting commits it on this same tick.
            if (
                tp.placed
                and not tp.ejected
                and tp is not self._eject_target
                and self.transport.clearPieceForDistribution(tp.known_object)
            ):
                self.logger.warning(
                    f"{LOG_TAG} placed head track={tid} lost before eject; withdrew it from distribution"
                )
            # A multi-drop piece we never got to route is now somewhere on the
            # platter with no track to follow. Keep the doors open until it falls.
            if tp.double_feed and not tp.ejected and tp is not self._eject_target:
                self._holdBucket(f"multi-drop piece track={tid} lost before it was routed")
            # Watchdog progress: a REAL piece (one that became a UI object) left
            # the channel. Churn tracks (no KnownObject) get no credit, so id
            # flapping can't mask a wedge.
            if tp.known_object is not None:
                self.noteProgress()
            if keeps_going:
                # Withdrawn above if it was placed; a new id that turns up at its
                # place still gets it back (see _adoptLost).
                self._unplace(tp)
                self._lost.append((tp, now))
            self.logger.info(f"{LOG_TAG} retired piece track={tid}")

    def _unplace(self, tp: _TrackedPiece) -> None:
        """Distribution no longer holds this piece: it is placed again later and
        must wait for a fresh aim. Left 'distributing', it read as aimed the
        moment it was placed (distribution keeps its gate open while idle) and
        was ejected wherever the chute happened to point."""
        tp.placed = False
        obj = tp.known_object
        if obj is not None and obj.stage == PieceStage.distributing:
            obj.stage = PieceStage.created

    def _successorFor(self, lost: _TrackedPiece, now: float) -> Optional[_TrackedPiece]:
        """The id now standing where ``lost`` was: an id no one photographed,
        either seen on top of it while both existed (a tracker double), or new
        since and no further along than the channel can have carried it."""
        if lost.gap_to_exit is None:
            return None
        lost_gap = float(lost.gap_to_exit)
        turned = self._turned_at >= lost.last_seen
        best: Optional[_TrackedPiece] = None
        best_d = 0.0
        for cand in self._pieces.values():
            if cand is lost or cand.known_object is not None or cand.double_feed:
                continue
            if cand.gap_to_exit is None or now - cand.last_seen > 0.3:
                continue
            then = cand.gapAt(lost.last_seen)
            if then is not None:
                d = abs(then - lost_gap)
                if d > _SAME_PIECE_DEG:
                    continue  # it was somewhere else: another piece
            else:
                if cand.zone == _ZONE_DROP and lost.zone != _ZONE_DROP:
                    continue  # pieces never go back into the drop zone
                moved = lost_gap - float(cand.gap_to_exit)
                reach = _RELINK_TURNED_DEG if turned else _RELINK_STILL_DEG
                if moved < -_RELINK_STILL_DEG or moved > reach:
                    continue
                d = abs(moved)
            if best is None or d < best_d:
                best, best_d = cand, d
        return best

    def _handOver(self, lost: _TrackedPiece, successor: _TrackedPiece) -> None:
        """``successor``'s id takes over ``lost``: its photos, classification,
        record and place in the queue. The empty piece made for the new id goes."""
        old_tid = lost.track_id
        self._pieces.pop(successor.track_id, None)
        lost.track_id = successor.track_id
        lost.zone = successor.zone
        lost.bbox = successor.bbox
        lost.gap_to_exit = successor.gap_to_exit
        lost.last_seen = successor.last_seen
        lost.progress_gap = successor.progress_gap
        lost.history = successor.history
        self._pieces[lost.track_id] = lost
        obj = lost.known_object
        if obj is not None and obj.aborted:
            obj.aborted = False
            lost.worker.emitKnownObject()
        if obj is not None:
            _logC4Piece(lost.track_id, obj.uuid, took_over=old_tid)
        self.logger.info(
            f"{LOG_TAG} track={old_tid} lost; track={lost.track_id} at its place takes it over"
        )

    def _adoptLost(self, tp: _TrackedPiece, now: float) -> None:
        """A new id may be a lost piece seen again (see _RELINK_WINDOW_S)."""
        for i, (lost, _at) in enumerate(self._lost):
            if self._successorFor(lost, now) is tp:
                del self._lost[i]
                self._handOver(lost, tp)
                return

    def _expireLost(self, now: float) -> None:
        keep: list[tuple[_TrackedPiece, float]] = []
        for lost, at in self._lost:
            if now - at <= _RELINK_WINDOW_S:
                keep.append((lost, at))
                continue
            obj = lost.known_object
            notePieceProblem(
                obj,
                "track_lost",
                f"The camera lost track of it {at - lost.created_at:.1f} s after it came onto the "
                f"channel, while it was {lost.where()}, and nothing at its place picked it up again "
                f"within {_RELINK_WINDOW_S:.0f} s, so where it went is not known and no bin counts it.",
                after_s=at - lost.created_at,
            )
            if obj is not None:
                lost.worker.emitKnownObject()
        self._lost = keep

    def _flagLateArrivals(self, now: float) -> None:
        """A piece that lands while the channel turns the last one off the drop
        zone (see _LATE_ARRIVAL_CONFIRM_S) can't be photographed alone and may
        ride close behind that one: both go to misc as a double feed."""
        if self._phase not in (_Phase.STAGING, _Phase.EJECTING):
            return
        first = self._stage_target
        if first is None or first.last_seen != now or first.gap_to_exit is None:
            return
        for tp in list(self._pieces.values()):
            if tp is first or tp.double_feed or tp.known_object is not None:
                continue
            if tp.zone != _ZONE_DROP or tp.last_seen != now or tp.gap_to_exit is None:
                continue
            if tp.created_at < self._rotation_started_at:
                continue  # there before this turn began (one that landed while paused)
            if now - tp.created_at < _LATE_ARRIVAL_CONFIRM_S:
                continue
            if abs(float(tp.gap_to_exit) - float(first.gap_to_exit)) <= _SAME_PIECE_DEG:
                continue  # a tracker double of the piece being staged
            if tp.first_gap is None or first.first_gap is None:
                continue
            if tp.first_gap > min(first.first_gap + _LATE_LANDING_SLACK_DEG, _LATE_ARRIVAL_MAX_GAP_DEG):
                continue  # came around from past the exit, not from the feeder
            group = first.multi_drop_group
            if group is None:
                self._multi_drop_seq += 1
                group = self._multi_drop_seq
            behind = now - first.created_at
            if not first.double_feed:
                self._markDoubleFeed(
                    first,
                    group,
                    "late_double_feed",
                    f"A second piece came onto the channel {behind:.1f} s after this one, while "
                    f"this one was being turned off the drop zone, so the two could not be told "
                    f"apart; both went to misc as a double feed.",
                )
            self._markDoubleFeed(
                tp,
                group,
                "late_double_feed",
                f"Came onto the channel {behind:.1f} s after the piece before it, while that one "
                f"was being turned off the drop zone (the feeder had not asked for a piece), so it "
                f"was never photographed alone; both went to misc as a double feed.",
            )

    def _flagCloseLandings(self, state, now: float, created: list) -> None:
        """Two pieces seen landing side by side, for even one frame, while the
        channel stands still (see _PAIR_DEG)."""
        stepper = getattr(self.irl, "carousel_stepper", None)
        if self._phase != _Phase.WAITING or not bool(getattr(stepper, "stopped", True)):
            # Sizes are only compared at rest: a turn shows a piece from a new
            # angle, so its readings start over.
            for tp in self._pieces.values():
                tp.rest_areas.clear()
                tp.rest_boxes.clear()
            return
        drop = [
            po
            for po in getattr(state, "pieces", ())
            if int(po.zone_code) == _ZONE_DROP and po.com_forward_to_exit_deg is not None
        ]
        pair = _closePair(drop)
        if pair is not None:
            if now > self._pair_until or self._pair_group is None:
                self._multi_drop_seq += 1
                self._pair_group = self._multi_drop_seq
            self._pair_until = now + _PAIR_FOLLOW_S
            gaps = [float(po.com_forward_to_exit_deg) for po in pair]
            for tp in list(self._pieces.values()):
                if tp.zone != _ZONE_DROP or tp.double_feed or tp.gap_to_exit is None:
                    continue
                if min(abs(float(tp.gap_to_exit) - g) for g in gaps) <= _PAIR_DEG:
                    self._markCloseLanding(tp)
        elif now <= self._pair_until:
            for tp in created:
                if tp.zone == _ZONE_DROP and not tp.double_feed:
                    self._markCloseLanding(tp)
        for tp in list(self._pieces.values()):
            if tp.zone != _ZONE_DROP or tp.double_feed or tp.last_seen != now:
                continue
            if now - tp.created_at < _GROW_SETTLE_S:
                continue
            b = tp.bbox
            tp.rest_areas.append(max(0.0, float(b[2] - b[0])) * max(0.0, float(b[3] - b[1])))
            tp.rest_boxes.append(tp.boxes)
            if len(tp.rest_areas) <= 3:
                continue
            settled = sorted(tp.rest_areas[:3])[1]
            settled_boxes = sorted(len(boxes) for boxes in tp.rest_boxes[:3])[1]
            # A second piece shows up as a box of its own inside the merged box. A
            # piece that tips over as it settles (a wheel landing on its edge,
            # then falling flat) grows with no new box: that is no double feed.
            grown = [
                a
                for a, boxes in zip(tp.rest_areas[3:], tp.rest_boxes[3:])
                if settled > 0 and a >= _GROW_FACTOR * settled and len(boxes) > settled_boxes
            ]
            if len(grown) >= _GROW_FRAMES:
                if self._pair_group is None or now > self._pair_until:
                    self._multi_drop_seq += 1
                    self._pair_group = self._multi_drop_seq
                self._markDoubleFeed(
                    tp,
                    self._pair_group,
                    "double_feed",
                    f"Another piece landed against it while it sat in the drop zone (its box "
                    f"grew to {max(grown) / settled:.1f} times its size), so it could not be "
                    f"photographed alone; it went to misc as a double feed.",
                )

    def _landedTouching(self, tp: _TrackedPiece) -> bool:
        """Its boxes at rest were two pieces' (see _APART_FRAC)."""
        frames = tp.rest_boxes
        if len(frames) < _APART_MIN_FRAMES:
            return False
        apart = sum(1 for boxes in frames if _apart(boxes))
        steady = max(Counter(len(boxes) for boxes in frames).values())
        return apart >= _APART_FRAC * len(frames) and steady >= _STEADY_FRAC * len(frames)

    def _flagComingApart(self, now: float) -> None:
        """A piece taken for one that shows itself to be two after it left the
        drop zone (see _APART_LATER_FRAMES) goes to misc after all."""
        for tp in list(self._pieces.values()):
            if (
                tp.double_feed
                or tp.committed_whole
                or tp.ejected
                or tp is self._eject_target
                or not tp.capture_done
                or tp.zone == _ZONE_DROP
                or tp.last_seen != now
            ):
                continue
            if _apart(tp.boxes):
                if len(tp.boxes) == tp.apart_count:
                    tp.apart_frames += 1
                else:
                    tp.apart_count, tp.apart_frames = len(tp.boxes), 1
            else:
                tp.apart_frames = 0
            if tp.apart_frames >= _APART_LATER_FRAMES:
                self._reviseToDoubleFeed(
                    tp,
                    None,
                    "Taken for one piece at rest, but once it moved the camera saw two separate "
                    "pieces in its place, so it went to misc as a double feed.",
                )
                continue
            if tp.gap_to_exit is None:
                continue
            for other in list(self._pieces.values()):
                if (
                    other is tp
                    or other.known_object is not None
                    or other.double_feed
                    or other.zone == _ZONE_DROP
                    or other.last_seen != now
                    or other.gap_to_exit is None
                    or now - other.created_at < _SPLIT_CONFIRM_S
                ):
                    continue
                apart_deg = abs(float(other.gap_to_exit) - float(tp.gap_to_exit))
                if _SAME_PIECE_DEG < apart_deg <= _SPLIT_DEG:
                    group = self._reviseToDoubleFeed(
                        tp,
                        None,
                        "Taken for one piece at rest, but after it moved a second piece showed up "
                        "beside it (they came apart, or one landed against it), so it went to misc "
                        "as a double feed.",
                    )
                    if group is None:
                        break
                    self._markDoubleFeed(
                        other,
                        group,
                        "double_feed",
                        "Showed up beside a piece that had been taken for one, so it went to "
                        "misc with it as a double feed.",
                    )
                    break

    def _reviseToDoubleFeed(
        self, tp: _TrackedPiece, group: Optional[int], message: str
    ) -> Optional[int]:
        """Make a piece that was taken for one a double feed. If the chute was
        already aimed for its bin it is withdrawn, and placed again for misc;
        one distribution has already committed to dropping keeps its bin."""
        if tp.placed:
            if not self.transport.clearPieceForDistribution(tp.known_object):
                tp.committed_whole = True
                self.logger.warning(
                    f"{LOG_TAG} track={tp.track_id} looks like two pieces, but distribution has "
                    f"already committed it to its bin"
                )
                return None
            self._unplace(tp)
        if group is None:
            self._multi_drop_seq += 1
            group = self._multi_drop_seq
        self._markDoubleFeed(tp, group, "double_feed", message)
        return group

    def _markCloseLanding(self, tp: _TrackedPiece) -> None:
        self._markDoubleFeed(
            tp,
            self._pair_group if self._pair_group is not None else 0,
            "double_feed",
            "Landed touching another piece: the camera saw two pieces side by side "
            "before it took them for one, so it could not be photographed alone; it "
            "went to misc as a double feed.",
        )

    def _flagDoubleFeeds(self, state) -> None:
        # Only pieces seen in this frame count. A piece that bounces as it lands
        # often settles under a new track id, and its old id stays here (last
        # seen in the drop zone) until it retires; counting that read one piece
        # as two and sent it to misc.
        seen = {po.sv_bt_track_id for po in getattr(state, "pieces", ())}
        drop = [
            tp
            for tp in self._pieces.values()
            if tp.zone == _ZONE_DROP and tp.track_id in seen
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

    def _markDoubleFeed(
        self,
        tp: _TrackedPiece,
        group: int,
        kind: str = "double_feed",
        message: str = (
            "Landed on the channel together with another piece, so it could not be "
            "photographed alone; it went to misc as a double feed."
        ),
    ) -> None:
        # Two+ pieces in the drop zone at once: classification can't be trusted, so
        # skip it and route the piece to the misc bin. It still rides the normal
        # bucket-brigade (staged, then ejected) — just to misc. All members of the
        # clump share one multi_drop_group so they read as a single multi-drop.
        tp.double_feed = True
        tp.multi_drop_group = group
        tp.capture_done = True
        self._cycles.multiDrop()
        tp.result_applied = True
        self.noteProgress()
        self._ensureKnownObject(tp)
        obj = tp.known_object
        if obj is not None:
            obj.classification_status = ClassificationStatus.multi_drop_fail
            obj.part_id = None
            notePieceProblem(obj, kind, message)
            tp.worker.emitKnownObject()
        self.logger.warning(
            f"{LOG_TAG} double feed -> misc (track={tp.track_id}, group={group})"
        )

    # --------------------------------------------------- ordered-queue accessors

    def _pendingPlacedPiece(self) -> Optional[_TrackedPiece]:
        # The piece currently holding distribution's single slot, if still tracked.
        return next(
            (tp for tp in self._pieces.values() if tp.placed and not tp.ejected), None
        )

    def _headPiece(self) -> Optional[_TrackedPiece]:
        # The head of the queue: the most-forward piece that has LEFT the drop zone
        # (in precise, the exit approach, or the unnamed gap between drop and
        # precise). This is the piece we classify-aim and eject next. Including the
        # gap (zone NONE) is what keeps a clump piece that overshot precise, or a
        # stray that landed mid-channel, from being stranded.
        #
        # Once a piece is placed it stays the head until ejected or lost, even if
        # another track reads as further forward (a tracker re-id, a phantom, or
        # two touching pieces trading places by a few degrees). Switching heads
        # re-placed a different piece over the slot: distribution saw a drop that
        # never happened and ended up aimed for the wrong piece.
        pending = self._pendingPlacedPiece()
        if pending is not None and pending.zone != _ZONE_DROP:
            return pending
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
            if tp.last_seen != now:
                # Not in this frame: its box is where it was, and a crop of it now
                # may be empty platter.
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
                obj = tp.known_object
                self._cycles.confirmed(time.time(), tp.track_id, obj.uuid if obj is not None else None)
            self._cropBurstFrame(tp.worker, tp.bbox, perc_frame)
            done, reason = tp.worker.burstCaptureComplete(ctx, now)
            if done and self._landedTouching(tp):
                self._multi_drop_seq += 1
                self._markDoubleFeed(
                    tp,
                    self._multi_drop_seq,
                    "double_feed",
                    "Two pieces lay touching in the drop zone: the camera saw the same separate "
                    "pieces in its box the whole time it was photographed, so it went to misc as "
                    "a double feed.",
                )
                continue
            if done:
                tp.capture_done = True
                self._cycles.captured(time.time(), tp.track_id)
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
                self._checkCircling(tp)
            elif (now - ctx.classify_started_at) > ctx.config.classify_timeout_s:
                self.logger.error(f"{LOG_TAG} classify timeout track={tp.track_id} -> unknown")
                notePieceProblem(
                    tp.known_object,
                    "classify_failed",
                    f"Identification did not answer within {ctx.config.classify_timeout_s:.0f} s "
                    f"of the photos being taken, so it went to misc unidentified.",
                    after_s=now - ctx.classify_started_at,
                )
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
        if self._pendingPlacedPiece() is not None:
            # The slot still belongs to a placed piece that has not been ejected.
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
                    notePieceProblem(
                        obj0,
                        "stray",
                        f"The camera first saw it {tp.where()}, not landing in the drop zone, so it "
                        f"was never photographed or identified; it went to misc.",
                    )
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
            and not tp.ejected
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
            self._maybeEjectHeadAlone()
            return
        head = self._headPiece()
        if head is None:
            self._stage_target = drop
            self._eject_target = None
            self._enterPhase(_Phase.STAGING)
            self._rotation_started_at = time.monotonic()
            self._cycles.rotated(time.time(), ejecting=False)
            self.logger.info(f"{LOG_TAG} ROTATE: stage track={drop.track_id} (no head)")
        elif self._headReady(head):
            self._stage_target = drop
            self._eject_target = head
            self._enterPhase(_Phase.EJECTING)
            self._rotation_started_at = time.monotonic()
            self._cycles.rotated(time.time(), ejecting=True)
            self.logger.info(
                f"{LOG_TAG} ROTATE: eject track={head.track_id} + stage track={drop.track_id}"
            )

    def _maybeEjectHeadAlone(self) -> None:
        # Counted from when the feeder was let in, or, while its gate stays shut
        # with no piece to photograph, from when the channel stopped: a piece
        # left straddling the drop zone's edge (its centre out, its box in)
        # reads as an occupied drop zone, so no next piece could ever come and
        # only the stall watchdog's sweep moved the channel on.
        since = self._ready_since if self._ready_since is not None else self._phase_started_at
        if time.monotonic() - since < _HEAD_ALONE_AFTER_S:
            return
        head = self._headPiece()
        if head is None or not self._headReady(head):
            return
        self._stage_target = None
        self._eject_target = head
        self._enterPhase(_Phase.EJECTING)
        self.logger.info(
            f"{LOG_TAG} ROTATE: eject track={head.track_id} alone "
            f"(no next piece for {_HEAD_ALONE_AFTER_S:.0f} s)"
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
            self._rememberEject(target, timed_out=gone_for < _EJECT_GONE_CONFIRM_S)
            self._commitToDistribution(target)
            self._cycles.ejected(time.time())
            if self._bucket_hold_cycles > 0:
                self._bucket_hold_cycles -= 1
                if self._bucket_hold_cycles == 0:
                    self._releaseBucket("loose piece has had its cycles to fall")
            if timed_out and gone_for < _EJECT_GONE_CONFIRM_S:
                self.logger.warning(
                    f"{LOG_TAG} EJECT timeout track={target.track_id} — committing anyway"
                )
                notePieceProblem(
                    target.known_object,
                    "eject_timeout",
                    f"It was still on the channel {_EJECT_TIMEOUT_S:.0f} s after the turn meant to "
                    f"drop it into its bin; it was counted as dropped anyway.",
                    after_s=now - self._phase_started_at,
                )
            else:
                self.logger.info(f"{LOG_TAG} ejected track={target.track_id} (id gone)")
            self._eject_target = None
            self._enterPhase(_Phase.STAGING)
            return
        if gone_for > 0.0:
            return  # id missing (likely just dropped) — stop pushing, let it confirm
        if stopped:
            # The target's own gap to the middle of the fall-off. The channel's
            # reading is for its most forward piece, which can be another one
            # when the target blinks in a frame; a move sized for that one threw
            # a waiting piece off into the bin aimed for the target. Piece gaps
            # run to the fall-off's near edge, the channel's to its middle.
            gap = state.exit_com_forward_to_center_deg
            pieces = getattr(state, "pieces", ())
            if gap is not None and pieces and target.gap_to_exit is not None:
                to_middle = float(gap) - float(pieces[0].com_forward_to_exit_deg)
                gap = float(target.gap_to_exit) + to_middle
            if gap is not None and gap > self.ctx.config.discharge_center_tolerance_deg:
                # One move for the whole cycle: far enough to drop the head, and
                # to bring the piece being staged to the holding band, so the
                # staging that follows has nothing left to do — short of bringing
                # a piece waiting behind the head up to the exit.
                move = max(gap, self._stageGap())
                move = min(self.ctx.config.discharge_max_move_output_deg, move)
                limit = self._keepOnLimit(exclude=target)
                if limit is not None:
                    move = max(gap, min(move, limit))
                self.startOutputMove(
                    C4_TRAVEL_SIGN * move, self.ctx.config.discharge_speed_usteps_per_s
                )

    def _keepOnLimit(self, exclude: Optional[_TrackedPiece] = None) -> Optional[float]:
        """How far the channel may turn before a waiting piece comes closer than
        _KEEP_ON_MIN_GAP_DEG to the exit (None when no piece limits it). Ids on
        top of or ahead of ``exclude`` (the piece being ejected) go with it."""
        ex_gap = exclude.gap_to_exit if exclude is not None else None
        limit: Optional[float] = None
        for tp in self._pieces.values():
            if tp is exclude or tp.ejected or tp.zone == _ZONE_DROP or tp.gap_to_exit is None:
                continue
            gap = float(tp.gap_to_exit)
            if ex_gap is not None and gap <= float(ex_gap) + _SAME_PIECE_DEG:
                continue
            room = gap - _KEEP_ON_MIN_GAP_DEG
            limit = room if limit is None else min(limit, room)
        return limit

    def _stageGap(self) -> float:
        """How far the piece being staged is from the start of the holding band
        (the precise zone); 0 when unknown."""
        target = self._stage_target
        if target is None or target.gap_to_exit is None:
            return 0.0
        perception_service = getattr(self.gc, "perception_service", None)
        channels = perception_service.channels() if perception_service is not None else {}
        channel = channels.get(4)
        if channel is None or not channel.precise_sections:
            return 0.0
        from perception.channel import SECTION_DEG

        return max(0.0, float(target.gap_to_exit) - len(channel.precise_sections) * SECTION_DEG)

    def _staging(self, state, stopped: bool, now: float) -> None:
        # Advance the platter until the DROP ZONE IS CLEAR — i.e. the new piece and
        # any multi-drop siblings have all left the drop zone (into the holding
        # area). Keying on "drop clear" rather than "one chosen piece reached
        # precise" is what moves a clump through together instead of stranding the
        # trailing piece.
        if (now - self._phase_started_at) > _STAGE_TIMEOUT_S:
            self.logger.warning(f"{LOG_TAG} STAGE timeout — giving up")
            self._cycles.staged(time.time(), note="stage timeout")
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
            if self._stage_target is not None:
                # A head ejected alone staged nothing: the wait for the next
                # piece goes on in the same cycle record.
                self._cycles.staged(time.time())
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
        # Clearing the drop zone must not push the piece waiting for the chute
        # off the exit before its bin is aimed. When there is no room left, the
        # cycle goes on from WAITING: that piece is aimed and ejected, and the
        # rest of the clump staged with that turn.
        limit = self._keepOnLimit()
        if limit is not None and limit < move:
            if limit < 3.0:
                self.logger.info(
                    f"{LOG_TAG} staging stops short: turning on would bring a waiting piece "
                    f"to the exit before its chute is aimed"
                )
                if self._stage_target is not None:
                    self._cycles.staged(time.time(), note="stopped short of the exit")
                self._stage_target = None
                self._enterPhase(_Phase.WAITING)
                return
            move = limit
        self.startOutputMove(
            C4_TRAVEL_SIGN * move, self.ctx.config.precise_converge_speed_usteps_per_s
        )

    def _pushOffLingeringEject(self, now: float) -> bool:
        """Push off a piece that was committed as ejected but still sits at the
        exit (see _LINGER_AFTER_EJECT_S). True when a push was started."""
        if self._pendingPlacedPiece() is not None:
            # The chute is aimed for another piece now: a push would drop the
            # lingering one into that piece's bin.
            return False
        for tp in self._pieces.values():
            if not tp.ejected or tp.ejected_at is None or tp.push_offs >= _PUSH_OFF_TRIES:
                continue
            if tp.last_seen != now or now - tp.ejected_at < _LINGER_AFTER_EJECT_S:
                continue
            if tp.zone != _ZONE_EXIT:
                continue
            tp.push_offs += 1
            notePieceProblem(
                tp.known_object,
                "pushed_off",
                f"It was still at the exit {now - tp.ejected_at:.1f} s after it should have dropped, "
                f"so the channel turned {_PUSH_OFF_DEG:.0f}° to push it off "
                f"(try {tp.push_offs} of {_PUSH_OFF_TRIES}).",
                after_s=now - tp.ejected_at,
            )
            tp.ejected_at = now
            self.logger.warning(
                f"{LOG_TAG} track={tp.track_id} was ejected but is still at the exit "
                f"(gap {tp.gap_to_exit if tp.gap_to_exit is None else round(tp.gap_to_exit)} deg): "
                f"pushing it off, try {tp.push_offs} of {_PUSH_OFF_TRIES}"
            )
            self.startOutputMove(
                C4_TRAVEL_SIGN * _PUSH_OFF_DEG, self.ctx.config.discharge_speed_usteps_per_s
            )
            return True
        return False

    def _rememberEject(self, tp: _TrackedPiece, *, timed_out: bool) -> None:
        obj = tp.known_object
        if obj is None or obj.part_id is None:
            return
        self._recent_ejects.append(
            (time.monotonic(), str(obj.part_id), str(obj.color_id), str(obj.uuid), timed_out)
        )

    def _checkCircling(self, tp: _TrackedPiece) -> None:
        """The piece just classified is one that was ejected moments ago and came
        back around (see _CIRCLING_WINDOW_S): keep it out of the counts, since its
        first record already counts it, and hold the machine for the operator."""
        obj = tp.known_object
        if obj is None or obj.part_id is None or obj.classification_status != ClassificationStatus.classified:
            return
        now = time.monotonic()
        name = f"{obj.part_name or ''} {obj.part_category or ''}".lower()
        rolls = any(word in name for word in _ROLLING_WORDS)
        for at, part_id, color_id, uuid, timed_out in reversed(self._recent_ejects):
            if now - at > _CIRCLING_WINDOW_S:
                return
            if part_id != str(obj.part_id) or color_id != str(obj.color_id):
                continue
            if not (rolls or timed_out):
                continue
            ago = now - at
            obj.dead = True
            obj.updated_at = time.time()
            notePieceProblem(
                obj,
                "circling",
                f"Came back around the channel {ago:.0f} s after the same part in the same color "
                f"was dropped{' (that drop was never seen happening)' if timed_out else ''}: one "
                f"piece seen twice, so this record is not counted and the machine stopped for it.",
                after_s=ago,
            )
            tp.worker.emitKnownObject()
            self.logger.warning(
                f"{LOG_TAG} track={tp.track_id} is {obj.part_id} ({obj.color_id}) again, "
                f"{ago:.1f} s after piece {uuid} was ejected"
                f"{' on a timeout' if timed_out else ''}: it came back around; "
                f"not counted again, holding for the operator"
            )
            incidents.report(
                self.gc,
                PIECE_CIRCLING_INCIDENT_KIND,
                subject="C4",
                source="c4_circling",
                severity="critical",
                status="waiting_for_operator",
                awaiting_operator=True,
                scope="classification",
                channel="c4",
                role="classification_channel",
                channel_label="C4",
                piece_uuid=obj.uuid,
                track_id=tp.track_id,
                first_piece_uuid=uuid,
                part_id=obj.part_id,
                color_id=obj.color_id,
                seconds_after_eject=round(ago, 1),
                eject_timed_out=timed_out,
                rule="same_part_and_colour_classified_again_after_eject",
                reason=f"{obj.part_name or obj.part_id} came back around {ago:.0f} s after it was ejected",
                operator_message=(
                    "A piece is going around the classification channel instead of falling off. "
                    "Take it off, then press Done."
                ),
            )
            try:
                import control_data_store

                control_data_store.record(
                    {
                        "type": "event",
                        "kind": "piece_circling",
                        "track": tp.track_id,
                        "piece": obj.uuid,
                        "first_piece": uuid,
                        "part": obj.part_id,
                        "color": obj.color_id,
                        "after_s": round(ago, 2),
                        "eject_timed_out": timed_out,
                        "t": time.time(),
                        "mono": now,
                    }
                )
            except Exception:
                pass
            return

    def _commitToDistribution(self, tp: _TrackedPiece) -> None:
        # The placed piece leaves the platter into the chute: move it to
        # distribution's drop slot and count it as a C4 exit.
        self.transport.advanceTransport()
        tp.ejected = True
        tp.ejected_at = time.monotonic()
        self.gc.runtime_stats.observeC4Exit()

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
        crop = self.cropBbox(perc_frame.bgr, bbox, ctx.config.crop_padding_px)
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

    def pause(self) -> None:
        """The machine paused, or stopped for a jam elsewhere. Every piece keeps
        its photos and classification, so on resume it goes where it was going
        instead of to misc as a piece nobody photographed. Distribution forgets
        its slot on a pause, so a placed piece is withdrawn and placed again
        when the flow runs; a turn that was under way is planned afresh."""
        self.transport.clearPieceForDistribution()
        for tp in self._pieces.values():
            if tp.placed and not tp.ejected:
                self._unplace(tp)
        self._enterPhase(_Phase.WAITING)
        self._eject_target = None
        self._stage_target = None
        self._multi_drop_streak = 0
        self._multi_drop_last_ts = -1.0
        self._cycles.drop()
        self._was_ready = False
        self._ready_since = None
        self.last_progress_at = time.monotonic()

    def _resumeAfterPause(self, now: float) -> None:
        """First step after a pause or an incident hold. The pieces sat still,
        so each gets the usual window to be seen again, is refreshed so the
        stuck-piece reaper does not count the pause, and the watchdog's window
        starts now."""
        for tp in self._pieces.values():
            tp.last_seen = now
            if tp.ejected_at is not None:
                tp.ejected_at = now
            if tp.known_object is None:
                # An id nobody photographed may be a piece's new id from
                # during the stop: give the hand-over its window before the
                # stray rule (_STRAY_MISC_S) sends it to misc.
                tp.created_at = now
            if tp.known_object is not None:
                tp.worker.emitKnownObject()
        self._lost = [(tp, now) for tp, _at in self._lost]
        self._ready_since = None
        self.last_progress_at = now
        self.logger.info(
            f"{LOG_TAG} resumed with {len(self._pieces)} piece(s) on the channel, "
            f"keeping what they were classified as"
        )

    def cleanup(self) -> None:
        for tp in self._pieces.values():
            try:
                tp.worker.abandonInFlightObject("two-piece classification channel teardown")
            except Exception:
                pass
        # Every tracked piece is forgotten, so a placed one would never be ejected;
        # withdraw it rather than leave distribution aimed and waiting after resume.
        self.transport.clearPieceForDistribution()
        self._pieces = {}
        self._lost = []
        self._last_step_at = None
        self._phase = _Phase.WAITING
        self._eject_target = None
        self._stage_target = None
        self._multi_drop_streak = 0
        self._multi_drop_last_ts = -1.0
        self._cycles.drop()
        self._was_ready = False
        # The hold lives in the counter on this object, which a teardown resets;
        # leaving the shared flag set would strand distribution in bucket mode
        # with nothing left to decrement it. Release it with the rest of the state.
        self._releaseBucket("classification channel teardown")
        # Fresh watchdog window on the next start — a pause must not count
        # toward "stalled".
        self.last_progress_at = time.monotonic()
        self.ctx.reset()
        self.ctx.known_object = None
