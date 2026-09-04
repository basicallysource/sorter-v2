"""Double-feed debounce of the C4 two-piece handler.

Regression: a piece first glimpsed as a sliver at the truncated frame edge got
one track id, then a second id once fully visible. The stale first id was still
in its retire window, so the handler saw "two ids in DROP" for several frames
and flagged a double feed on a single piece.
"""
import logging
from types import SimpleNamespace

from subsystems.classification_channel.two_piece import (
    TwoPieceClassificationChannel,
    _TrackedPiece,
    _ZONE_DROP,
)


def _handler(confirm_reads: int = 3) -> TwoPieceClassificationChannel:
    h = object.__new__(TwoPieceClassificationChannel)
    h._pieces = {}
    h._multi_drop_streak = 0
    h._multi_drop_last_ts = -1.0
    h._multi_drop_seq = 0
    h.ctx = SimpleNamespace(config=SimpleNamespace(multi_feed_confirm_reads=confirm_reads))
    h.logger = logging.getLogger("test")
    h.flagged = []
    h._markDoubleFeed = lambda tp, group: h.flagged.append((tp.track_id, group))
    return h


def _piece(tid: int) -> _TrackedPiece:
    tp = object.__new__(_TrackedPiece)
    tp.track_id = tid
    tp.zone = _ZONE_DROP
    tp.double_feed = False
    tp.multi_drop_group = None
    return tp


def _frame(h: TwoPieceClassificationChannel, ts: float, seen: set[int]) -> None:
    h._flagDoubleFeeds(SimpleNamespace(ts=ts), seen)


def test_stale_track_in_drop_does_not_pair_with_its_successor() -> None:
    h = _handler()
    h._pieces = {25: _piece(25), 26: _piece(26)}
    # Track 25 vanished; only 26 is detected from now on.
    for i in range(6):
        _frame(h, ts=float(i), seen={26})
    assert h.flagged == []


def test_two_pieces_detected_together_confirm_after_threshold() -> None:
    h = _handler(confirm_reads=3)
    h._pieces = {1: _piece(1), 2: _piece(2)}
    _frame(h, 0.0, {1, 2})
    _frame(h, 1.0, {1, 2})
    assert h.flagged == []
    _frame(h, 2.0, {1, 2})
    assert sorted(h.flagged) == [(1, 1), (2, 1)]


def test_streak_resets_when_a_frame_shows_one_piece() -> None:
    h = _handler(confirm_reads=3)
    h._pieces = {1: _piece(1), 2: _piece(2)}
    _frame(h, 0.0, {1, 2})
    _frame(h, 1.0, {1, 2})
    _frame(h, 2.0, {1})
    _frame(h, 3.0, {1, 2})
    _frame(h, 4.0, {1, 2})
    assert h.flagged == []
    _frame(h, 5.0, {1, 2})
    assert len(h.flagged) == 2


def test_repeated_frame_timestamp_counts_once() -> None:
    h = _handler(confirm_reads=2)
    h._pieces = {1: _piece(1), 2: _piece(2)}
    _frame(h, 0.0, {1, 2})
    _frame(h, 0.0, {1, 2})
    assert h.flagged == []
    _frame(h, 1.0, {1, 2})
    assert len(h.flagged) == 2
