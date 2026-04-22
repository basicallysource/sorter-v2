from __future__ import annotations

import time

import numpy as np

import rt.perception  # noqa: F401 - trigger registry population
from rt.config.schema import FilterConfig, PipelineConfig, ZoneConfig
from rt.contracts.feed import FeedFrame, RectZone
from rt.contracts.filters import FilterChain
from rt.perception.detectors.mog2 import Mog2Detector
from rt.perception.filters.ghost import GhostFilter
from rt.perception.filters.size import SizeFilter
from rt.perception.pipeline import PerceptionPipeline, build_pipeline_from_config
from rt.perception.trackers.polar import PolarTracker
from rt.perception.zones import build_zone


class _StubFeed:
    feed_id = "test"
    purpose = "c2_feed"
    camera_id = "cam"

    def __init__(self) -> None:
        self._count = 0

    def latest(self) -> FeedFrame | None:
        self._count += 1
        return FeedFrame(
            feed_id=self.feed_id,
            camera_id=self.camera_id,
            raw=np.zeros((100, 100, 3), dtype=np.uint8),
            gray=None,
            timestamp=float(self._count) * 0.1,
            monotonic_ts=time.monotonic(),
            frame_seq=self._count,
        )

    def fps(self) -> float:
        return 10.0


def _make_frame(raw: np.ndarray, seq: int) -> FeedFrame:
    return FeedFrame(
        feed_id="test",
        camera_id="cam",
        raw=raw,
        gray=None,
        timestamp=float(seq) * 0.1,
        monotonic_ts=float(seq) * 0.1,
        frame_seq=seq,
    )


def test_pipeline_end_to_end_produces_confirmed_track() -> None:
    feed = _StubFeed()
    zone = RectZone(x=0, y=0, w=200, h=200)
    detector = Mog2Detector(min_area_px=50, blur_kernel=3, morph_kernel=3)
    tracker = PolarTracker(polar_center=None, pixel_fallback_distance_px=200.0)
    filters = FilterChain(
        (SizeFilter(min_area_px=100), GhostFilter(confirmed_real_only=False)),
    )
    pipe = PerceptionPipeline(
        feed=feed, zone=zone, detector=detector, tracker=tracker, filters=filters,
    )

    # Warm up the MOG2 background with static frames.
    bg = np.full((200, 200, 3), 30, dtype=np.uint8)
    for i in range(30):
        pipe.process_frame(_make_frame(bg, seq=i))

    saw_any_track = False
    # Now move a bright rectangle across the frame.
    for i in range(30, 50):
        frame = bg.copy()
        x = 20 + (i - 30) * 6
        frame[80:130, x : x + 30] = 220
        out = pipe.process_frame(_make_frame(frame, seq=i))
        if out.tracks:
            saw_any_track = True

    assert saw_any_track, "pipeline should emit at least one track while object moves"


def test_build_pipeline_from_config_wires_strategies() -> None:
    zone_cfg = ZoneConfig(kind="rect", params={"x": 0, "y": 0, "w": 100, "h": 100})
    pipeline_cfg = PipelineConfig(
        feed_id="test",
        detector={"key": "mog2", "params": {"min_area_px": 50}},
        tracker={"key": "polar", "params": {}},
        filters=[
            FilterConfig(key="size", params={"min_area_px": 10}),
            FilterConfig(key="ghost", params={"confirmed_real_only": False}),
        ],
    )
    feed = _StubFeed()
    zone = build_zone(zone_cfg)
    pipe = build_pipeline_from_config(pipeline_cfg, feed, zone)

    assert isinstance(pipe, PerceptionPipeline)
    assert pipe.detector.key == "mog2"
    assert pipe.tracker.key == "polar"
    assert len(pipe.filters.filters) == 2
    assert pipe.filters.filters[0].key == "size"
    assert pipe.filters.filters[1].key == "ghost"


def test_build_pipeline_with_polar_zone_propagates_geometry() -> None:
    zone_cfg = ZoneConfig(
        kind="polar",
        params={
            "center_xy": [100.0, 100.0],
            "r_inner": 30.0,
            "r_outer": 60.0,
            "theta_start_rad": 0.0,
            "theta_end_rad": 6.28,
        },
    )
    pipeline_cfg = PipelineConfig(
        feed_id="test",
        detector={"key": "mog2", "params": {}},
        tracker={"key": "polar", "params": {}},
        filters=[],
    )
    feed = _StubFeed()
    zone = build_zone(zone_cfg)
    pipe = build_pipeline_from_config(pipeline_cfg, feed, zone)
    # Internal state check: polar_center should have been set.
    assert pipe.tracker._polar_center == (100.0, 100.0)
