from __future__ import annotations

import math

import numpy as np

import rt.perception  # noqa: F401 - trigger tracker registration
from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import TRACKERS
from rt.perception.trackers.turntable_groundplane import TurntableGroundplaneTracker


def _frame(seq: int, ts: float) -> FeedFrame:
    return FeedFrame(
        feed_id="f",
        camera_id="c",
        raw=np.zeros((200, 200, 3), dtype=np.uint8),
        gray=None,
        timestamp=ts,
        monotonic_ts=ts,
        frame_seq=seq,
    )


def _batch(
    bboxes: tuple[tuple[int, int, int, int], ...],
    *,
    seq: int,
    ts: float,
) -> DetectionBatch:
    return DetectionBatch(
        feed_id="f",
        frame_seq=seq,
        timestamp=ts,
        detections=tuple(Detection(bbox_xyxy=bbox, score=0.9) for bbox in bboxes),
        algorithm="test",
        latency_ms=1.0,
    )


def test_groundplane_registered_in_registry() -> None:
    assert "turntable_groundplane" in TRACKERS.keys()


def test_groundplane_keeps_consistent_track_id_on_arc_motion() -> None:
    center = (100.0, 100.0)
    radius = 50.0
    tracker = TurntableGroundplaneTracker(
        polar_center=center,
        polar_radius_range=(30.0, 80.0),
        max_step_px=80.0,
        max_angular_step_deg=35.0,
        min_hits=2,
    )
    tracker.register_rotation_window(0.0, 100.0)

    track_ids: list[int] = []
    last = None
    for i in range(8):
        theta = math.radians(i * 4.0)
        cx = center[0] + radius * math.cos(theta)
        cy = center[1] + radius * math.sin(theta)
        bbox = (int(cx - 6), int(cy - 6), int(cx + 6), int(cy + 6))
        ts = 1.0 + i * 0.1
        last = tracker.update(_batch((bbox,), seq=i, ts=ts), _frame(i, ts))
        assert len(last.tracks) == 1
        track_ids.append(last.tracks[0].track_id)

    assert len(set(track_ids)) == 1
    assert last is not None
    final = last.tracks[0]
    assert final.confirmed_real is True
    assert final.angle_rad is not None
    assert final.radius_px is not None
    assert tracker.observed_rpm() is not None


def test_groundplane_merges_close_duplicate_births() -> None:
    tracker = TurntableGroundplaneTracker(
        polar_center=None,
        duplicate_merge_distance_px=30.0,
        duplicate_merge_iou=0.3,
    )
    batch = tracker.update(
        _batch(((50, 50, 80, 80), (54, 52, 84, 82)), seq=1, ts=1.0),
        _frame(1, 1.0),
    )

    assert len(batch.tracks) == 1
    assert len(batch.lost_track_ids) == 1


def test_groundplane_track_stays_pending_without_rotation_window() -> None:
    tracker = TurntableGroundplaneTracker(polar_center=None)

    last = None
    for i in range(20):
        bbox = (50, 50, 70, 70)
        ts = 1.0 + i * 0.1
        last = tracker.update(_batch((bbox,), seq=i, ts=ts), _frame(i, ts))

    assert last is not None
    assert len(last.tracks) == 1
    assert last.tracks[0].confirmed_real is False
    assert last.tracks[0].ghost is False


def test_groundplane_stationary_track_during_rotation_becomes_ghost() -> None:
    tracker = TurntableGroundplaneTracker(polar_center=None)
    tracker.register_rotation_window(0.0, 100.0)

    last = None
    for i in range(20):
        bbox = (50, 50, 70, 70)
        ts = 1.0 + i * 0.1
        last = tracker.update(_batch((bbox,), seq=i, ts=ts), _frame(i, ts))

    assert last is not None
    assert len(last.tracks) == 1
    assert last.tracks[0].confirmed_real is False
    assert last.tracks[0].ghost is True


def test_groundplane_rotation_window_outside_samples_keeps_pending() -> None:
    tracker = TurntableGroundplaneTracker(polar_center=None)
    tracker.register_rotation_window(0.0, 0.5)

    last = None
    for i in range(10):
        bbox = (50, 50, 70, 70)
        ts = 1.0 + i * 0.1
        last = tracker.update(_batch((bbox,), seq=i, ts=ts), _frame(i, ts))

    assert last is not None
    assert len(last.tracks) == 1
    assert last.tracks[0].confirmed_real is False
    assert last.tracks[0].ghost is False


def test_groundplane_few_hits_do_not_confirm_without_motion_evidence() -> None:
    tracker = TurntableGroundplaneTracker(polar_center=None, min_hits=2)
    tracker.register_rotation_window(0.0, 100.0)

    for i in range(3):
        bbox = (50 + i, 50, 70 + i, 70)
        ts = 1.0 + i * 0.1
        batch = tracker.update(_batch((bbox,), seq=i, ts=ts), _frame(i, ts))

    assert len(batch.tracks) == 1
    assert batch.tracks[0].hit_count == 3
    assert batch.tracks[0].confirmed_real is False
    assert batch.tracks[0].ghost is False


def test_groundplane_expires_after_coast_limit() -> None:
    tracker = TurntableGroundplaneTracker(polar_center=None, coast_limit_ticks=1)
    tracker.update(_batch(((50, 50, 70, 70),), seq=1, ts=1.0), _frame(1, 1.0))

    empty = _batch((), seq=2, ts=1.1)
    first_coast = tracker.update(empty, _frame(2, 1.1))
    assert len(first_coast.tracks) == 1

    expired = tracker.update(_batch((), seq=3, ts=1.2), _frame(3, 1.2))
    assert expired.tracks == ()
    assert 1 in expired.lost_track_ids
