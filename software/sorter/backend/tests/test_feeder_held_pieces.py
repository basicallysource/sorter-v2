"""A piece its channel turns under without moving it is held by the channel
next to it: that channel is turned a little, and the operator is called when a
few such turns do not free it."""

import logging
from types import SimpleNamespace

from subsystems.feeder.pulse_perception import held
from subsystems.feeder.pulse_perception.held import HeldPieces

_DROP, _EXIT = 1, 2


class _Stats:
    def __init__(self) -> None:
        self.active = None

    def activeIncident(self):
        return self.active

    def setActiveIncident(self, incident):
        self.active = incident

    def clearActiveIncident(self, kind=None, resolved_by=None):
        self.active = None


def _gc():
    return SimpleNamespace(logger=logging.getLogger("test_feeder_held_pieces"), runtime_stats=_Stats())


def _on(*pieces):
    return SimpleNamespace(
        pieces=[SimpleNamespace(sv_bt_track_id=t, com_forward_to_exit_deg=g, zone_code=z) for t, g, z in pieces]
    )


def test_a_piece_held_in_the_landing_area_turns_the_channel_above(monkeypatch):
    monkeypatch.setattr(held.incidents, "handling", lambda kind: "manual")
    gc = _gc()
    watch = HeldPieces(gc)
    still = _on((5, 200.0, _DROP))
    assert watch.check(3, still, 0.0, 0.0) is None
    assert watch.check(3, still, 30.0, 1.0) is None  # not turned enough yet
    turn = watch.check(3, still, 50.0, 2.0)
    assert turn is not None and (turn.channel, turn.held_on) == (2, 3)
    watch.turned(turn, 2.0)
    assert watch.check(3, still, 60.0, 2.5) is None  # the turn settles first
    for i in range(2):
        turn = watch.check(3, still, 70.0 + i, 3.5 + 1.5 * i)
        assert turn is not None
        watch.turned(turn, 3.5 + 1.5 * i)
    assert watch.check(3, still, 80.0, 8.0) is None
    assert gc.runtime_stats.active["kind"] == "piece_held"
    # It moves after all: the incident closes.
    watch.check(3, _on((5, 190.0, _DROP)), 90.0, 9.0)
    assert gc.runtime_stats.active is None


def test_a_piece_held_at_the_exit_turns_the_channel_below():
    watch = HeldPieces(_gc())
    still = _on((8, 1.0, _EXIT))
    watch.check(2, still, 0.0, 0.0)
    turn = watch.check(2, still, 50.0, 1.0)
    assert turn is not None and (turn.channel, turn.held_on) == (3, 2)


def test_a_piece_hanging_onto_the_classification_channel_is_only_reported(monkeypatch):
    monkeypatch.setattr(held.incidents, "handling", lambda kind: "manual")
    gc = _gc()
    watch = HeldPieces(gc)
    still = _on((9, 1.0, _EXIT))
    watch.check(3, still, 0.0, 0.0)
    assert watch.check(3, still, 100.0, 1.0) is None
    assert gc.runtime_stats.active is None
    assert watch.check(3, still, 200.0, 2.0) is None
    assert gc.runtime_stats.active["kind"] == "piece_held"
