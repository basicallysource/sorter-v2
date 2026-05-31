"""Cascade rule tests.

Enumerates the full input space for cascade(c2, c3, c4) and pins every
output. The cascade is the entire feeder decision logic; if these change,
they should change with a commit message explaining why.

Input space:
  c2.in_drop ∈ {F, T}
  c2.in_exit ∈ {F, T}
  c3.in_drop ∈ {F, T}
  c3.in_exit ∈ {F, T}
  c4.n_pieces ∈ {0, ≥1}   →  classification_ready True/False

= 32 combinations × {a1, a2, a3} pinned outputs.
"""

import itertools

import pytest

from perception.cascade import (
    Action,
    cascade,
    classificationReady,
    feederChannelAction,
)
from perception.state import ChannelState


def _state(in_drop: bool, in_exit: bool, n_pieces: int = 0) -> ChannelState:
    return ChannelState(ts=1.0, in_drop=in_drop, in_exit=in_exit, n_pieces=n_pieces)


# --- per-channel rule (the building block) ---------------------------------


def test_feeder_action_at_exit_downstream_clear_pulses() -> None:
    assert feederChannelAction(_state(False, True), downstream_clear=True) == Action.PRECISE
    # Drop+exit simultaneously → exit wins (we're about to dispense; that
    # is the priority).
    assert feederChannelAction(_state(True, True), downstream_clear=True) == Action.PRECISE


def test_feeder_action_at_exit_downstream_blocked_freezes() -> None:
    assert feederChannelAction(_state(False, True), downstream_clear=False) == Action.FREEZE
    assert feederChannelAction(_state(True, True), downstream_clear=False) == Action.FREEZE


def test_feeder_action_in_drop_advances() -> None:
    # Drop-only: advance regardless of downstream — only the exit push
    # waits on downstream.
    assert feederChannelAction(_state(True, False), downstream_clear=True) == Action.ADVANCE
    assert feederChannelAction(_state(True, False), downstream_clear=False) == Action.ADVANCE


def test_feeder_action_empty_idles() -> None:
    assert feederChannelAction(_state(False, False), downstream_clear=True) == Action.IDLE
    assert feederChannelAction(_state(False, False), downstream_clear=False) == Action.IDLE


# --- C4 ready ---------------------------------------------------------------


def test_classification_ready_only_when_c4_empty() -> None:
    assert classificationReady(_state(False, False, n_pieces=0)) is True
    assert classificationReady(_state(False, False, n_pieces=1)) is False
    assert classificationReady(_state(True, False, n_pieces=1)) is False
    assert classificationReady(_state(False, True, n_pieces=2)) is False


# --- full cascade input-space enumeration -----------------------------------


_BOOLS = (False, True)
_C4_COUNTS = (0, 1)


def _enumerate() -> list[tuple[ChannelState, ChannelState, ChannelState]]:
    out = []
    for c2_drop, c2_exit, c3_drop, c3_exit, c4_n in itertools.product(
        _BOOLS, _BOOLS, _BOOLS, _BOOLS, _C4_COUNTS
    ):
        out.append((
            _state(c2_drop, c2_exit),
            _state(c3_drop, c3_exit),
            _state(False, False, n_pieces=c4_n),
        ))
    return out


@pytest.mark.parametrize("c2,c3,c4", _enumerate())
def test_cascade_outputs_consistent_with_per_channel_rules(
    c2: ChannelState, c3: ChannelState, c4: ChannelState
) -> None:
    a = cascade(c2, c3, c4)
    expected_a3 = feederChannelAction(c3, classificationReady(c4))
    expected_a2 = feederChannelAction(c2, not c3.in_drop)
    expected_a1 = Action.ADVANCE if not c2.in_drop else Action.FREEZE
    assert a.c3 == expected_a3, (c2, c3, c4, a)
    assert a.c2 == expected_a2, (c2, c3, c4, a)
    assert a.c1 == expected_a1, (c2, c3, c4, a)


# --- specific scenarios from the spec --------------------------------------


def test_chain_dispense_when_everyone_at_exit_and_c4_ready() -> None:
    """C3 at exit + C4 ready → C3 pulses. C2 at exit + C3 has nothing in
    drop → C2 pulses. C1 advances unless C2 drop occupied."""
    c2 = _state(in_drop=False, in_exit=True)
    c3 = _state(in_drop=False, in_exit=True)
    c4 = _state(in_drop=False, in_exit=False, n_pieces=0)
    a = cascade(c2, c3, c4)
    assert a == (Action.ADVANCE, Action.PRECISE, Action.PRECISE)


def test_jam_at_classification_freezes_c3_only() -> None:
    """C3 at exit but C4 has a piece → C3 freezes. C2 unaffected unless its
    own exit is engaged."""
    c2 = _state(in_drop=True, in_exit=False)
    c3 = _state(in_drop=False, in_exit=True)
    c4 = _state(in_drop=False, in_exit=False, n_pieces=1)
    a = cascade(c2, c3, c4)
    assert a.c3 == Action.FREEZE
    assert a.c2 == Action.ADVANCE     # C2 has a drop piece, downstream=c3 not in_drop
    assert a.c1 == Action.FREEZE      # C2 drop occupied
