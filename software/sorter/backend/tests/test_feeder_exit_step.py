"""One piece in the opening at a time: while the lead is in a channel's exit
opening, the exit never brings the next piece's center within clear_deg of it,
and shakes the lead loose instead."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from perception.cascade import Action
from subsystems.feeder.pulse_perception.config import PulsePerceptionConfig
from subsystems.feeder.pulse_perception.dispense_gate import DispenseGate
from subsystems.feeder.pulse_perception.exit_step import MAX_TRIES, ExitStep, exitStep
from subsystems.feeder.pulse_perception.flow import PulsePerceptionFeeding


def _step(lead: float, nxt: float | None, tries: int = 0, push: float = 2.0, clear: float = 2.0) -> ExitStep:
    return exitStep(lead, nxt, push, 2.0, clear, tries)


def test_with_nothing_close_behind_the_exit_pushes_as_before() -> None:
    assert _step(-3.0, None, push=10.0) == ExitStep("push", 10.0)
    assert _step(-3.0, 12.0) == ExitStep("push", 2.0)


def test_a_push_stops_before_the_next_piece_comes_within_clear_of_the_opening() -> None:
    assert _step(-3.0, 3.0) == ExitStep("push", 1.0)


def test_with_the_lead_in_the_opening_and_no_room_left_it_shakes() -> None:
    assert _step(-6.0, 2.2) == ExitStep("shake", 2.0)


def test_a_next_piece_already_too_close_is_backed_off_first() -> None:
    # Back to 1 degree beyond clear: from -1 to 3, while the lead stays in.
    assert _step(-10.0, -1.0) == ExitStep("back", 4.0)


@pytest.mark.parametrize(
    ("lead", "nxt", "why"),
    [
        (1.0, 1.5, "beside the lead"),
        (-2.0, -1.0, "too close to part"),
    ],
)
def test_pieces_too_close_to_part_are_pushed_as_before(lead: float, nxt: float, why: str) -> None:
    assert _step(lead, nxt) == ExitStep("push", 2.0, why)


def test_after_its_tries_the_lead_is_pushed_off() -> None:
    assert _step(-6.0, 2.2, tries=MAX_TRIES) == ExitStep("push", 2.0, "tries used up")


def test_off_the_rule_changes_nothing() -> None:
    assert _step(-6.0, 0.0, clear=0.0) == ExitStep("push", 2.0)


def _piece(deg: float, track_id: int):
    return SimpleNamespace(com_forward_to_exit_deg=deg, sv_bt_track_id=track_id, bbox=(0, 0, 1, 1))


def _feeder() -> tuple[PulsePerceptionFeeding, list[tuple[int, float]]]:
    feeder = PulsePerceptionFeeding.__new__(PulsePerceptionFeeding)
    moves: list[tuple[int, float]] = []

    def move(label, channel, stepper, deg, pause, cfg, enforce_min=True, backwards=False):
        moves.append((channel, -deg if backwards else deg))
        return True

    feeder._busy = lambda stepper: False
    feeder._move = move
    feeder._exitMoveDeg = lambda channel, state, cfg: 2.0
    feeder._gates = {2: DispenseGate(), 3: DispenseGate()}
    feeder._moved_until = {}
    feeder._shake_owed = {}
    feeder._exit_tries = {}
    return feeder, moves


def _act(feeder: PulsePerceptionFeeding, channel: int, action: Action, *pieces, ts: float = 10.0) -> None:
    state = SimpleNamespace(ts=ts, pieces=pieces, in_drop=False)
    feeder._apply_action(f"ch{channel}", channel, action, SimpleNamespace(_name="s"), state, PulsePerceptionConfig())


def test_a_shake_goes_back_then_forward_as_far_whatever_comes_next() -> None:
    feeder, moves = _feeder()
    _act(feeder, 2, Action.PRECISE, _piece(-6.0, 7), _piece(2.2, 8))
    # Downstream is no longer clear, but the shake still ends where it began.
    _act(feeder, 2, Action.FREEZE, _piece(-6.0, 7), _piece(2.2, 8))
    _act(feeder, 2, Action.FREEZE, _piece(-6.0, 7), _piece(2.2, 8))
    assert moves == [(2, -2.0), (2, 2.0)]
    assert feeder._gates[2].track_id == 7


def test_the_exit_decides_only_on_a_picture_taken_after_its_last_move() -> None:
    feeder, moves = _feeder()
    feeder._moved_until[2] = 10.5
    _act(feeder, 2, Action.PRECISE, _piece(-3.0, 7), ts=10.4)
    assert moves == []
    _act(feeder, 2, Action.PRECISE, _piece(-3.0, 7), ts=10.6)
    assert moves == [(2, 2.0)]


def test_tries_count_per_lead() -> None:
    feeder, moves = _feeder()
    for _ in range(MAX_TRIES):
        _act(feeder, 2, Action.PRECISE, _piece(-6.0, 7), _piece(2.2, 8))
        _act(feeder, 2, Action.FREEZE, _piece(-6.0, 7), _piece(2.2, 8))
    _act(feeder, 2, Action.PRECISE, _piece(-6.0, 7), _piece(2.2, 8))
    assert moves[-1] == (2, 2.0) and len(moves) == 2 * MAX_TRIES + 1
    # A new lead gets its own tries.
    _act(feeder, 2, Action.PRECISE, _piece(-6.0, 8), _piece(2.2, 9))
    assert moves[-1] == (2, -2.0)


def test_c3_pushes_as_before_unless_turned_on() -> None:
    feeder, moves = _feeder()
    feeder._moved_until[3] = 99.0
    _act(feeder, 3, Action.PRECISE, _piece(-6.0, 7), _piece(0.5, 8))
    assert moves == [(3, 2.0)]
