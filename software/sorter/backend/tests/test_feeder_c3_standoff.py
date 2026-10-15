"""While the classification channel is busy, C3 keeps its lead piece back from
the lip instead of carrying it right up to the exit edge, where it can fall onto
the classification channel mid-turn beside the piece already there."""

from __future__ import annotations

from types import SimpleNamespace

from perception.cascade import Action
from subsystems.feeder.pulse_perception.config import PulsePerceptionConfig
from subsystems.feeder.pulse_perception.flow import PulsePerceptionFeeding


def _feeder(*, c4_ready: bool) -> tuple[PulsePerceptionFeeding, list[float]]:
    feeder = PulsePerceptionFeeding.__new__(PulsePerceptionFeeding)
    moves: list[float] = []
    feeder._busy = lambda stepper: False
    feeder._classification_ready = lambda cfg: c4_ready
    feeder._move = lambda label, channel, stepper, deg, pause, cfg, enforce_min=True: moves.append(deg) or True
    return feeder, moves


def _advance(feeder: PulsePerceptionFeeding, channel: int, clearance: float, standoff: float) -> None:
    cfg = PulsePerceptionConfig(ch3_busy_standoff_deg=standoff)
    state = SimpleNamespace(in_drop=True, advance_clearance_deg=clearance)
    feeder._apply_action(f"ch{channel}", channel, Action.ADVANCE, SimpleNamespace(_name="s"), state, cfg)


def test_c3_stops_short_of_the_lip_while_c4_is_busy() -> None:
    feeder, moves = _feeder(c4_ready=False)
    _advance(feeder, 3, clearance=20.0, standoff=12.0)
    assert moves == [8.0]


def test_c3_does_not_move_when_the_lead_is_already_within_the_standoff() -> None:
    feeder, moves = _feeder(c4_ready=False)
    _advance(feeder, 3, clearance=10.0, standoff=12.0)
    assert moves == []


def test_c3_advances_to_the_edge_once_c4_is_ready() -> None:
    feeder, moves = _feeder(c4_ready=True)
    _advance(feeder, 3, clearance=20.0, standoff=12.0)
    assert moves == [20.0]


def test_c2_is_not_held_back() -> None:
    feeder, moves = _feeder(c4_ready=False)
    _advance(feeder, 2, clearance=20.0, standoff=12.0)
    assert moves == [20.0]
