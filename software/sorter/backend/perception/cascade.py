"""Feeder cascade rule — the entire decision logic for C1/C2/C3.

Pure function. Read the doc at
``sorter-v2-agent-notes/tasks/operation-30hz/rev04_2026-05-27.md`` for the
canonical channel behavior. C4 is consumed here (to gate C3) but its own
motion belongs to the classification-channel state machine, not this
function.

THIS IS THE CORE DECISION SOURCE FOR THE PURE REV04 / GO_TO_ANGLE_REV01
PERCEPTION PATH (when perception_service is active). The go-to-angle jitter
logic reads ChannelState.in_exit etc. that ultimately come from the
inference workers feeding these slots.
"""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple

from .state import ChannelState


class Action(Enum):
    IDLE = "idle"        # do not move
    ADVANCE = "advance"  # free move, push pieces along this channel
    PRECISE = "precise"  # small pulse, push the piece at exit forward
    FREEZE = "freeze"    # do not move (waiting on downstream)


class FeederActions(NamedTuple):
    c1: Action
    c2: Action
    c3: Action


def feederChannelAction(
    state: ChannelState, downstream_clear: bool, greedy: bool = False
) -> Action:
    """The rule for C2 and C3 (channels with their own drop+exit zones).

    ``greedy`` (per-channel): in the default rule a channel only advances while a
    piece is in its drop zone, then idles until the piece reaches the exit zone.
    In greedy mode the channel advances a piece toward the exit as soon as it is
    seen ANYWHERE on the channel (any on-channel piece, not yet at the exit), so
    the piece is staged at the exit edge immediately and the drop zone clears
    sooner — letting the upstream channel feed again. The advance is still capped
    to the exit edge by the caller (advance_clearance_deg) and exit hand-off
    stays downstream-gated, so the usual protections hold."""
    if state.in_exit:
        return Action.PRECISE if downstream_clear else Action.FREEZE
    if state.in_drop:
        return Action.ADVANCE
    if greedy and state.n_pieces > 0:
        return Action.ADVANCE
    return Action.IDLE


def c1Action(c2: ChannelState) -> Action:
    """C1 has no drop/exit of its own — it always advances unless C2's
    drop zone is occupied."""
    return Action.ADVANCE if not c2.in_drop else Action.FREEZE


def classificationReady(c4: ChannelState) -> bool:
    """C4 (classification channel) is ready to receive when the channel is
    empty. Any piece anywhere on C4 → not ready."""
    return c4.n_pieces == 0


def cascade(c2: ChannelState, c3: ChannelState, c4: ChannelState) -> FeederActions:
    """The whole feeder decision, one tick.

    The mapping, in plain English:
      - C3 holds still iff a piece is in its exit zone AND C4 is not ready.
      - C3 precise-pulses iff a piece is in its exit zone AND C4 is ready.
      - C3 advances freely iff a piece is in its drop zone (and no exit
        piece).
      - C3 idles iff its channel is empty.
      - C2 follows the same rule with "downstream clear" = not c3.in_drop.
      - C1 just advances unless C2's drop zone is occupied.
    """
    a3 = feederChannelAction(c3, downstream_clear=classificationReady(c4))
    a2 = feederChannelAction(c2, downstream_clear=not c3.in_drop)
    a1 = c1Action(c2)
    return FeederActions(c1=a1, c2=a2, c3=a3)
