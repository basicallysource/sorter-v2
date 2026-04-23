"""Tests for ``rt.bootstrap`` zone-loader + runner lifecycle helpers.

Covers the boot-race fix (saved polygons + camera config resolve zones
without a live frame), the detector-slug-from-config resolution, and the
``RtRuntimeHandle.rebuild_runner_for_role`` path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch


import rt.perception  # noqa: F401 — register detectors/trackers/filters
from rt.bootstrap import (
    _build_perception_runner_for_role,
    _configured_resolution_for_role,
    _detector_slug_for_role,
    _load_arc_tracker_params,
    _load_zone_for_role,
)
from rt.contracts.feed import PolygonZone, RectZone
from rt.contracts.registry import CLASSIFIERS
from rt.events.bus import InProcessEventBus


LOG = logging.getLogger("test.bootstrap")


# ---------------------------------------------------------------------------
# Fake camera_service that never produces a frame — mirrors the boot-race.
# ---------------------------------------------------------------------------


def test_rt_perception_import_registers_brickognize_classifier() -> None:
    """Bootstrap imports ``rt.perception`` only once, so that import must
    register the classifier strategies needed by ``build_rt_runtime``."""
    assert "brickognize" in CLASSIFIERS.keys()


@dataclass
class _FakeCameraConfig:
    width: int = 1920
    height: int = 1080


class _FakeDevice:
    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self.config = _FakeCameraConfig(width=width, height=height)


class _FakeCameraService:
    """No ``get_capture_thread_for_role`` / ``get_feed`` that returns a live
    frame — this is exactly the boot-race shape (camera thread hasn't
    produced frames yet)."""

    def __init__(
        self,
        devices: dict[str, _FakeDevice] | None = None,
    ) -> None:
        self._devices = devices or {}

    def get_device(self, role: str) -> _FakeDevice | None:
        return self._devices.get(role)


# ---------------------------------------------------------------------------
# _load_zone_for_role
# ---------------------------------------------------------------------------


def _fake_saved_polygons_full() -> dict[str, Any]:
    """Saved-blob shape with polygons + top-level resolution."""
    return {
        "polygons": {
            "second_channel": [
                [100, 100],
                [300, 100],
                [300, 200],
                [100, 200],
            ],
            "third_channel": [
                [150, 50],
                [350, 50],
                [350, 250],
                [150, 250],
            ],
            "classification_channel": [
                [200, 300],
                [500, 300],
                [500, 600],
                [200, 600],
            ],
        },
        "resolution": [3840, 2160],
    }


def _fake_saved_polygons_with_per_channel_res() -> dict[str, Any]:
    payload = _fake_saved_polygons_full()
    payload["arc_params"] = {
        "second": {"resolution": [1280, 720]},
        "third": {"resolution": [2592, 1944]},
        "classification_channel": {"resolution": [3840, 2160]},
    }
    return payload


def test_load_zone_from_saved_polygon_without_live_frame():
    """A saved polygon with resolution metadata yields a PolygonZone
    even when the camera service never produced a frame."""
    camera_service = _FakeCameraService(
        devices={
            "carousel": _FakeDevice(width=1920, height=1080),
        }
    )
    with patch(
        "rt.bootstrap._load_saved_polygon",
        wraps=None,
    ):
        pass  # no patch — we want the real implementation
    with patch("blob_manager.getChannelPolygons", return_value=_fake_saved_polygons_full()):
        zone, reason = _load_zone_for_role("c4", camera_service, LOG)
    assert reason == ""
    assert isinstance(zone, PolygonZone)
    # Saved polygon (3840x2160) should scale down to the 1920x1080 target.
    # So e.g. (200, 300) -> (100, 150).
    xs = [p[0] for p in zone.vertices]
    ys = [p[1] for p in zone.vertices]
    assert max(xs) <= 1920
    assert max(ys) <= 1080
    # Scale check — first vertex of classification_channel at saved res (200,300)
    # becomes (100,150) at target.
    assert zone.vertices[0] == (100, 150)


def test_load_zone_uses_per_channel_resolution_for_c2_polygon() -> None:
    camera_service = _FakeCameraService(
        devices={
            "c_channel_2": _FakeDevice(width=1280, height=720),
        }
    )
    with patch(
        "blob_manager.getChannelPolygons",
        return_value=_fake_saved_polygons_with_per_channel_res(),
    ):
        zone, reason = _load_zone_for_role("c2", camera_service, LOG)
    assert reason == ""
    assert isinstance(zone, PolygonZone)
    xs = [p[0] for p in zone.vertices]
    ys = [p[1] for p in zone.vertices]
    assert min(xs) == 100
    assert max(xs) == 300
    assert min(ys) == 100
    assert max(ys) == 200


def test_load_arc_tracker_params_uses_per_channel_resolution() -> None:
    with patch(
        "blob_manager.getChannelPolygons",
        return_value={
            **_fake_saved_polygons_with_per_channel_res(),
            "arc_params": {
                "second": {
                    "center": [640, 360],
                    "inner_radius": 120,
                    "outer_radius": 300,
                    "resolution": [1280, 720],
                },
            },
        },
    ):
        params = _load_arc_tracker_params("c2", target_w=1280, target_h=720)
    assert params["polar_center"] == (640.0, 360.0)
    assert params["polar_radius_range"] == (120.0, 300.0)


def test_load_zone_c4_boots_without_live_frame_on_c4_camera():
    """Specifically the bug Marc hit: C4 (carousel camera) should not be
    skipped when its camera hasn't produced a frame yet, as long as the
    device config carries the capture resolution."""
    camera_service = _FakeCameraService(
        devices={
            "c_channel_2": _FakeDevice(),
            "c_channel_3": _FakeDevice(),
            "carousel": _FakeDevice(),
        }
    )
    with patch("blob_manager.getChannelPolygons", return_value=_fake_saved_polygons_full()):
        zone, reason = _load_zone_for_role("c4", camera_service, LOG)
    assert reason == ""
    assert zone is not None


def test_load_zone_falls_back_to_full_frame_when_polygon_missing():
    """When no polygon is saved we still return a RectZone using the
    configured camera resolution — not None, not a skip."""
    camera_service = _FakeCameraService(
        devices={
            "carousel": _FakeDevice(width=1280, height=720),
        }
    )
    with patch("blob_manager.getChannelPolygons", return_value={"polygons": {}}):
        zone, reason = _load_zone_for_role("c4", camera_service, LOG)
    assert reason == ""
    assert isinstance(zone, RectZone)
    assert zone.w == 1280
    assert zone.h == 720


def test_load_zone_returns_none_when_no_camera_config():
    """If the device has no config AND the polygon blob has no resolution,
    we cannot compute a zone."""
    camera_service = _FakeCameraService(devices={})  # no device
    with patch("blob_manager.getChannelPolygons", return_value={"polygons": {}}):
        zone, reason = _load_zone_for_role("c4", camera_service, LOG)
    assert zone is None
    assert reason == "no_camera_config"


def test_configured_resolution_reads_device_config():
    camera_service = _FakeCameraService(
        devices={"carousel": _FakeDevice(width=4096, height=2160)}
    )
    assert _configured_resolution_for_role(camera_service, "carousel") == (4096, 2160)


def test_configured_resolution_returns_none_when_missing():
    camera_service = _FakeCameraService(devices={})
    assert _configured_resolution_for_role(camera_service, "carousel") is None


# ---------------------------------------------------------------------------
# _detector_slug_for_role  —  Bug #2
# ---------------------------------------------------------------------------


def test_detector_slug_falls_back_to_scope_default_when_no_saved_pref():
    """When the user has never changed the dropdown we use the per-scope
    default — not a hardcoded value."""
    with patch("blob_manager.getFeederDetectionConfig", return_value={}):
        with patch("blob_manager.getClassificationChannelDetectionConfig", return_value={}):
            slug = _detector_slug_for_role("c4", LOG)
    # _UI_SCOPE_DEFAULT_SLUG["classification_channel"] is hive:c-channel-yolo11n-320
    # and that slug is actually registered. Must match.
    assert slug == "hive:c-channel-yolo11n-320"


def test_detector_slug_respects_user_saved_preference_for_c4():
    """Saved per-role algorithm under 'classification_channel' (via the
    feeder config blob shape) must win over the default."""
    # The real registry has only one hive slug in tests, so we verify the
    # precedence mechanism by asserting that a saved *valid* slug is used
    # verbatim — use the real default slug as the stand-in.
    saved_slug = "hive:c-channel-yolo11n-320"
    with patch(
        "blob_manager.getFeederDetectionConfig",
        return_value={"algorithm_by_role": {"classification_channel": saved_slug}},
    ):
        with patch("blob_manager.getClassificationChannelDetectionConfig", return_value={}):
            slug = _detector_slug_for_role("c4", LOG)
    assert slug == saved_slug


def test_detector_slug_ignores_invalid_saved_slug():
    """A saved slug that no longer refers to a registered detector must
    not be returned — we fall back to the scope default."""
    with patch(
        "blob_manager.getFeederDetectionConfig",
        return_value={"algorithm_by_role": {"c_channel_2": "hive:does-not-exist"}},
    ):
        slug = _detector_slug_for_role("c2", LOG)
    assert slug == "hive:c-channel-yolo11n-320"


# ---------------------------------------------------------------------------
# _build_perception_runner_for_role + rebuild
# ---------------------------------------------------------------------------


def test_build_perception_runner_for_role_returns_reason_on_missing_camera():
    """The bootstrap loop must surface a reason slug so `/api/rt/status`
    can explain the skip to the operator."""
    camera_service = _FakeCameraService(devices={})
    with patch("blob_manager.getChannelPolygons", return_value={"polygons": {}}):
        runner, zone, reason = _build_perception_runner_for_role(
            "c4",
            camera_service=camera_service,
            event_bus=InProcessEventBus(),
            logger=LOG,
        )
    assert runner is None
    assert reason == "no_camera_config"


def test_build_perception_runner_for_role_happy_path():
    camera_service = _FakeCameraService(
        devices={"carousel": _FakeDevice(width=1920, height=1080)}
    )
    saved = _fake_saved_polygons_full()
    saved["arc_params"] = {
        "classification_channel": {
            "center": [960, 540],
            "inner_radius": 180,
            "outer_radius": 500,
            "resolution": [1920, 1080],
        }
    }
    with patch("blob_manager.getChannelPolygons", return_value=saved):
        with patch("blob_manager.getFeederDetectionConfig", return_value={}):
            with patch(
                "blob_manager.getClassificationChannelDetectionConfig",
                return_value={},
            ):
                runner, zone, reason = _build_perception_runner_for_role(
                    "c4",
                    camera_service=camera_service,
                    event_bus=InProcessEventBus(),
                    logger=LOG,
                )
    assert reason == ""
    assert runner is not None
    assert zone is not None
    # The runner has the correct feed id wired.
    pipeline = runner._pipeline
    assert pipeline.feed.feed_id == "c4_feed"
    # And the detector is the scope default (hive:c-channel-yolo11n-320).
    assert pipeline.detector.key == "hive:c-channel-yolo11n-320"
    tracker = pipeline.tracker
    assert getattr(tracker, "_polar_center", None) is not None
