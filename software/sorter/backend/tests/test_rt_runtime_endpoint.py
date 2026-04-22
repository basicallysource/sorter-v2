"""Tests for /api/rt/status and the detector-rebuild hook wired from
the detection-config POST handlers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from rt.contracts.feed import PolygonZone, RectZone  # noqa: E402
from server import shared_state  # noqa: E402
from server.routers import detection as detection_router  # noqa: E402
from server.routers import rt_runtime as rt_runtime_router  # noqa: E402


class _FakeFeed:
    def __init__(self, feed_id: str) -> None:
        self.feed_id = feed_id

    def latest(self) -> None:
        return None  # no frames yet


class _FakeDetector:
    def __init__(self, key: str) -> None:
        self.key = key


class _FakePipeline:
    def __init__(self, feed: _FakeFeed, zone: Any, detector: _FakeDetector) -> None:
        self.feed = feed
        self.zone = zone
        self.detector = detector


class _FakeRunner:
    def __init__(self, feed_id: str, detector_slug: str, zone: Any) -> None:
        self._pipeline = _FakePipeline(
            _FakeFeed(feed_id), zone, _FakeDetector(detector_slug)
        )
        self._running = True


class _FakeHandle:
    """Shape-compatible with the real RtRuntimeHandle for the status endpoint."""

    def __init__(self, runners: list[_FakeRunner], skipped: list[dict[str, str]]) -> None:
        self.perception_runners = runners
        self.skipped_roles = skipped
        self.started = True
        self.paused = False


# ---------------------------------------------------------------------------
# /api/rt/status
# ---------------------------------------------------------------------------


def test_rt_status_returns_empty_envelope_when_no_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shared_state, "rt_handle", None, raising=False)
    payload = rt_runtime_router.get_rt_status()
    assert payload == {
        "rt_handle_ready": False,
        "runners": [],
        "skipped_roles": [],
    }


def test_rt_status_surfaces_runners_and_skipped_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runners = [
        _FakeRunner("c2_feed", "hive:c-channel-yolo11n-320", RectZone(x=0, y=0, w=640, h=480)),
        _FakeRunner(
            "c3_feed",
            "hive:c-channel-yolo11n-320",
            PolygonZone(vertices=((0, 0), (10, 0), (10, 10), (0, 10))),
        ),
    ]
    skipped = [{"role": "c4", "reason": "no_camera_config"}]
    handle = _FakeHandle(runners, skipped)
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    payload = rt_runtime_router.get_rt_status()
    assert payload["rt_handle_ready"] is True
    assert payload["started"] is True
    assert payload["paused"] is False
    assert payload["skipped_roles"] == [{"role": "c4", "reason": "no_camera_config"}]

    feeds = {entry["feed_id"]: entry for entry in payload["runners"]}
    assert set(feeds.keys()) == {"c2_feed", "c3_feed"}
    assert feeds["c2_feed"]["detector_slug"] == "hive:c-channel-yolo11n-320"
    assert feeds["c2_feed"]["zone_kind"] == "rect"
    assert feeds["c3_feed"]["zone_kind"] == "polygon"
    assert feeds["c2_feed"]["running"] is True


# ---------------------------------------------------------------------------
# Rebuild hook called from detection-config POST
# ---------------------------------------------------------------------------


def test_save_feeder_config_calls_rebuild_on_rt_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /api/feeder/detection-config?role=c_channel_2 must trigger a
    ``rebuild_runner_for_role('c2')`` on the rt handle."""
    handle = MagicMock()
    handle.rebuild_runner_for_role = MagicMock()
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    # Stub out blob writers so the test doesn't touch disk.
    monkeypatch.setattr(
        "server.routers.detection.getFeederDetectionConfig",
        lambda: {},
    )
    monkeypatch.setattr(
        "server.routers.detection.setFeederDetectionConfig",
        lambda cfg: None,
    )

    payload = detection_router.AuxiliaryDetectionConfigPayload(
        algorithm="hive:c-channel-yolo11n-320",
    )
    detection_router.save_feeder_detection_config(payload=payload, role="c_channel_2")

    handle.rebuild_runner_for_role.assert_called_once_with("c2")


def test_save_classification_channel_config_rebuilds_c4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST /api/classification-channel/detection-config must trigger a
    ``rebuild_runner_for_role('c4')`` on the rt handle so the user's new
    detector is applied without a server restart."""
    handle = MagicMock()
    handle.rebuild_runner_for_role = MagicMock()
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    # Force the auxiliary scope branch to the classification_channel path.
    monkeypatch.setattr(
        "server.routers.detection._public_aux_scope",
        lambda: "classification_channel",
    )
    monkeypatch.setattr(
        "server.routers.detection.getClassificationChannelDetectionConfig",
        lambda: {},
    )
    monkeypatch.setattr(
        "server.routers.detection.setClassificationChannelDetectionConfig",
        lambda cfg: None,
    )

    # The classification-channel/carousel POST endpoint validates the
    # payload against the "carousel" ui_scope, which is satisfied by the
    # carousel Hive detector.
    payload = detection_router.AuxiliaryDetectionConfigPayload(
        algorithm="hive:carousel-yolo11n-320",
    )
    detection_router.save_carousel_detection_config(payload=payload)

    handle.rebuild_runner_for_role.assert_called_once_with("c4")


def test_save_config_without_rt_handle_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No rt handle → no exception, no rebuild."""
    monkeypatch.setattr(shared_state, "rt_handle", None, raising=False)
    monkeypatch.setattr(
        "server.routers.detection.getFeederDetectionConfig",
        lambda: {},
    )
    monkeypatch.setattr(
        "server.routers.detection.setFeederDetectionConfig",
        lambda cfg: None,
    )

    payload = detection_router.AuxiliaryDetectionConfigPayload(
        algorithm="hive:c-channel-yolo11n-320",
    )
    # Should not raise.
    result = detection_router.save_feeder_detection_config(payload=payload, role="c_channel_2")
    assert result["ok"] is True
