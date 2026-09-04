"""A forward piece whose track id changes keeps its capture and result.

Regression (2026-09-05): track 7 was classified and the chute aimed, the
tracker dropped the id and re-issued it as track 8; the handler treated 8 as
an unclassified stray and sent a good piece to misc.
"""
import logging
from types import SimpleNamespace

from subsystems.classification_channel.two_piece import (
    TwoPieceClassificationChannel,
    _ORPHAN_ADOPT_S,
    _TRACK_GONE_RETIRE_S,
    _TrackedPiece,
    _ZONE_DROP,
    _ZONE_NONE,
)


class _Worker:
    def __init__(self) -> None:
        self.abandoned = []
        self.ctx = SimpleNamespace(known_object=object())

    def abandonInFlightObject(self, reason: str) -> None:
        self.abandoned.append(reason)


def _handler() -> TwoPieceClassificationChannel:
    h = object.__new__(TwoPieceClassificationChannel)
    h._pieces = {}
    h._orphans = []
    h.logger = logging.getLogger("test")
    h._multi_drop_streak = 0
    h._multi_drop_last_ts = -1.0
    h._multi_drop_seq = 0
    h.ctx = SimpleNamespace(config=SimpleNamespace(multi_feed_confirm_reads=3))
    h.progress = 0
    h.noteProgress = lambda: setattr(h, "progress", h.progress + 1)
    return h


def _piece(tid: int, *, zone: int, capture_done: bool, last_seen: float) -> _TrackedPiece:
    tp = object.__new__(_TrackedPiece)
    tp.track_id = tid
    tp.zone = zone
    tp.capture_done = capture_done
    tp.result_applied = capture_done
    tp.placed = capture_done
    tp.ejected = False
    tp.last_seen = last_seen
    tp.worker = _Worker()
    return tp


def _observation(tid: int, zone: int):
    return SimpleNamespace(
        pieces=[SimpleNamespace(sv_bt_track_id=tid, zone_code=zone, bbox=(0, 0, 10, 10), com_forward_to_exit_deg=None)],
        ts=1.0,
    )


def test_forward_piece_with_result_is_kept_and_adopted_by_new_forward_id() -> None:
    h = _handler()
    old = _piece(7, zone=_ZONE_NONE, capture_done=True, last_seen=0.0)
    h._pieces = {7: old}
    h._retireGonePieces(now=_TRACK_GONE_RETIRE_S + 0.1)
    assert 7 not in h._pieces and len(h._orphans) == 1
    assert old.worker.abandoned == []

    h._observe(_observation(8, _ZONE_NONE), now=4.0)
    assert h._pieces[8] is old
    assert old.track_id == 8 and old.placed and old.result_applied
    assert h._orphans == []


def test_new_id_in_drop_zone_is_an_arrival_not_an_adoption(monkeypatch) -> None:
    h = _handler()
    old = _piece(7, zone=_ZONE_NONE, capture_done=True, last_seen=0.0)
    h._orphans = [(old, 1.0)]
    created = []
    h._createPiece = lambda tid, now: created.append(tid) or _piece(tid, zone=_ZONE_DROP, capture_done=False, last_seen=now)
    h._observe(_observation(9, _ZONE_DROP), now=2.0)
    assert created == [9]
    assert len(h._orphans) == 1


def test_orphan_expires_and_is_abandoned() -> None:
    h = _handler()
    old = _piece(7, zone=_ZONE_NONE, capture_done=True, last_seen=0.0)
    h._orphans = [(old, 1.0)]
    h._retireGonePieces(now=1.0 + _ORPHAN_ADOPT_S + 0.1)
    assert h._orphans == []
    assert old.worker.abandoned == ["track id gone (left channel)"]


def test_uncaptured_or_ejected_pieces_retire_normally() -> None:
    h = _handler()
    fresh = _piece(1, zone=_ZONE_NONE, capture_done=False, last_seen=0.0)
    done = _piece(2, zone=_ZONE_NONE, capture_done=True, last_seen=0.0)
    done.ejected = True
    h._pieces = {1: fresh, 2: done}
    h._retireGonePieces(now=_TRACK_GONE_RETIRE_S + 0.1)
    assert h._pieces == {} and h._orphans == []
    assert fresh.worker.abandoned and done.worker.abandoned


def test_captured_drop_piece_lost_mid_staging_is_kept_as_orphan() -> None:
    h = _handler()
    staged = _piece(1, zone=_ZONE_DROP, capture_done=True, last_seen=0.0)
    h._pieces = {1: staged}
    h._retireGonePieces(now=_TRACK_GONE_RETIRE_S + 0.1)
    assert h._pieces == {} and len(h._orphans) == 1
    h._observe(_observation(3, _ZONE_NONE), now=2.0)
    assert h._pieces[3] is staged and staged.track_id == 3
