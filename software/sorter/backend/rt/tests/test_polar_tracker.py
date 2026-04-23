from __future__ import annotations

import math

import numpy as np

import rt.perception  # noqa: F401 - trigger tracker registration
from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import TRACKERS
from rt.perception.trackers.polar import PolarTracker


def _frame(seq: int, ts: float) -> FeedFrame:
    return FeedFrame(
        feed_id="f",
        camera_id="c",
        raw=np.zeros((10, 10, 3), dtype=np.uint8),
        gray=None,
        timestamp=ts,
        monotonic_ts=ts,
        frame_seq=seq,
    )


def _batch(bbox: tuple[int, int, int, int], seq: int, ts: float) -> DetectionBatch:
    return DetectionBatch(
        feed_id="f",
        frame_seq=seq,
        timestamp=ts,
        detections=(Detection(bbox_xyxy=bbox, score=0.9),),
        algorithm="test",
        latency_ms=1.0,
    )


def test_polar_registered_in_registry() -> None:
    assert "polar" in TRACKERS.keys()


def test_cartesian_fallback_keeps_consistent_track_id() -> None:
    trk = PolarTracker(polar_center=None, pixel_fallback_distance_px=50.0)
    # A rotation window covering the whole test sequence — confirmed_real is
    # only evaluated on samples observed during a known rotation.
    trk.register_rotation_window(0.0, 100.0)

    track_ids = []
    batch = None
    # 14 * 10 px = 140 px total; head median near 120, tail median near 220
    # -> centroid drift ~100 px >= 40 px threshold.
    for i in range(14):
        x = 100 + i * 10
        bbox = (x, 100, x + 20, 120)
        ts = 1.0 + i * 0.1
        batch = trk.update(_batch(bbox, seq=i, ts=ts), _frame(i, ts))
        assert len(batch.tracks) == 1
        track_ids.append(batch.tracks[0].track_id)

    # Stable id across the whole sequence.
    assert len(set(track_ids)) == 1
    assert batch is not None
    final = batch.tracks[0]
    assert final.confirmed_real is True
    assert final.hit_count == 14
    assert final.global_id == final.track_id


def test_polar_mode_confirms_on_angular_progress() -> None:
    center = (100.0, 100.0)
    radius = 60.0
    trk = PolarTracker(
        polar_center=center,
        polar_radius_range=(40.0, 80.0),
        max_angular_step_deg=20.0,
        max_radial_step_px=40.0,
    )
    trk.register_rotation_window(0.0, 100.0)

    last_batch = None
    for i in range(10):
        # Walk 2 deg per tick around the ring -> ~18 deg total >> 5 deg.
        theta = math.radians(i * 2.0)
        cx = center[0] + radius * math.cos(theta)
        cy = center[1] + radius * math.sin(theta)
        bbox = (int(cx - 5), int(cy - 5), int(cx + 5), int(cy + 5))
        ts = 1.0 + i * 0.1
        last_batch = trk.update(_batch(bbox, seq=i, ts=ts), _frame(i, ts))

    assert last_batch is not None
    assert len(last_batch.tracks) == 1
    t = last_batch.tracks[0]
    assert t.confirmed_real is True
    assert t.angle_rad is not None
    assert t.radius_px is not None
    # Radius should stay near the ring.
    assert abs(t.radius_px - radius) < 10.0


def test_track_pending_without_rotation_window() -> None:
    # Without a registered rotation window, a stationary track is neither
    # confirmed nor declared a ghost: the tracker has no basis to judge.
    trk = PolarTracker(polar_center=None, pixel_fallback_distance_px=50.0)
    last = None
    for i in range(20):
        bbox = (100, 100, 120, 120)  # no motion
        ts = 1.0 + i * 0.1
        last = trk.update(_batch(bbox, seq=i, ts=ts), _frame(i, ts))
    assert last is not None
    t = last.tracks[0]
    assert t.confirmed_real is False
    assert t.ghost is False


def test_stationary_track_during_rotation_becomes_ghost() -> None:
    trk = PolarTracker(polar_center=None, pixel_fallback_distance_px=50.0)
    trk.register_rotation_window(0.0, 100.0)
    last = None
    for i in range(20):
        bbox = (100, 100, 120, 120)  # no motion during a known rotation
        ts = 1.0 + i * 0.1
        last = trk.update(_batch(bbox, seq=i, ts=ts), _frame(i, ts))
    assert last is not None
    t = last.tracks[0]
    assert t.confirmed_real is False
    assert t.ghost is True


def test_confirmed_track_does_not_flip_back_to_ghost_while_waiting() -> None:
    trk = PolarTracker(polar_center=None, pixel_fallback_distance_px=50.0)
    trk.register_rotation_window(0.0, 100.0)

    last = None
    for i in range(14):
        x = 100 + i * 10
        ts = 1.0 + i * 0.1
        last = trk.update(_batch((x, 100, x + 20, 120), seq=i, ts=ts), _frame(i, ts))

    assert last is not None
    assert last.tracks[0].confirmed_real is True
    stable_bbox = last.tracks[0].bbox_xyxy

    for i in range(14, 40):
        ts = 1.0 + i * 0.1
        last = trk.update(_batch(stable_bbox, seq=i, ts=ts), _frame(i, ts))

    assert last is not None
    t = last.tracks[0]
    assert t.confirmed_real is True
    assert t.ghost is False


def test_rotation_window_outside_samples_keeps_pending() -> None:
    # Rotation window ends before the first sample arrives → no sample
    # counts as during-rotation → track stays pending.
    trk = PolarTracker(polar_center=None, pixel_fallback_distance_px=50.0)
    trk.register_rotation_window(0.0, 0.5)
    last = None
    for i in range(10):
        bbox = (100, 100, 120, 120)
        ts = 1.0 + i * 0.1
        last = trk.update(_batch(bbox, seq=i, ts=ts), _frame(i, ts))
    assert last is not None
    t = last.tracks[0]
    assert t.confirmed_real is False
    assert t.ghost is False


def test_track_is_not_confirmed_after_few_samples() -> None:
    trk = PolarTracker(polar_center=None)
    # Three detections with tiny drift -> not confirmed.
    for i in range(3):
        x = 100 + i  # 1 px steps, far below 40 px gate
        bbox = (x, 100, x + 20, 120)
        ts = 1.0 + i * 0.1
        batch = trk.update(_batch(bbox, seq=i, ts=ts), _frame(i, ts))

    assert len(batch.tracks) == 1
    assert batch.tracks[0].confirmed_real is False


def test_track_expires_after_coast_limit() -> None:
    trk = PolarTracker(polar_center=None, coast_limit_ticks=2)
    bbox = (100, 100, 120, 120)
    trk.update(_batch(bbox, seq=0, ts=1.0), _frame(0, 1.0))
    # Feed empty detection batches -> track coasts and eventually dies.
    for i in range(1, 6):
        empty = DetectionBatch(
            feed_id="f",
            frame_seq=i,
            timestamp=1.0 + i * 0.1,
            detections=(),
            algorithm="test",
            latency_ms=0.0,
        )
        batch = trk.update(empty, _frame(i, 1.0 + i * 0.1))

    # After coast_limit=2 plus some margin, track must be gone.
    assert trk.live_global_ids() == set()
    assert 1 in batch.lost_track_ids or len(batch.tracks) == 0


def test_reset_clears_tracks() -> None:
    trk = PolarTracker(polar_center=None)
    trk.update(_batch((10, 10, 20, 20), seq=0, ts=1.0), _frame(0, 1.0))
    assert len(trk.live_global_ids()) == 1
    trk.reset()
    assert trk.live_global_ids() == set()
