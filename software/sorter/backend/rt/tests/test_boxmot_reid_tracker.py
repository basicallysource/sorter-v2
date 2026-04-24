"""Unit tests for the BoTSORT + OSNet ReID tracker adapter.

Heavy dependencies (torch, downloading ReID weights) are stubbed with a
``core_factory`` fake so the tests run in a few milliseconds and stay
independent of network or hardware.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from rt.contracts.detection import Detection, DetectionBatch
from rt.contracts.feed import FeedFrame
from rt.perception.trackers.boxmot_reid import BotSortReIDTracker


def _frame(seq: int, ts: float) -> FeedFrame:
    return FeedFrame(
        feed_id="c4_feed",
        camera_id="cam",
        raw=np.zeros((120, 160, 3), dtype=np.uint8),
        gray=None,
        timestamp=ts,
        monotonic_ts=ts,
        frame_seq=seq,
    )


def _batch(seq: int, ts: float, bboxes: list[tuple[int, int, int, int]]) -> DetectionBatch:
    dets = tuple(Detection(bbox_xyxy=b, score=0.9) for b in bboxes)
    return DetectionBatch(
        feed_id="c4_feed",
        frame_seq=seq,
        timestamp=ts,
        detections=dets,
        algorithm="test",
        latency_ms=0.0,
    )


class _FakeCore:
    """Minimal stand-in for boxmot's BoTSORT tracker.

    Returns one track per detection using row index as tracker id, and
    publishes a deterministic ``smooth_feat`` so the adapter can pick it up.
    """

    def __init__(self) -> None:
        self.active_tracks: list[SimpleNamespace] = []

    def update(self, dets: np.ndarray, img: np.ndarray) -> np.ndarray:
        if dets.shape[0] == 0:
            self.active_tracks = []
            return np.empty((0, 8), dtype=np.float32)
        rows: list[list[float]] = []
        self.active_tracks = []
        for idx, det in enumerate(dets):
            tid = idx + 1
            rows.append(
                [float(det[0]), float(det[1]), float(det[2]), float(det[3]), float(tid), float(det[4]), 0.0, float(idx)]
            )
            feat = np.array([0.1 * tid, 0.2 * tid, 0.3 * tid], dtype=np.float32)
            # ``STrack.id`` is what BoTSORT writes into row[4], not ``track_id``.
            self.active_tracks.append(
                SimpleNamespace(id=tid, track_id=tid, smooth_feat=feat, curr_feat=feat)
            )
        return np.asarray(rows, dtype=np.float32)


def _make_tracker() -> BotSortReIDTracker:
    return BotSortReIDTracker(
        polar_center=(80.0, 60.0),
        core_factory=lambda: _FakeCore(),
    )


def test_emits_track_with_appearance_embedding() -> None:
    tracker = _make_tracker()
    out = tracker.update(_batch(0, 1.0, [(10, 10, 50, 50)]), _frame(0, 1.0))
    assert len(out.tracks) == 1
    track = out.tracks[0]
    assert track.appearance_embedding is not None
    assert len(track.appearance_embedding) == 3
    # Tuple-of-floats, not ndarray — crosses the contract cleanly.
    assert isinstance(track.appearance_embedding, tuple)
    assert all(isinstance(v, float) for v in track.appearance_embedding)


def test_polar_geometry_attached_from_center() -> None:
    tracker = _make_tracker()
    out = tracker.update(_batch(0, 1.0, [(70, 50, 90, 70)]), _frame(0, 1.0))
    track = out.tracks[0]
    assert track.angle_rad is not None
    assert track.radius_px is not None


def test_local_id_is_stable_for_repeated_external_id() -> None:
    tracker = _make_tracker()
    first = tracker.update(_batch(0, 1.0, [(10, 10, 50, 50)]), _frame(0, 1.0))
    second = tracker.update(_batch(1, 1.1, [(12, 11, 52, 51)]), _frame(1, 1.1))
    assert first.tracks[0].global_id == second.tracks[0].global_id


def test_lost_track_ids_reported_when_detection_disappears() -> None:
    tracker = _make_tracker()
    tracker.update(_batch(0, 1.0, [(10, 10, 50, 50)]), _frame(0, 1.0))
    out = tracker.update(_batch(1, 1.1, []), _frame(1, 1.1))
    assert out.lost_track_ids == (1,)
    assert out.tracks == ()


def test_reset_clears_state() -> None:
    tracker = _make_tracker()
    tracker.update(_batch(0, 1.0, [(10, 10, 50, 50)]), _frame(0, 1.0))
    tracker.reset()
    assert tracker.live_global_ids() == set()


def test_handles_core_exception_gracefully() -> None:
    class _ExplodingCore:
        active_tracks: list = []

        def update(self, dets: np.ndarray, img: np.ndarray) -> np.ndarray:
            raise RuntimeError("boom")

    tracker = BotSortReIDTracker(core_factory=lambda: _ExplodingCore())
    out = tracker.update(_batch(0, 1.0, [(10, 10, 50, 50)]), _frame(0, 1.0))
    assert out.tracks == ()
    assert out.lost_track_ids == ()
