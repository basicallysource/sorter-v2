"""Per-channel perception state — what the coordinator reads.

The slot stores booleans, not bboxes. Region attribution happens on the
inference thread; the coordinator gets a finished verdict. Single-ref
atomic write keeps the slot lock-free.
"""

from __future__ import annotations

from dataclasses import dataclass


EMPTY_STATE_TS = 0.0


@dataclass(frozen=True)
class PieceObservation:
    """One on-channel piece as seen THIS frame, ordered leading-first in
    ``ChannelState.pieces``.

    The multi-piece holding flow reasons about pieces by travel position + which
    zone their centre sits in — NOT by cross-frame identity. ``sv_bt_track_id``
    adds an advisory stable id (perception ByteTrack — see
    ``perception.tracking``) for diagnostics, the stream overlay, and any future
    identity-aware consumer, but the control flow does not depend on it."""

    # Signed travel-direction gap (channel-output degrees) from this piece's COM
    # to the entry edge of the REAL exit (exit-only) arc — same quantity and sign
    # convention as ``ChannelState.exit_com_forward_deg`` but per piece. > 0 = the
    # COM is short of the exit by this much; <= 0 = the COM has crossed the entry
    # edge. Smaller = more forward, so ``pieces[0]`` is the leading piece.
    com_forward_to_exit_deg: float
    com_section: int
    # Region the COM section sits in, matching ``perception.arcs._region_lookup``:
    # 0 = none (between named zones), 1 = drop, 2 = exit_only, 3 = precise. Extends
    # with additional codes when holding bands are added to the region LUT.
    zone_code: int
    # This piece's bbox (x1, y1, x2, y2) in frame pixels — lets a consumer crop the
    # specific piece in a given zone (e.g. capture the DROP-zone piece while another
    # piece sits in precise), without re-deriving which bbox is which.
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)
    # Advisory stable identity from the perception ByteTrack tracker: the same
    # physical piece keeps one id frame-to-frame as it slides down the channel,
    # surviving brief detector dropouts. ``None`` when tracking is unavailable or
    # the box is not yet a confirmed track. Not used by control logic (see class
    # docstring) — diagnostics / overlay / future identity-aware consumers only.
    sv_bt_track_id: int | None = None


@dataclass(frozen=True)
class ChannelState:
    """The only thing the coordinator reads per channel.

    `ts == EMPTY_STATE_TS` means the slot has never been written (the
    inference worker has not produced its first frame yet) — treat as
    "no information."
    """

    ts: float
    in_drop: bool
    in_exit: bool
    n_pieces: int
    # True when at least one on-channel piece is in the precise sub-arc of the
    # exit zone. ``in_exit`` (the union of exit + precise) stays the trigger for
    # the cascade's PRECISE pulse; ``in_precise`` lets callers ask the narrower
    # "is this piece specifically in the precise zone" question.
    in_precise: bool = False
    # True when at least one on-channel piece has strictly more bbox sample
    # points in the exit-only sub-arc than in the precise arc — i.e. the piece
    # is "majority in the exit zone, not the precise zone." Jitter unstick uses
    # this as its trigger so a piece straddling the exit/precise boundary still
    # starts the dwell timer once it is mostly past the precise zone.
    in_exit_majority: bool = False
    # Forward distance (output degrees) from the most-forward on-channel piece
    # to the near edge of the exit zone — the largest advance possible without
    # pushing a piece into the exit zone. ``None`` when there is no on-channel
    # piece or the channel has no exit arc. The cascade's ADVANCE caps its move
    # to this so a free drop-zone advance never shoves a leading piece through
    # the exit, bypassing the downstream-gated exit handling.
    advance_clearance_deg: float | None = None
    # Signed forward distance (channel-output degrees) from the LEADING on-channel
    # piece's bbox center-of-mass to the entry edge of the REAL exit region
    # (the exit arc MINUS the precise arc — see ``arcs.exitOnlySections``; the
    # precise zone is a separate band the piece crosses first and must NOT trip
    # the eject). > 0 means the COM is still that many degrees SHORT of the exit
    # zone (advance it forward this much); <= 0 means the COM has crossed the
    # entry edge, i.e. the piece is >= 50% into the exit region (COM = centroid).
    # ``None`` when there is no on-channel piece or the channel has no exit arc.
    # The eject controller drives this toward 0 in a closed loop, re-reading it
    # after every move so piece slippage just costs extra iterations.
    exit_com_forward_deg: float | None = None
    # Signed forward distance (output degrees) from the LEADING piece's COM to the
    # CENTER of the exit-only (fall-off) arc, not its near edge — see
    # ``arcs.exitComForwardToCenterDeg``. The C4 closed-loop discharge drives this
    # toward 0 so a piece parks in the MIDDLE of the fall-off zone rather than on
    # its leading lip. Same None semantics as ``exit_com_forward_deg``.
    exit_com_forward_to_center_deg: float | None = None
    # Signed travel-direction distance (output degrees) from the LEADING piece's
    # COM to the BEGINNING (entry edge) of the PRECISE (staging) arc — see
    # ``arcs.comForwardToPreciseEntryDeg``. The C4 reverse flow drives this toward
    # 0 in MOVING_TO_PRECISE to park the piece at the START of the precise band
    # (not its centre, which overshot) before the fall-off. Same None semantics as
    # ``exit_com_forward_to_center_deg``.
    exit_com_forward_to_precise_deg: float | None = None
    # True when the LEADING piece's COM section lies in the PRECISE zone. This is
    # the exact trigger for starting a C3 eject — the piece must actually be in
    # the precise (staging) band, not merely within some distance of the exit.
    exit_com_in_precise: bool = False
    # Every on-channel piece this frame, ordered leading-first (ascending
    # com_forward_to_exit_deg). Empty when there is no on-channel piece or the
    # channel has no exit arc. The single-leading ``exit_com_*`` fields above are
    # ``pieces[0]``; this additionally exposes the TRAILING pieces a multi-piece
    # holding flow needs to tell apart the piece staged for discharge from the one
    # still being classified in the drop zone. No cross-frame identity — reason by
    # position + zone, not tracking.
    pieces: tuple[PieceObservation, ...] = ()


EMPTY_STATE = ChannelState(ts=EMPTY_STATE_TS, in_drop=False, in_exit=False, n_pieces=0)


class LatestStateSlot:
    """Single atomic-ref slot. Producer overwrites, consumers read whatever
    the most recent write was. Tuple/object assignment is atomic under the
    GIL, so no lock is needed."""

    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state: ChannelState = EMPTY_STATE

    def write(self, state: ChannelState) -> None:
        self._state = state

    def read(self) -> ChannelState:
        return self._state

    @property
    def has_data(self) -> bool:
        return self._state.ts != EMPTY_STATE_TS
