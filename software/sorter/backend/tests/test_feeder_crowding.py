"""A crowded channel gets nothing more from the one before it: pieces packed
together on C3 sit touching, and its exit then drops two at once onto the
classification channel."""

from __future__ import annotations

from types import SimpleNamespace

from subsystems.feeder.pulse_perception.config import PulsePerceptionConfig
from subsystems.feeder.pulse_perception.flow import PulsePerceptionFeeding


def _feeder(hidden: dict[int, int] | None = None) -> PulsePerceptionFeeding:
    feeder = PulsePerceptionFeeding.__new__(PulsePerceptionFeeding)
    feeder.shared = SimpleNamespace(feeder_hidden_pieces=dict(hidden or {}))
    return feeder


def test_a_full_channel_has_no_room() -> None:
    feeder = _feeder()
    assert feeder._hasRoom(3, SimpleNamespace(n_pieces=2), 3)
    assert not feeder._hasRoom(3, SimpleNamespace(n_pieces=3), 3)


def test_pieces_out_of_sight_count() -> None:
    feeder = _feeder({3: 1})
    assert not feeder._hasRoom(3, SimpleNamespace(n_pieces=2), 3)


def test_no_limit_by_default() -> None:
    assert PulsePerceptionConfig().ch3_max_pieces == 0
    assert PulsePerceptionConfig().ch2_max_pieces == 0
    assert _feeder()._hasRoom(3, SimpleNamespace(n_pieces=40), 0)
