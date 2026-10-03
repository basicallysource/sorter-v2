"""A double feed is two pieces seen in the drop zone at once, not one piece that
the tracker renamed as it settled."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from defs.known_object import ClassificationStatus
from perception.state import ChannelState, PieceObservation
from subsystems.classification_channel.two_piece.flow import (
    TwoPieceClassificationChannel,
    _TrackedPiece,
)

_DROP = 1


class _Worker:
    def __init__(self) -> None:
        self.ctx = SimpleNamespace(known_object=None, classify_started_at=0.0)

    def emitKnownObject(self) -> None:
        pass


def _channel() -> TwoPieceClassificationChannel:
    ch = TwoPieceClassificationChannel.__new__(TwoPieceClassificationChannel)
    ch.logger = logging.getLogger("test_c4_double_feed_rule")
    ch.ctx = SimpleNamespace(config=SimpleNamespace(multi_feed_confirm_reads=3))
    ch._pieces = {}
    ch._multi_drop_streak = 0
    ch._multi_drop_last_ts = -1.0
    ch._multi_drop_seq = 0
    ch.last_progress_at = time.monotonic()
    return ch


def _track(ch: TwoPieceClassificationChannel, track_id: int) -> _TrackedPiece:
    tp = _TrackedPiece(track_id, _Worker(), time.monotonic())
    tp.zone = _DROP
    ch._pieces[track_id] = tp
    return tp


def _frame(ts: float, *track_ids: int) -> ChannelState:
    pieces = tuple(
        PieceObservation(
            com_forward_to_exit_deg=90.0, com_section=0, zone_code=_DROP, sv_bt_track_id=t
        )
        for t in track_ids
    )
    return ChannelState(ts=ts, in_drop=True, in_exit=False, n_pieces=len(pieces), pieces=pieces)


def test_a_piece_renamed_as_it_settles_is_not_a_double_feed() -> None:
    ch = _channel()
    old = _track(ch, 7)  # the id it had while bouncing, not retired yet
    new = _track(ch, 8)
    for ts in (1.0, 1.1, 1.2, 1.3):
        ch._flagDoubleFeeds(_frame(ts, 8))
    assert not old.double_feed and not new.double_feed


def test_two_pieces_seen_together_are_a_double_feed() -> None:
    ch = _channel()
    a, b = _track(ch, 7), _track(ch, 8)
    for ts in (1.0, 1.1, 1.2):
        ch._flagDoubleFeeds(_frame(ts, 7, 8))
    assert a.double_feed and b.double_feed
    assert a.multi_drop_group == b.multi_drop_group
    assert a.known_object.classification_status == ClassificationStatus.multi_drop_fail
