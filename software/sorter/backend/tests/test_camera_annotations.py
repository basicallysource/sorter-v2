from __future__ import annotations

from dataclasses import dataclass
import sys
from pathlib import Path

import numpy as np
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from defs.events import CameraName
from rt.contracts.feed import PolygonZone
from rt.contracts.tracking import Track, TrackBatch
from server import shared_state
from server.camera_annotations import (
    ChannelArcOverlay,
    ChannelZoneAnnotationProvider,
    RuntimeAnnotationProvider,
    RuntimeTrackOverlay,
    RuntimeZoneOverlay,
    attach_camera_annotations,
)


@dataclass
class _FakeFeed:
    overlays: list[object]

    def clear_overlays(self) -> None:
        self.overlays.clear()

    def add_overlay(self, overlay: object) -> None:
        self.overlays.append(overlay)

    def set_overlays(self, overlays: list[object]) -> None:
        self.overlays = list(overlays)


@dataclass(frozen=True)
class _FakeAnnotationSnapshot:
    zone: PolygonZone | None
    tracks: tuple[Track, ...]


class _FakeHandle:
    def __init__(self, zone: PolygonZone, batch: TrackBatch) -> None:
        self._snapshots = {
            "c2_feed": _FakeAnnotationSnapshot(zone=zone, tracks=batch.tracks)
        }

    def annotation_snapshot(self, feed_id: str) -> _FakeAnnotationSnapshot | None:
        return self._snapshots.get(feed_id)


class _FakeCameraService:
    def __init__(self) -> None:
        self.active_cameras = [
            CameraName.c_channel_2,
            CameraName.c_channel_3,
            CameraName.classification_channel,
            CameraName.classification_top,
        ]
        self.feeds = {
            "c_channel_2": _FakeFeed([]),
            "c_channel_3": _FakeFeed([]),
            "classification_channel": _FakeFeed([]),
            "classification_top": _FakeFeed([]),
        }

    def get_feed(self, role: str) -> _FakeFeed | None:
        return self.feeds.get(role)


def _track_batch() -> TrackBatch:
    return TrackBatch(
        feed_id="c2_feed",
        frame_seq=1,
        timestamp=0.0,
        tracks=(
            Track(
                track_id=7,
                global_id=77,
                piece_uuid=None,
                bbox_xyxy=(20, 30, 90, 120),
                score=0.9,
                confirmed_real=True,
                angle_rad=0.0,
                radius_px=120.0,
                hit_count=4,
                first_seen_ts=0.0,
                last_seen_ts=0.0,
            ),
        ),
        lost_track_ids=(),
    )


def test_runtime_zone_overlay_renders_polygon() -> None:
    overlay = RuntimeZoneOverlay(
        lambda: PolygonZone(vertices=((10, 10), (100, 10), (100, 90), (10, 90)))
    )
    frame = np.zeros((120, 120, 3), dtype=np.uint8)
    annotated = overlay.annotate(frame)
    assert np.any(annotated != frame)


def test_runtime_track_overlay_renders_rt_tracks() -> None:
    overlay = RuntimeTrackOverlay(lambda: list(_track_batch().tracks))
    frame = np.zeros((160, 160, 3), dtype=np.uint8)
    annotated = overlay.annotate(frame)
    assert np.any(annotated != frame)


def test_runtime_annotation_provider_emits_role_bound_layers() -> None:
    provider = RuntimeAnnotationProvider({"c_channel_2": "c2_feed"})
    overlays = provider.overlays_for_role("c_channel_2")
    assert len(overlays) == 1
    assert isinstance(overlays[0], RuntimeTrackOverlay)
    assert provider.overlays_for_role("classification_top") == ()


def test_channel_zone_annotation_provider_emits_arc_overlay() -> None:
    provider = ChannelZoneAnnotationProvider()
    overlays = provider.overlays_for_role("c_channel_2")
    assert len(overlays) == 1
    assert isinstance(overlays[0], ChannelArcOverlay)
    assert provider.overlays_for_role("classification_top") == ()


def test_attach_camera_annotations_wires_live_rt_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    zone = PolygonZone(vertices=((8, 8), (120, 8), (120, 120), (8, 120)))
    handle = _FakeHandle(zone, _track_batch())
    service = _FakeCameraService()
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)
    monkeypatch.setattr(
        "server.camera_annotations.getChannelPolygons",
        lambda: {
            "arc_params": {
                "second": {
                    "center": [64, 64],
                    "inner_radius": 18,
                    "outer_radius": 52,
                    "drop_zone": {"start_angle": 0.0, "end_angle": 60.0},
                    "exit_zone": {"start_angle": 180.0, "end_angle": 240.0},
                    "resolution": [128, 128],
                },
                "third": {
                    "center": [64, 64],
                    "inner_radius": 18,
                    "outer_radius": 52,
                    "drop_zone": {"start_angle": 0.0, "end_angle": 60.0},
                    "exit_zone": {"start_angle": 180.0, "end_angle": 240.0},
                    "resolution": [128, 128],
                },
                "classification_channel": {
                    "center": [64, 64],
                    "inner_radius": 18,
                    "outer_radius": 52,
                    "drop_zone": {"start_angle": 0.0, "end_angle": 60.0},
                    "exit_zone": {"start_angle": 180.0, "end_angle": 240.0},
                    "resolution": [128, 128],
                },
            }
        },
    )

    attach_camera_annotations(service)

    c2 = service.feeds["c_channel_2"]
    assert len(c2.overlays) == 2
    frame = np.zeros((160, 160, 3), dtype=np.uint8)
    annotated = frame.copy()
    for overlay in c2.overlays:
        annotated = overlay.annotate(annotated)
    assert np.any(annotated != frame)

    assert len(service.feeds["c_channel_3"].overlays) == 2
    assert len(service.feeds["classification_channel"].overlays) == 2
    assert service.feeds["classification_top"].overlays == []
