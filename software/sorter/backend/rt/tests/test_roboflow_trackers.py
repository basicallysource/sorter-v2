from __future__ import annotations

import numpy as np
import pytest

import rt.perception  # noqa: F401 - trigger tracker registration
from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import TRACKERS
from rt.perception.trackers.roboflow import (
    RoboflowByteTrackTracker,
    RoboflowOCSORTTracker,
    RoboflowSORTTracker,
)


TRACKER_CASES = (
    ("rf_sort", RoboflowSORTTracker),
    ("rf_bytetrack", RoboflowByteTrackTracker),
    ("rf_ocsort", RoboflowOCSORTTracker),
)


def _frame(seq: int, ts: float) -> FeedFrame:
    return FeedFrame(
        feed_id="f",
        camera_id="c",
        raw=np.zeros((240, 320, 3), dtype=np.uint8),
        gray=None,
        timestamp=ts,
        monotonic_ts=ts,
        frame_seq=seq,
    )


def _batch(
    bbox: tuple[int, int, int, int] | None,
    seq: int,
    ts: float,
    *,
    score: float = 0.9,
) -> DetectionBatch:
    detections = () if bbox is None else (Detection(bbox_xyxy=bbox, score=score),)
    return DetectionBatch(
        feed_id="f",
        frame_seq=seq,
        timestamp=ts,
        detections=detections,
        algorithm="test",
        latency_ms=0.0,
    )


def test_roboflow_trackers_are_registered() -> None:
    keys = TRACKERS.keys()
    assert "rf_sort" in keys
    assert "rf_bytetrack" in keys
    assert "rf_ocsort" in keys


@pytest.mark.parametrize(("key", "tracker_cls"), TRACKER_CASES)
def test_roboflow_tracker_keeps_stable_local_id_and_confirms_motion(
    key: str,
    tracker_cls: type,
) -> None:
    trk = tracker_cls(
        polar_center=None,
        minimum_iou_threshold=0.05,
        minimum_consecutive_frames=1,
    )
    trk.register_rotation_window(0.0, 100.0)

    seen_ids: list[int] = []
    last = None
    for i in range(22):
        x = 40 + i * 4
        bbox = (x, 80, x + 40, 120)
        ts = 1.0 + i * 0.1
        last = trk.update(_batch(bbox, i, ts), _frame(i, ts))
        if last.tracks:
            seen_ids.append(last.tracks[0].track_id)

    assert key in TRACKERS.keys()
    assert seen_ids
    assert len(set(seen_ids)) == 1
    assert last is not None
    assert last.tracks
    assert last.tracks[0].global_id == last.tracks[0].track_id
    assert last.tracks[0].confirmed_real is True
    assert last.tracks[0].ghost is False


@pytest.mark.parametrize(("key", "tracker_cls"), TRACKER_CASES)
def test_roboflow_tracker_marks_stationary_track_as_ghost_during_rotation(
    key: str,
    tracker_cls: type,
) -> None:
    trk = tracker_cls(minimum_iou_threshold=0.05, minimum_consecutive_frames=1)
    trk.register_rotation_window(0.0, 100.0)

    last = None
    for i in range(24):
        ts = 1.0 + i * 0.1
        last = trk.update(_batch((80, 80, 120, 120), i, ts), _frame(i, ts))

    assert key in TRACKERS.keys()
    assert last is not None
    assert last.tracks
    assert last.tracks[0].confirmed_real is False
    assert last.tracks[0].ghost is True


@pytest.mark.parametrize(("key", "tracker_cls"), TRACKER_CASES)
def test_roboflow_confirmed_track_does_not_flip_back_to_ghost_while_waiting(
    key: str,
    tracker_cls: type,
) -> None:
    trk = tracker_cls(
        polar_center=None,
        minimum_iou_threshold=0.05,
        minimum_consecutive_frames=1,
    )
    trk.register_rotation_window(0.0, 100.0)

    last = None
    for i in range(22):
        x = 40 + i * 4
        ts = 1.0 + i * 0.1
        last = trk.update(_batch((x, 80, x + 40, 120), i, ts), _frame(i, ts))

    assert key in TRACKERS.keys()
    assert last is not None
    assert last.tracks
    assert last.tracks[0].confirmed_real is True
    stable_bbox = last.tracks[0].bbox_xyxy

    for i in range(22, 52):
        ts = 1.0 + i * 0.1
        last = trk.update(_batch(stable_bbox, i, ts), _frame(i, ts))

    assert last is not None
    assert last.tracks
    assert last.tracks[0].confirmed_real is True
    assert last.tracks[0].ghost is False


@pytest.mark.parametrize(("key", "tracker_cls"), TRACKER_CASES)
def test_roboflow_tracker_keeps_pending_without_rotation_window(
    key: str,
    tracker_cls: type,
) -> None:
    trk = tracker_cls(minimum_iou_threshold=0.05, minimum_consecutive_frames=1)

    last = None
    for i in range(10):
        ts = 1.0 + i * 0.1
        last = trk.update(_batch((80, 80, 120, 120), i, ts), _frame(i, ts))

    assert key in TRACKERS.keys()
    assert last is not None
    assert last.tracks
    assert last.tracks[0].confirmed_real is False
    assert last.tracks[0].ghost is False


@pytest.mark.parametrize(("key", "tracker_cls"), TRACKER_CASES)
def test_roboflow_tracker_reset_clears_local_ids(
    key: str,
    tracker_cls: type,
) -> None:
    trk = tracker_cls(minimum_iou_threshold=0.05, minimum_consecutive_frames=1)
    for i in range(4):
        ts = 1.0 + i * 0.1
        trk.update(_batch((80, 80, 120, 120), i, ts), _frame(i, ts))

    assert key in TRACKERS.keys()
    assert trk.live_global_ids()
    trk.reset()
    assert trk.live_global_ids() == set()


def test_roboflow_tracker_exposes_ring_geometry() -> None:
    trk = RoboflowByteTrackTracker(
        polar_center=(100.0, 120.0),
        polar_radius_range=(30.0, 90.0),
    )
    assert trk.ring_geometry() == {
        "center_x": 100.0,
        "center_y": 120.0,
        "inner_radius": 30.0,
        "outer_radius": 90.0,
    }
