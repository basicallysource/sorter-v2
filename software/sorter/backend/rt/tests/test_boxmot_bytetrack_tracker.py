from __future__ import annotations

import numpy as np

from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.feed import FeedFrame
from rt.contracts.registry import TRACKERS
from rt.perception.trackers.boxmot_bytetrack import BoxMotByteTrackTracker


def _frame(seq: int, ts: float) -> FeedFrame:
    return FeedFrame(
        feed_id="c3_feed",
        camera_id="cam",
        raw=np.zeros((120, 160, 3), dtype=np.uint8),
        gray=None,
        timestamp=ts,
        monotonic_ts=ts,
        frame_seq=seq,
    )


def _batch(seq: int, ts: float, bbox: tuple[int, int, int, int] | None) -> DetectionBatch:
    dets = () if bbox is None else (Detection(bbox_xyxy=bbox, score=0.9),)
    return DetectionBatch(
        feed_id="c3_feed",
        frame_seq=seq,
        timestamp=ts,
        detections=dets,
        algorithm="test",
        latency_ms=0.0,
    )


class _FakeByteTrackCore:
    def update(self, dets: np.ndarray, img: np.ndarray) -> np.ndarray:
        if dets.shape[0] == 0:
            return np.empty((0, 8), dtype=np.float32)
        det = dets[0]
        return np.asarray(
            [[det[0], det[1], det[2], det[3], 42.0, det[4], 0.0, 0.0]],
            dtype=np.float32,
        )


def _tracker() -> BoxMotByteTrackTracker:
    return BoxMotByteTrackTracker(
        polar_center=(80.0, 60.0),
        core_factory=lambda: _FakeByteTrackCore(),
    )


def test_boxmot_bytetrack_registered() -> None:
    assert "boxmot_bytetrack" in TRACKERS.keys()


def test_emits_sorter_native_tracks_without_embedding() -> None:
    tracker = _tracker()

    out = tracker.update(_batch(0, 1.0, (70, 50, 90, 70)), _frame(0, 1.0))

    assert len(out.tracks) == 1
    track = out.tracks[0]
    assert track.global_id == 1
    assert track.angle_rad is not None
    assert track.radius_px is not None
    assert track.appearance_embedding is None


def test_reports_lost_local_track_ids() -> None:
    tracker = _tracker()
    tracker.update(_batch(0, 1.0, (70, 50, 90, 70)), _frame(0, 1.0))

    out = tracker.update(_batch(1, 1.1, None), _frame(1, 1.1))

    assert out.tracks == ()
    assert out.lost_track_ids == (1,)
