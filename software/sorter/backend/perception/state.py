"""Per-channel perception state — what the coordinator reads.

The slot stores booleans, not bboxes. Region attribution happens on the
inference thread; the coordinator gets a finished verdict. Single-ref
atomic write keeps the slot lock-free.
"""

from __future__ import annotations

from dataclasses import dataclass


EMPTY_STATE_TS = 0.0


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
    # COM to the CENTER of the PRECISE (staging) arc — see
    # ``arcs.comForwardToPreciseCenterDeg``. The C4 reverse flow drives this
    # toward 0 in MOVING_TO_PRECISE to park the piece in the precise band before
    # the fall-off. Same None semantics as ``exit_com_forward_to_center_deg``.
    exit_com_forward_to_precise_deg: float | None = None
    # True when the LEADING piece's COM section lies in the PRECISE zone. This is
    # the exact trigger for starting a C3 eject — the piece must actually be in
    # the precise (staging) band, not merely within some distance of the exit.
    exit_com_in_precise: bool = False


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
