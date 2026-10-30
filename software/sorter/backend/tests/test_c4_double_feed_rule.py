"""A double feed is two pieces seen in the drop zone at once, not one piece that
the tracker renamed as it settled."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

from defs.known_object import ClassificationStatus, KnownObject
from piece_transport import ClassificationChannelTransport
from perception.state import ChannelState, PieceObservation
from piece_cycles import CycleRecorder
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
    ch._lost, ch._last_step_at, ch._turned_at = [], None, 0.0
    ch._rotation_started_at = 0.0
    ch._pair_until, ch._pair_group = 0.0, None
    ch._multi_drop_streak = 0
    ch._multi_drop_last_ts = -1.0
    ch._multi_drop_seq = 0
    ch.last_progress_at = time.monotonic()
    ch._cycles = CycleRecorder()
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


_PRECISE = 3
_RED = (1010, 1445, 1355, 1804)
_GRAY = (1236, 1727, 1475, 1944)
_WHOLE = (2634, 248, 2942, 647)
_PART = (2754, 412, 2942, 647)


def test_two_pieces_lying_touching_are_two_pieces() -> None:
    # The detector draws the same two separate boxes in every frame at rest.
    ch = _channel()
    tp = _track(ch, 15)
    tp.rest_boxes = [(_RED, _GRAY)] * 10
    assert ch._landedTouching(tp)


def test_one_piece_drawn_whole_and_in_parts_is_one_piece() -> None:
    # Around the whole piece and around its part, nested, and not every frame.
    ch = _channel()
    tp = _track(ch, 19)
    tp.rest_boxes = [(_WHOLE, _PART), (_WHOLE, _PART, (2654, 258, 2942, 647))] * 5
    assert not ch._landedTouching(tp)


def test_a_piece_that_comes_apart_once_it_moves_goes_to_misc() -> None:
    ch = _channel()
    ch.transport = ClassificationChannelTransport()
    ch._eject_target = None
    tp = _track(ch, 15)
    tp.zone = _PRECISE
    tp.capture_done = tp.result_applied = True
    obj = KnownObject(part_id="3001", color_id="5")
    obj.classification_status = ClassificationStatus.classified
    tp.worker.ctx.known_object = obj
    ch.transport.placePieceForDistribution(obj)
    tp.placed = True
    for _ in range(14):
        now = time.monotonic()
        tp.boxes, tp.last_seen = (_RED, _GRAY), now
        ch._flagComingApart(now)
    assert not tp.double_feed  # not yet: a moment apart is not enough
    now = time.monotonic()
    tp.boxes, tp.last_seen = (_RED, _GRAY), now
    ch._flagComingApart(now)
    assert tp.double_feed and not tp.placed
    assert obj.classification_status == ClassificationStatus.multi_drop_fail
    assert ch.transport.getPieceForDistributionPositioning() is None


def test_a_whole_minifigure_is_one_piece() -> None:
    # A head box above a body box, lined up: the boxes kitbash drew for a minifigure.
    ch = _channel()
    tp = _track(ch, 386)
    head, body = (2774, 780, 2949, 918), (2763, 900, 2964, 1157)
    tp.rest_boxes = [(head, body)] * 10
    assert not ch._landedTouching(tp)
