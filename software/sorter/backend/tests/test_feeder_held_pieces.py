"""A piece its channel turns under without moving it is held by the channel
next to it. Where pieces land it is handed to its incident and recovery, once;
at the exit the channel below is turned a little, and after a few turns that do
not free it the feeder gives up on it and sorting goes on."""

import logging
from types import SimpleNamespace

import pytest

import db
import held_piece_records
from subsystems.feeder.pulse_perception.held import FreeTurn, HeldAtLanding, HeldPieces

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


@pytest.fixture(autouse=True)
def _scratch_db(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STATE_DB_PATH", str(tmp_path / "state.sqlite"))


def _gc():
    return SimpleNamespace(logger=logging.getLogger("test_feeder_held_pieces"), runtime_stats=_Stats())


def _on(*pieces, box=(500, 300, 540, 340)):
    return SimpleNamespace(
        pieces=[
            SimpleNamespace(sv_bt_track_id=t, com_forward_to_exit_deg=g, zone_code=z, bbox=box)
            for t, g, z in pieces
        ]
    )


def test_a_piece_held_where_pieces_land_is_handed_to_its_incident_once():
    gc = _gc()
    watch = HeldPieces(gc)
    still = _on((5, 200.0, _DROP))
    assert watch.check(3, still, 0.0, 0.0) is None
    assert watch.check(3, still, 30.0, 1.0) is None  # not turned enough yet
    held = watch.check(3, still, 50.0, 2.0)
    assert held == HeldAtLanding(3, 5, (500.0, 300.0, 540.0, 340.0))
    assert watch.check(3, still, 80.0, 3.0) is None
    # It moves after all, and the held piece is recorded.
    watch.check(3, _on((5, 190.0, _DROP)), 90.0, 9.0)
    assert db.drain(5.0)
    (row,) = held_piece_records.listHeld(0.0, 1e12)
    assert (row["channel"], row["zone"], row["turns"], row["outcome"]) == (3, "landing", 0, "freed")


def test_a_box_cut_off_by_the_edge_of_the_picture_is_not_watched():
    watch = HeldPieces(_gc())
    at_edge = _on((5, 200.0, _DROP), box=(600, 680, 660, 720))
    for odometer in (0.0, 50.0, 100.0):
        assert watch.check(3, at_edge, odometer, odometer / 50.0, (1280, 720)) is None


def test_a_piece_held_at_the_exit_turns_the_channel_below():
    watch = HeldPieces(_gc())
    still = _on((8, 1.0, _EXIT))
    watch.check(2, still, 0.0, 0.0)
    turn = watch.check(2, still, 50.0, 1.0)
    assert isinstance(turn, FreeTurn) and (turn.channel, turn.held_on) == (3, 2)


def test_a_piece_hanging_onto_the_classification_channel_is_left_to_it():
    watch = HeldPieces(_gc())
    still = _on((9, 1.0, _EXIT))
    watch.check(3, still, 0.0, 0.0)
    assert watch.check(3, still, 100.0, 1.0) is None
    assert watch.check(3, still, 200.0, 2.0) is None
    watch.check(3, _on(), 210.0, 3.0)  # it fell
    assert db.drain(5.0)
    (row,) = held_piece_records.listHeld(0.0, 1e12)
    assert (row["turns"], row["gave_up"], row["outcome"]) == (0, 1, "gone")
