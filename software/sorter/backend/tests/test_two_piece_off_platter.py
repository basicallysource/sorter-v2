"""A drop-zone detection that does not ride along with the platter is not on
it (a piece on C3's lip projecting into C4's drop zone, or one on the rim)."""
import logging
from types import SimpleNamespace

from subsystems.classification_channel.simple_state_machine_rev01.base import Rev01BaseState
from subsystems.classification_channel.two_piece import (
    _ZONE_DROP,
    _ZONE_NONE,
    TwoPieceClassificationChannel,
    _TrackedPiece,
)


def _handler():
    h = object.__new__(TwoPieceClassificationChannel)
    h._pieces = {}
    h._orphans = []
    h._aliases = {}
    h._reid_explained = set()
    h.logger = logging.getLogger("test")
    h._multi_drop_streak = 0
    h._multi_drop_last_ts = -1.0
    h._multi_drop_seq = 0
    h.ctx = SimpleNamespace(config=SimpleNamespace(multi_feed_confirm_reads=2))
    h.noteProgress = lambda: None

    def create(tid, now):
        tp = object.__new__(_TrackedPiece)
        tp.track_id = tid; tp.zone = _ZONE_NONE; tp.bbox = (0, 0, 0, 0); tp.gap_to_exit = None
        tp.progress_gap = None; tp.created_at = now; tp.last_seen = now; tp.still_since = now
        tp.capture_done = tp.result_applied = tp.placed = tp.double_feed = tp.ejected = False
        tp.multi_drop_group = None; tp.expected_gap = None
        tp.worker = SimpleNamespace(abandonInFlightObject=lambda r: None, ctx=SimpleNamespace(capturing_started_at=0.0))
        h._pieces[tid] = tp
        return tp

    h._createPiece = create
    return h


def _obs(ts, *items):
    return SimpleNamespace(
        ts=ts, in_drop=any(z == _ZONE_DROP for _, z, _ in items),
        pieces=[SimpleNamespace(sv_bt_track_id=t, zone_code=z, bbox=b, com_forward_to_exit_deg=None) for t, z, b in items],
    )


LIP = (1400, 1900, 1650, 2150)  # a plate hanging on C3's lip, seen inside C4's drop zone


def test_detection_that_ignores_a_turn_is_flagged_and_no_longer_blocks(monkeypatch) -> None:
    monkeypatch.setattr(Rev01BaseState, "startOutputMove", lambda self, deg, speed: True)
    h = _handler()
    h._observe(_obs(1.0, (1, _ZONE_DROP, LIP)), now=1.0, stopped=True)
    assert h._dropPiece() is not None and h._dropOccupied(_obs(1.0, (1, _ZONE_DROP, LIP)))
    h.startOutputMove(-30.0, 5000)                                   # the platter turns 30°
    h._observe(_obs(2.0, (1, _ZONE_DROP, LIP)), now=2.0, stopped=False)  # mid-turn frame: no verdict yet
    assert not h._pieces[1].off_platter
    h._observe(_obs(3.0, (1, _ZONE_DROP, LIP)), now=3.0, stopped=True)   # still exactly there
    assert h._pieces[1].off_platter
    assert h._dropPiece() is None
    assert not h._dropOccupied(_obs(3.0, (1, _ZONE_DROP, LIP)))
    assert h._headPiece() is None


def test_a_piece_that_rides_along_is_kept(monkeypatch) -> None:
    monkeypatch.setattr(Rev01BaseState, "startOutputMove", lambda self, deg, speed: True)
    h = _handler()
    h._observe(_obs(1.0, (1, _ZONE_DROP, (1300, 1700, 1500, 1900))), now=1.0, stopped=True)
    h.startOutputMove(-30.0, 5000)
    h._observe(_obs(2.0, (1, _ZONE_DROP, (900, 1200, 1100, 1400))), now=2.0, stopped=True)
    assert not h._pieces[1].off_platter and h._dropPiece() is not None


def test_small_turns_do_not_judge_and_moving_again_clears_the_flag(monkeypatch) -> None:
    monkeypatch.setattr(Rev01BaseState, "startOutputMove", lambda self, deg, speed: True)
    h = _handler()
    h._observe(_obs(1.0, (1, _ZONE_DROP, LIP)), now=1.0, stopped=True)
    h.startOutputMove(-5.0, 5000)
    h._observe(_obs(2.0, (1, _ZONE_DROP, LIP)), now=2.0, stopped=True)
    assert not h._pieces[1].off_platter                     # 5° proves nothing
    h.startOutputMove(-30.0, 5000)
    h._observe(_obs(3.0, (1, _ZONE_DROP, LIP)), now=3.0, stopped=True)
    assert h._pieces[1].off_platter
    h._observe(_obs(4.0, (1, _ZONE_DROP, (1300, 1700, 1550, 1950))), now=4.0, stopped=True)  # it fell onto the platter
    assert not h._pieces[1].off_platter and h._dropPiece() is not None


def test_off_platter_detection_does_not_make_a_double_feed(monkeypatch) -> None:
    monkeypatch.setattr(Rev01BaseState, "startOutputMove", lambda self, deg, speed: True)
    h = _handler()
    h._observe(_obs(1.0, (1, _ZONE_DROP, LIP)), now=1.0, stopped=True)
    h.startOutputMove(-30.0, 5000)
    h._observe(_obs(2.0, (1, _ZONE_DROP, LIP)), now=2.0, stopped=True)
    assert h._pieces[1].off_platter
    for ts in (3.0, 4.0, 5.0):
        h._observe(_obs(ts, (1, _ZONE_DROP, LIP), (2, _ZONE_DROP, (1000, 1500, 1200, 1700))), now=ts, stopped=True)
    assert not h._pieces[2].double_feed and not h._pieces[1].double_feed
