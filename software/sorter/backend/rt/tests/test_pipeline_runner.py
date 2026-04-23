from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import numpy as np

import rt.perception  # noqa: F401
from rt.contracts.detection import Detection, DetectionBatch, Detector
from rt.contracts.feed import FeedFrame, RectZone, Zone
from rt.contracts.filters import FilterChain
from rt.contracts.tracking import Track, TrackBatch, Tracker
from rt.events.bus import InProcessEventBus
from rt.events.topics import HARDWARE_ERROR, PERCEPTION_TRACKS
from rt.perception.pipeline import PerceptionPipeline
from rt.perception.pipeline_runner import PerceptionRunner


class _FakeFeed:
    feed_id = "fake"
    purpose = "c2_feed"
    camera_id = "cam"

    def __init__(self, frames_to_emit: int = 5) -> None:
        self._total = frames_to_emit
        self._seq = 0
        self.calls = 0
        self._lock = threading.Lock()

    def latest(self) -> FeedFrame | None:
        with self._lock:
            self.calls += 1
            self._seq += 1
            seq = self._seq
        return FeedFrame(
            feed_id=self.feed_id,
            camera_id=self.camera_id,
            raw=np.zeros((10, 10, 3), dtype=np.uint8),
            gray=None,
            timestamp=float(seq) * 0.01,
            monotonic_ts=time.monotonic(),
            frame_seq=seq,
        )

    def fps(self) -> float:
        return 100.0


class _NoopDetector:
    key = "noop"

    def requires(self) -> frozenset[str]:
        return frozenset()

    def detect(self, frame: FeedFrame, zone: Zone) -> DetectionBatch:
        return DetectionBatch(
            feed_id=frame.feed_id,
            frame_seq=frame.frame_seq,
            timestamp=frame.timestamp,
            detections=(),
            algorithm=self.key,
            latency_ms=0.0,
        )

    def reset(self) -> None:
        return None

    def stop(self) -> None:
        return None


class _NoopTracker:
    key = "noop"

    def update(self, detections: DetectionBatch, frame: FeedFrame) -> TrackBatch:
        return TrackBatch(
            feed_id=detections.feed_id,
            frame_seq=detections.frame_seq,
            timestamp=detections.timestamp,
            tracks=(),
            lost_track_ids=(),
        )

    def live_global_ids(self) -> set[int]:
        return set()

    def reset(self) -> None:
        return None


class _ExplodingDetector:
    key = "boom"

    def requires(self) -> frozenset[str]:
        return frozenset()

    def detect(self, frame: FeedFrame, zone: Zone) -> DetectionBatch:
        raise RuntimeError("kaboom")

    def reset(self) -> None:
        return None

    def stop(self) -> None:
        return None


def _build_pipeline(detector: Detector, tracker: Tracker, feed: _FakeFeed) -> PerceptionPipeline:
    return PerceptionPipeline(
        feed=feed,
        zone=RectZone(x=0, y=0, w=10, h=10),
        detector=detector,
        tracker=tracker,
        filters=FilterChain(()),
    )


def test_runner_processes_frames_and_publishes() -> None:
    feed = _FakeFeed()
    pipeline = _build_pipeline(_NoopDetector(), _NoopTracker(), feed)
    bus = InProcessEventBus()
    received: list = []
    bus.subscribe(PERCEPTION_TRACKS, received.append)
    bus.start()
    try:
        runner = PerceptionRunner(pipeline, period_ms=5, event_bus=bus)
        runner.start()
        time.sleep(0.1)
        runner.stop(timeout=1.0)
    finally:
        bus.stop()

    assert runner.latest_tracks() is not None
    # Runner should have seen multiple frames.
    assert feed.calls >= 3
    assert len(received) >= 1
    assert received[0].topic == PERCEPTION_TRACKS


def test_runner_stops_on_persistent_errors() -> None:
    feed = _FakeFeed()
    pipeline = _build_pipeline(_ExplodingDetector(), _NoopTracker(), feed)
    bus = InProcessEventBus()
    errors: list = []
    bus.subscribe(HARDWARE_ERROR, errors.append)
    bus.start()
    try:
        runner = PerceptionRunner(pipeline, period_ms=1, event_bus=bus)
        runner.start()
        # Wait long enough for 10 errors to accrue.
        time.sleep(0.3)
        # Ensure thread stopped itself.
        runner.stop(timeout=1.0)
    finally:
        bus.stop()

    assert len(errors) >= 1
    assert "kaboom" in errors[0].payload.get("error", "")


def test_runner_skips_duplicate_frame_seq() -> None:
    class _StickyFeed(_FakeFeed):
        def latest(self) -> FeedFrame | None:
            # Always returns seq=1 -> runner must dedupe.
            self.calls += 1
            return FeedFrame(
                feed_id=self.feed_id,
                camera_id=self.camera_id,
                raw=np.zeros((10, 10, 3), dtype=np.uint8),
                gray=None,
                timestamp=1.0,
                monotonic_ts=time.monotonic(),
                frame_seq=1,
            )

    feed = _StickyFeed()

    class _CountingTracker:
        key = "count"

        def __init__(self) -> None:
            self.calls = 0

        def update(self, detections, frame):
            self.calls += 1
            return TrackBatch(
                feed_id=frame.feed_id,
                frame_seq=frame.frame_seq,
                timestamp=frame.timestamp,
                tracks=(),
                lost_track_ids=(),
            )

        def live_global_ids(self):
            return set()

        def reset(self):
            return None

    tracker = _CountingTracker()
    pipeline = _build_pipeline(_NoopDetector(), tracker, feed)
    runner = PerceptionRunner(pipeline, period_ms=2)
    runner.start()
    time.sleep(0.1)
    runner.stop(timeout=1.0)

    assert feed.calls >= 3
    # Tracker should have been called exactly once (frame_seq=1 only).
    assert tracker.calls == 1


def test_runner_keeps_latest_unfiltered_snapshot() -> None:
    feed = _FakeFeed(frames_to_emit=1)

    class _Detector:
        key = "det"

        def requires(self) -> frozenset[str]:
            return frozenset()

        def detect(self, frame: FeedFrame, zone: Zone) -> DetectionBatch:
            return DetectionBatch(
                feed_id=frame.feed_id,
                frame_seq=frame.frame_seq,
                timestamp=frame.timestamp,
                detections=(Detection(bbox_xyxy=(1, 2, 6, 7), score=0.9),),
                algorithm=self.key,
                latency_ms=0.0,
            )

        def reset(self) -> None:
            return None

        def stop(self) -> None:
            return None

    class _Tracker:
        key = "trk"

        def update(self, detections: DetectionBatch, frame: FeedFrame) -> TrackBatch:
            return TrackBatch(
                feed_id=frame.feed_id,
                frame_seq=frame.frame_seq,
                timestamp=frame.timestamp,
                tracks=(
                    Track(
                        track_id=1,
                        global_id=1,
                        piece_uuid=None,
                        bbox_xyxy=(1, 2, 6, 7),
                        score=0.9,
                        confirmed_real=False,
                        angle_rad=0.0,
                        radius_px=10.0,
                        hit_count=1,
                        first_seen_ts=frame.timestamp,
                        last_seen_ts=frame.timestamp,
                    ),
                ),
                lost_track_ids=(),
            )

        def live_global_ids(self) -> set[int]:
            return {1}

        def reset(self) -> None:
            return None

    class _DropAllFilter:
        key = "drop_all"

        def apply(self, tracks: TrackBatch, frame: FeedFrame) -> TrackBatch:
            return TrackBatch(
                feed_id=tracks.feed_id,
                frame_seq=tracks.frame_seq,
                timestamp=tracks.timestamp,
                tracks=(),
                lost_track_ids=tracks.lost_track_ids,
            )

    pipeline = PerceptionPipeline(
        feed=feed,
        zone=RectZone(x=0, y=0, w=10, h=10),
        detector=_Detector(),
        tracker=_Tracker(),
        filters=FilterChain((_DropAllFilter(),)),
    )
    runner = PerceptionRunner(pipeline, period_ms=2)
    runner.start()
    time.sleep(0.05)
    runner.stop(timeout=1.0)

    latest = runner.latest_tracks()
    snapshot = runner.latest_state()
    assert latest is not None
    assert snapshot is not None
    assert len(latest.tracks) == 0
    assert len(snapshot.detections.detections) == 1
    assert len(snapshot.raw_tracks.tracks) == 1
    assert len(snapshot.filtered_tracks.tracks) == 0


def test_runner_status_snapshot_surfaces_debug_counts() -> None:
    class _StatusFeed:
        feed_id = "c2_feed"
        purpose = "c2_feed"
        camera_id = "cam"

        def latest(self) -> FeedFrame | None:
            return FeedFrame(
                feed_id=self.feed_id,
                camera_id=self.camera_id,
                raw=np.zeros((10, 10, 3), dtype=np.uint8),
                gray=None,
                timestamp=1.0,
                monotonic_ts=100.0,
                frame_seq=1,
            )

        def fps(self) -> float:
            return 100.0

    feed = _StatusFeed()
    pipeline = _build_pipeline(_NoopDetector(), _NoopTracker(), feed)
    runner = PerceptionRunner(pipeline, period_ms=2)
    runner._running = True
    runner._latest_state = SimpleNamespace(
        detections=SimpleNamespace(detections=(object(), object())),
        raw_tracks=TrackBatch(
            feed_id="c2_feed",
            frame_seq=1,
            timestamp=1.0,
            tracks=(
                Track(
                    track_id=1,
                    global_id=101,
                    piece_uuid=None,
                    bbox_xyxy=(0, 0, 10, 10),
                    score=0.9,
                    confirmed_real=False,
                    angle_rad=0.0,
                    radius_px=5.0,
                    hit_count=2,
                    first_seen_ts=0.5,
                    last_seen_ts=1.0,
                ),
                Track(
                    track_id=2,
                    global_id=102,
                    piece_uuid=None,
                    bbox_xyxy=(0, 0, 10, 10),
                    score=0.8,
                    confirmed_real=True,
                    angle_rad=0.5,
                    radius_px=5.0,
                    hit_count=3,
                    first_seen_ts=0.25,
                    last_seen_ts=1.0,
                ),
            ),
            lost_track_ids=(),
        ),
        filtered_tracks=TrackBatch(
            feed_id="c2_feed",
            frame_seq=1,
            timestamp=1.0,
            tracks=(
                Track(
                    track_id=2,
                    global_id=102,
                    piece_uuid=None,
                    bbox_xyxy=(0, 0, 10, 10),
                    score=0.8,
                    confirmed_real=True,
                    angle_rad=0.5,
                    radius_px=5.0,
                    hit_count=3,
                    first_seen_ts=0.25,
                    last_seen_ts=1.0,
                ),
            ),
            lost_track_ids=(),
        ),
    )

    snapshot = runner.status_snapshot(now_mono=100.25)

    assert snapshot["feed_id"] == "c2_feed"
    assert snapshot["detector_slug"] == "noop"
    assert snapshot["zone_kind"] == "rect"
    assert snapshot["running"] is True
    assert snapshot["period_ms"] == 2
    assert snapshot["last_frame_age_ms"] == 250.0
    assert snapshot["detection_count"] == 2
    assert snapshot["raw_track_count"] == 2
    assert snapshot["confirmed_track_count"] == 1
    assert snapshot["confirmed_real_track_count"] == 1
    assert snapshot["raw_track_preview"][0]["global_id"] == 101
    assert snapshot["confirmed_track_preview"][0]["global_id"] == 102
