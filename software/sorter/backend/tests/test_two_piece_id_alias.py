"""A second track id on the same box is the same piece.

Regression (2026-09-05 00:50): the tracker flipped between ids 5 and 6 on one
piece; id 5 became an uncaptured 'stray' head sent to misc while the
classified twin (6) was aimed for its bin.
"""
import logging
from types import SimpleNamespace

from subsystems.classification_channel.two_piece import (
    TwoPieceClassificationChannel,
    _TrackedPiece,
    _ZONE_DROP,
    _ZONE_NONE,
    _bboxIou,
)


def _handler():
    h = object.__new__(TwoPieceClassificationChannel)
    h._pieces = {}
    h._orphans = []
    h._aliases = {}
    h.logger = logging.getLogger("test")
    h._multi_drop_streak = 0
    h._multi_drop_last_ts = -1.0
    h._multi_drop_seq = 0
    h.ctx = SimpleNamespace(config=SimpleNamespace(multi_feed_confirm_reads=3))
    h.noteProgress = lambda: None
    h.created = []
    def create(tid, now):
        tp = object.__new__(_TrackedPiece)
        tp.track_id = tid; tp.zone = _ZONE_NONE; tp.bbox = (0, 0, 0, 0); tp.gap_to_exit = None
        tp.progress_gap = None; tp.created_at = now; tp.last_seen = now
        tp.capture_done = tp.result_applied = tp.placed = tp.double_feed = tp.ejected = False
        tp.multi_drop_group = None; tp.worker = SimpleNamespace(abandonInFlightObject=lambda r: None)
        h._pieces[tid] = tp; h.created.append(tid); return tp
    h._createPiece = create
    return h


def _obs(ts, *items):
    return SimpleNamespace(ts=ts, pieces=[SimpleNamespace(sv_bt_track_id=t, zone_code=z, bbox=b, com_forward_to_exit_deg=None) for t, z, b in items])


def test_second_id_on_overlapping_box_is_aliased_not_created() -> None:
    h = _handler()
    h._observe(_obs(1.0, (6, _ZONE_DROP, (600, 800, 700, 900))), now=1.0)
    h._observe(_obs(1.2, (5, _ZONE_DROP, (605, 805, 705, 905))), now=1.2)
    assert h.created == [6]
    assert 5 in h._aliases and h._aliases[5] is h._pieces[6]
    assert len(h._pieces) == 1
    # later frames under the alias keep updating the same piece
    h._observe(_obs(1.5, (5, _ZONE_NONE, (1400, 500, 1500, 600))), now=1.5)
    assert h._pieces[6].zone == _ZONE_NONE and h._pieces[6].last_seen == 1.5


def test_distinct_boxes_are_distinct_pieces() -> None:
    h = _handler()
    h._observe(_obs(1.0, (1, _ZONE_DROP, (600, 800, 700, 900))), now=1.0)
    h._observe(_obs(1.2, (2, _ZONE_DROP, (900, 800, 1000, 900))), now=1.2)
    assert h.created == [1, 2]


def test_iou() -> None:
    assert _bboxIou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert _bboxIou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert 0.3 < _bboxIou((0, 0, 10, 10), (5, 0, 15, 10)) < 0.35


def test_new_forward_id_without_overlap_binds_to_the_nearest_forward_piece() -> None:
    h = _handler()
    h._observe(_obs(1.0, (6, _ZONE_NONE, (1400, 500, 1500, 600))), now=1.0)
    h._pieces[6].capture_done = True
    # twin box next to it, no overlap, appears forward
    h._observe(_obs(1.3, (5, _ZONE_NONE, (1510, 505, 1600, 590))), now=1.3)
    assert h.created == [6]
    assert h._aliases[5] is h._pieces[6]


def test_new_id_in_drop_never_binds_by_proximity() -> None:
    h = _handler()
    h._observe(_obs(1.0, (1, _ZONE_DROP, (600, 800, 700, 900))), now=1.0)
    h._observe(_obs(1.3, (2, _ZONE_DROP, (720, 800, 820, 900))), now=1.3)
    assert h.created == [1, 2]


def test_far_forward_detection_is_not_the_previous_piece() -> None:
    h = _handler()
    h._observe(_obs(1.0, (1, _ZONE_NONE, (100, 100, 150, 150))), now=1.0)
    h._observe(_obs(1.1, (2, _ZONE_NONE, (1500, 800, 1550, 850))), now=1.1)
    assert h.created == [1, 2]


def test_separately_visible_neighbour_is_not_aliased_in_either_order() -> None:
    for reverse in (False, True):
        h = _handler()
        old = (1, _ZONE_NONE, (100, 100, 150, 150))
        other = (2, _ZONE_NONE, (155, 100, 205, 150))
        h._observe(_obs(1.0, old), now=1.0)
        h._observe(_obs(1.1, *((other, old) if reverse else (old, other))), now=1.1)
        assert h.created == [1, 2]


def test_ambiguous_reidentification_does_not_choose_a_bin_identity() -> None:
    h = _handler()
    # Create in DROP, where distinct boxes never bind by proximity.
    h._observe(_obs(1.0, (1, _ZONE_DROP, (100, 100, 150, 150)),
                   (2, _ZONE_DROP, (200, 100, 250, 150))), now=1.0)
    for tp in h._pieces.values():
        tp.zone = _ZONE_NONE
    h._observe(_obs(1.1, (3, _ZONE_NONE, (150, 100, 200, 150))), now=1.1)
    assert h.created == [1, 2, 3]
