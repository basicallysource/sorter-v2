"""Two pieces from one feed that land touching become one box to the camera,
often from the very next frame: the box merge that keeps one piece from being
counted as several fuses them, and the pair was tracked, photographed and
sorted as one piece. The frame they land in still shows them apart, and a
piece landing against one already there makes its box grow. Either makes a
double feed, sent to misc."""

from __future__ import annotations

import logging
import time
from collections import deque
from types import SimpleNamespace

from defs.known_object import ClassificationStatus
from piece_cycles import CycleRecorder
from piece_transport import ClassificationChannelTransport
from runtime_stats import RuntimeStatsCollector
from subsystems.classification_channel.two_piece import flow as two_piece
from subsystems.classification_channel.two_piece.flow import (
    TwoPieceClassificationChannel,
    _Phase,
)
from subsystems.shared_variables import SharedVariables

DROP = two_piece._ZONE_DROP
_LOGGER = logging.getLogger("test_c4_close_landings")


class _Worker:
    def __init__(self) -> None:
        self.ctx = SimpleNamespace(known_object=None, classify_started_at=0.0)

    def emitKnownObject(self) -> None:
        pass

    def abandonInFlightObject(self, reason: str) -> None:
        pass


def _channel(*, stopped: bool = True) -> TwoPieceClassificationChannel:
    transport = ClassificationChannelTransport()
    shared = SharedVariables()
    shared.transport = transport
    ch = TwoPieceClassificationChannel.__new__(TwoPieceClassificationChannel)
    ch.transport, ch.shared, ch.logger = transport, shared, _LOGGER
    ch.gc = SimpleNamespace(logger=_LOGGER, runtime_stats=RuntimeStatsCollector())
    ch.irl = SimpleNamespace(carousel_stepper=SimpleNamespace(stopped=stopped))
    ch.ctx = SimpleNamespace(
        config=SimpleNamespace(multi_feed_confirm_reads=3), reset=lambda: None, known_object=None
    )
    ch._pieces = {}
    ch._lost, ch._last_step_at, ch._turned_at = [], None, 0.0
    ch._rotation_started_at = 0.0
    ch._pair_until, ch._pair_group = 0.0, None
    ch._phase = _Phase.WAITING
    ch._eject_target = ch._stage_target = None
    ch._phase_started_at = time.monotonic()
    ch.last_progress_at = time.monotonic()
    ch._multi_drop_streak, ch._multi_drop_last_ts, ch._multi_drop_seq = 0, -1.0, 0
    ch._recent_ejects = deque(maxlen=16)
    ch._bucket_hold_cycles = 0
    ch._cycles = CycleRecorder()
    ch._was_ready, ch._ready_since = False, None
    # Pieces get a worker with nothing photographed, like a fresh drop arrival.
    ch._createPiece = lambda tid, now: ch._pieces.setdefault(
        tid, two_piece._TrackedPiece(tid, _Worker(), now)
    )
    return ch


def _box(gap: float, tid, *, size: int = 100, x: int = 1000) -> SimpleNamespace:
    return SimpleNamespace(
        sv_bt_track_id=tid,
        zone_code=DROP,
        com_forward_to_exit_deg=gap,
        bbox=(x, 500, x + size, 500 + size),
    )


def _frame(ts: float, *boxes, merged: tuple = ()) -> SimpleNamespace:
    return SimpleNamespace(ts=ts, pieces=boxes, merged=merged)


def test_two_boxes_landing_side_by_side_then_fused_are_a_double_feed() -> None:
    ch = _channel()
    now = time.monotonic()
    # The landing frame shows two pieces, before either has a track id...
    ch._observe(_frame(1.0, _box(207.0, None), _box(208.0, None, x=1130)), now)
    # ...and the next frames one fused box, which then gets its id.
    ch._observe(_frame(1.1, _box(150.0, 308, size=200)), now + 0.15)
    tp = ch._pieces[308]
    assert tp.double_feed
    obj = tp.known_object
    assert obj is not None and obj.classification_status == ClassificationStatus.multi_drop_fail
    assert obj.problems[0]["kind"] == "double_feed"


def test_a_second_box_beside_the_piece_being_photographed_makes_both_double_feeds() -> None:
    ch = _channel()
    now = time.monotonic()
    ch._observe(_frame(1.0, _box(210.0, 67)), now)
    ch._observe(_frame(1.1, _box(210.0, 67), _box(195.0, 68, x=1200)), now + 0.1)
    assert ch._pieces[67].double_feed and ch._pieces[68].double_feed
    assert ch._pieces[67].multi_drop_group == ch._pieces[68].multi_drop_group


def test_a_piece_landing_well_after_a_pair_is_its_own_piece() -> None:
    ch = _channel()
    now = time.monotonic()
    ch._observe(_frame(1.0, _box(207.0, None), _box(208.0, None, x=1130)), now)
    ch._observe(_frame(2.0, _box(207.0, 400)), now + two_piece._PAIR_FOLLOW_S + 0.5)
    assert not ch._pieces[400].double_feed


def test_boxes_far_apart_or_a_small_fragment_are_no_pair() -> None:
    ch = _channel()
    now = time.monotonic()
    ch._observe(_frame(1.0, _box(210.0, 70), _box(150.0, 71, x=1500)), now)
    ch._observe(_frame(1.1, _box(210.0, 72, x=2000), _box(205.0, None, size=30, x=2200)), now + 0.1)
    assert not any(tp.double_feed for tp in ch._pieces.values())


def test_no_pair_is_judged_while_the_channel_turns() -> None:
    ch = _channel(stopped=False)
    now = time.monotonic()
    ch._observe(_frame(1.0, _box(207.0, 80), _box(208.0, 81, x=1130)), now)
    assert not ch._pieces[80].double_feed


def test_a_box_that_grows_while_at_rest_had_a_piece_land_against_it() -> None:
    ch = _channel()
    t0 = time.monotonic()
    for i in range(6):  # lands and settles at 100 x 100
        ch._observe(_frame(1.0 + i, _box(210.0, 90)), t0 + 0.1 * i)
    assert not ch._pieces[90].double_feed
    for i in range(2):  # a second piece lands against it: a box of its own in the merged box
        grown = _box(210.0, 90, size=135)
        merged = ((grown.bbox, ((1000, 500, 1100, 600), (1080, 560, 1135, 635))),)
        ch._observe(_frame(7.0 + i, grown, merged=merged), t0 + 0.6 + 0.1 * i)
    assert ch._pieces[90].double_feed
    assert "grew" in ch._pieces[90].known_object.problems[0]["message"]


def test_a_piece_that_tips_over_as_it_settles_is_not_a_double_feed() -> None:
    # A wheel lands on its edge, then falls flat: its one box grows, no second box appears.
    ch = _channel()
    t0 = time.monotonic()
    for i in range(6):
        ch._observe(_frame(1.0 + i, _box(210.0, 91, size=100)), t0 + 0.1 * i)
    for i in range(4):
        ch._observe(_frame(7.0 + i, _box(210.0, 91, size=150)), t0 + 0.6 + 0.1 * i)
    assert not ch._pieces[91].double_feed


def test_one_bigger_reading_is_not_growth() -> None:
    ch = _channel()
    t0 = time.monotonic()
    for i in range(6):
        ch._observe(_frame(1.0 + i, _box(210.0, 91)), t0 + 0.1 * i)
    ch._observe(_frame(7.0, _box(210.0, 91, size=135)), t0 + 0.6)
    ch._observe(_frame(8.0, _box(210.0, 91)), t0 + 0.7)
    assert not ch._pieces[91].double_feed
