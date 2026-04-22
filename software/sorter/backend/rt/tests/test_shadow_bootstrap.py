"""Unit tests for rt.shadow.bootstrap.build_shadow_runner_from_live.

These use a fake camera_service + fake vision_manager (both purely
duck-typed) so we don't pull in the real vision stack. A test-only
``noop`` detector is registered in the DETECTORS registry up front and
passed via ``detector_slug`` to avoid depending on actual Hive ONNX
artifacts.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import numpy as np
import pytest

import rt.perception  # noqa: F401 - register built-in strategies
from rt.contracts.detection import DetectionBatch
from rt.contracts.feed import FeedFrame, Zone
from rt.contracts.registry import DETECTORS
from rt.events.bus import InProcessEventBus
from rt.events.topics import PERCEPTION_TRACKS
from rt.shadow.bootstrap import build_shadow_runner_from_live
from rt.shadow.iou import RollingIouTracker


# ---------------------------------------------------------------------------
# A stable "noop" detector we register once for the whole module.
# ---------------------------------------------------------------------------


_TEST_DETECTOR_SLUG = "test:shadow-noop"


class _NoopDetector:
    key = _TEST_DETECTOR_SLUG

    def requires(self):
        return frozenset({"raw"})

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


def _register_noop_detector_once() -> None:
    try:
        DETECTORS.register(_TEST_DETECTOR_SLUG, lambda **_: _NoopDetector())
    except ValueError:
        # Already registered by a previous test — fine.
        pass


_register_noop_detector_once()


# ---------------------------------------------------------------------------
# Fakes for camera_service + vision_manager.
# ---------------------------------------------------------------------------


@dataclass
class _FakeCapture:
    latest_frame: object | None


@dataclass
class _FakeCameraFrame:
    raw: np.ndarray
    timestamp: float


class _FakeCameraFeed:
    def __init__(self, raw: np.ndarray) -> None:
        self._raw = raw

    def get_frame(self, annotated: bool = False) -> _FakeCameraFrame:
        return _FakeCameraFrame(raw=self._raw, timestamp=time.time())


class _FakeCameraService:
    def __init__(self, raw: np.ndarray) -> None:
        self._raw = raw
        self._lock = threading.Lock()

    def get_capture_thread_for_role(self, role: str) -> _FakeCapture:
        return _FakeCapture(latest_frame=_FakeCameraFrame(raw=self._raw, timestamp=time.time()))

    def get_feed(self, role: str) -> _FakeCameraFeed:
        return _FakeCameraFeed(self._raw)


class _FakeVisionManager:
    """Minimal VisionManager surface the bootstrap actually reads."""

    def __init__(self, polygon_key: str | None, polygon_vertices: list[tuple[int, int]] | None) -> None:
        self._polygon_key = polygon_key
        self._polygon_vertices = polygon_vertices
        self._tracks: list[object] = []

    # VisionManager API used by bootstrap._load_zone_from_vision_manager
    def _channelPolygonKeyForRole(self, role: str) -> str | None:
        return self._polygon_key

    def _loadSavedPolygon(self, key: str, w: int, h: int) -> np.ndarray | None:
        if self._polygon_vertices is None:
            return None
        return np.asarray(self._polygon_vertices, dtype=np.int32)

    # VisionManager API used by bootstrap._legacy_tracks_for_role
    def getFeederTracks(self, role: str) -> list[object]:
        return list(self._tracks)

    def set_tracks(self, tracks: list[object]) -> None:
        self._tracks = list(tracks)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _raw_frame(h: int = 480, w: int = 640) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def test_build_returns_none_when_camera_not_ready() -> None:
    camera_service = _FakeCameraService(np.zeros((0, 0, 3), dtype=np.uint8))

    # Force no raw frame on either path
    def _no_capture(role: str) -> _FakeCapture:
        return _FakeCapture(latest_frame=None)

    def _no_feed(role: str):
        return None

    camera_service.get_capture_thread_for_role = _no_capture  # type: ignore[assignment]
    camera_service.get_feed = _no_feed  # type: ignore[assignment]

    vm = _FakeVisionManager(polygon_key="second_channel", polygon_vertices=None)
    bus = InProcessEventBus()
    runner = build_shadow_runner_from_live(
        "c2",
        camera_service,
        vm,
        bus,
        detector_slug=_TEST_DETECTOR_SLUG,
    )
    assert runner is None


def test_build_with_polygon_zone_succeeds() -> None:
    raw = _raw_frame()
    camera_service = _FakeCameraService(raw)
    vm = _FakeVisionManager(
        polygon_key="second_channel",
        polygon_vertices=[(10, 10), (100, 10), (100, 80), (10, 80)],
    )
    bus = InProcessEventBus()
    runner = build_shadow_runner_from_live(
        "c2",
        camera_service,
        vm,
        bus,
        detector_slug=_TEST_DETECTOR_SLUG,
    )
    assert runner is not None
    # Pipeline wiring sanity: runner is not running yet but owns a pipeline.
    assert hasattr(runner, "start")
    assert hasattr(runner, "stop")
    assert runner.latest_tracks() is None


def test_build_falls_back_to_rect_zone_when_polygon_missing() -> None:
    raw = _raw_frame(240, 320)
    camera_service = _FakeCameraService(raw)
    vm = _FakeVisionManager(polygon_key=None, polygon_vertices=None)
    bus = InProcessEventBus()
    runner = build_shadow_runner_from_live(
        "c2",
        camera_service,
        vm,
        bus,
        detector_slug=_TEST_DETECTOR_SLUG,
    )
    # RectZone fallback should still produce a working runner.
    assert runner is not None


def test_runner_is_startable_and_publishes_tracks() -> None:
    raw = _raw_frame()
    camera_service = _FakeCameraService(raw)
    vm = _FakeVisionManager(
        polygon_key="second_channel",
        polygon_vertices=[(10, 10), (100, 10), (100, 80), (10, 80)],
    )
    bus = InProcessEventBus()
    received: list = []
    bus.subscribe(PERCEPTION_TRACKS, received.append)
    bus.start()
    try:
        runner = build_shadow_runner_from_live(
            "c2",
            camera_service,
            vm,
            bus,
            detector_slug=_TEST_DETECTOR_SLUG,
            period_ms=10,
        )
        assert runner is not None
        runner.start()
        time.sleep(0.15)
        runner.stop(timeout=1.0)
    finally:
        bus.stop()
    assert runner.latest_tracks() is not None
    assert any(ev.topic == PERCEPTION_TRACKS for ev in received)


def test_iou_tracker_is_wired_and_records_parity() -> None:
    raw = _raw_frame()
    camera_service = _FakeCameraService(raw)
    vm = _FakeVisionManager(
        polygon_key="second_channel",
        polygon_vertices=[(10, 10), (100, 10), (100, 80), (10, 80)],
    )
    bus = InProcessEventBus()
    iou = RollingIouTracker(window_sec=5.0)
    bus.start()
    try:
        runner = build_shadow_runner_from_live(
            "c2",
            camera_service,
            vm,
            bus,
            detector_slug=_TEST_DETECTOR_SLUG,
            iou_tracker=iou,
            period_ms=10,
        )
        assert runner is not None
        runner.start()
        # Allow several ticks so the EventBus subscriber can record samples.
        time.sleep(0.2)
        runner.stop(timeout=1.0)
    finally:
        bus.stop()

    # Both tracker sets are empty → IoU = 1.0 per tick.
    assert iou.sample_count() >= 1
    assert iou.mean_iou() == pytest.approx(1.0)


def test_unknown_role_maps_through_default() -> None:
    # Unknown role is still a string and has a FeedPurpose fallback. Bootstrap
    # should not crash — just return None because no polygon & no frame.
    camera_service = _FakeCameraService(np.zeros((0, 0, 3), dtype=np.uint8))

    def _no_capture(role: str):
        return _FakeCapture(latest_frame=None)

    camera_service.get_capture_thread_for_role = _no_capture  # type: ignore[assignment]
    camera_service.get_feed = lambda role: None  # type: ignore[assignment]
    vm = _FakeVisionManager(polygon_key=None, polygon_vertices=None)
    bus = InProcessEventBus()
    runner = build_shadow_runner_from_live(
        "c7",
        camera_service,
        vm,
        bus,
        detector_slug=_TEST_DETECTOR_SLUG,
    )
    assert runner is None
