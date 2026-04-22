"""Tests for ``RtRuntimeHandle.rebuild_runner_for_role``.

Covers the detector-selection rebuild path: user saves a new slug, the
runner is torn down and rebuilt with the new detector, and the handle's
``skipped_roles`` list stays consistent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import rt.perception  # noqa: F401 — register detectors/trackers/filters
from rt.bootstrap import RtRuntimeHandle
from rt.contracts.feed import PolygonZone, RectZone, Zone
from rt.coupling.orchestrator import Orchestrator
from rt.coupling.slots import CapacitySlot
from rt.events.bus import InProcessEventBus
from rt.perception.pipeline_runner import PerceptionRunner


LOG = logging.getLogger("test.runtime_handle")


@dataclass
class _FakeCameraConfig:
    width: int = 1920
    height: int = 1080


class _FakeDevice:
    def __init__(self, width: int = 1920, height: int = 1080) -> None:
        self.config = _FakeCameraConfig(width=width, height=height)


class _FakeCameraService:
    def __init__(self, devices: dict[str, _FakeDevice]) -> None:
        self._devices = devices

    def get_device(self, role: str) -> _FakeDevice | None:
        return self._devices.get(role)


def _polygon_blob() -> dict[str, Any]:
    return {
        "polygons": {
            "classification_channel": [[200, 300], [500, 300], [500, 600], [200, 600]],
            "second_channel": [[100, 100], [300, 100], [300, 200], [100, 200]],
            "third_channel": [[150, 50], [350, 50], [350, 250], [150, 250]],
        },
        "resolution": [3840, 2160],
    }


def _empty_handle(camera_service: Any) -> RtRuntimeHandle:
    """Construct a minimal RtRuntimeHandle with a real orchestrator stub."""
    bus = InProcessEventBus()
    orch = Orchestrator(
        runtimes=[],
        slots={},
        perception_sources={},
        event_bus=bus,
        logger=LOG,
        tick_period_s=0.020,
    )
    # c4 + distributor are not exercised in these tests; use None proxies.
    return RtRuntimeHandle(
        orchestrator=orch,
        perception_runners=[],
        event_bus=bus,
        c4=None,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=camera_service,
    )


def test_rebuild_runner_adds_missing_runner():
    """A role that was skipped at bootstrap can be brought online later
    without tearing down the whole runtime."""
    camera_service = _FakeCameraService(
        devices={"carousel": _FakeDevice(width=1920, height=1080)}
    )
    handle = _empty_handle(camera_service)
    handle.skipped_roles.append({"role": "c4", "reason": "no_camera_config"})

    with patch("blob_manager.getChannelPolygons", return_value=_polygon_blob()):
        with patch("blob_manager.getFeederDetectionConfig", return_value={}):
            with patch(
                "blob_manager.getClassificationChannelDetectionConfig",
                return_value={},
            ):
                runner = handle.rebuild_runner_for_role("c4", logger=LOG)

    assert runner is not None
    assert len(handle.perception_runners) == 1
    # skipped_roles entry for c4 is cleared.
    assert all(entry.get("role") != "c4" for entry in handle.skipped_roles)
    # Handle accessor finds the new runner.
    assert handle.runner_for_feed("c4_feed") is runner


def test_rebuild_runner_replaces_existing_runner_with_new_slug():
    """Changing the saved slug and calling rebuild swaps detectors on the
    running handle."""
    camera_service = _FakeCameraService(
        devices={"carousel": _FakeDevice(width=1920, height=1080)}
    )
    handle = _empty_handle(camera_service)

    # Seed the handle with an initial c4 runner (saved config empty → scope default).
    with patch("blob_manager.getChannelPolygons", return_value=_polygon_blob()):
        with patch("blob_manager.getFeederDetectionConfig", return_value={}):
            with patch(
                "blob_manager.getClassificationChannelDetectionConfig",
                return_value={},
            ):
                first = handle.rebuild_runner_for_role("c4", logger=LOG)
    assert first is not None
    first_slug = first._pipeline.detector.key

    # Now save a new slug (use the same slug since only one hive model is
    # registered in tests) and rebuild — the runner instance must change.
    with patch("blob_manager.getChannelPolygons", return_value=_polygon_blob()):
        with patch(
            "blob_manager.getFeederDetectionConfig",
            return_value={
                "algorithm_by_role": {"classification_channel": first_slug},
            },
        ):
            with patch(
                "blob_manager.getClassificationChannelDetectionConfig",
                return_value={},
            ):
                second = handle.rebuild_runner_for_role("c4", logger=LOG)

    assert second is not None
    assert second is not first
    assert len(handle.perception_runners) == 1
    assert second._pipeline.detector.key == first_slug


def test_rebuild_runner_marks_skipped_on_failure():
    """When the rebuild can't produce a runner the handle must record the
    skip so ``/api/rt/status`` can surface it."""
    camera_service = _FakeCameraService(devices={})  # carousel absent
    handle = _empty_handle(camera_service)

    with patch("blob_manager.getChannelPolygons", return_value={"polygons": {}}):
        with patch("blob_manager.getFeederDetectionConfig", return_value={}):
            with patch(
                "blob_manager.getClassificationChannelDetectionConfig",
                return_value={},
            ):
                runner = handle.rebuild_runner_for_role("c4", logger=LOG)

    assert runner is None
    assert len(handle.perception_runners) == 0
    reasons = [e["reason"] for e in handle.skipped_roles if e.get("role") == "c4"]
    assert reasons and reasons[0] == "no_camera_config"


def test_handle_runner_for_feed_returns_none_when_empty():
    camera_service = _FakeCameraService(devices={})
    handle = _empty_handle(camera_service)
    assert handle.runner_for_feed("c4_feed") is None


def test_start_perception_starts_runners_without_orchestrator():
    bus = MagicMock()
    orchestrator = MagicMock()
    runners = [MagicMock(), MagicMock()]
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=runners,
        event_bus=bus,
        c4=None,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
    )

    handle.start_perception()

    bus.start.assert_called_once_with()
    orchestrator.start.assert_not_called()
    assert all(runner.start.call_count == 1 for runner in runners)
    assert handle.perception_started is True
    assert handle.started is False


def test_start_paused_starts_orchestrator_in_paused_mode():
    bus = MagicMock()
    orchestrator = MagicMock()
    runners = [MagicMock(), MagicMock()]
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=runners,
        event_bus=bus,
        c4=None,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
    )

    handle.start(paused=True)

    bus.start.assert_called_once_with()
    orchestrator.start.assert_called_once_with(paused=True)
    assert handle.started is True
    assert handle.perception_started is True
    assert handle.paused is True


def test_stop_stops_perception_when_runtime_never_fully_started():
    bus = MagicMock()
    orchestrator = MagicMock()
    runners = [MagicMock(), MagicMock()]
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=runners,
        event_bus=bus,
        c4=None,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
    )
    handle.start_perception()

    handle.stop()

    orchestrator.stop.assert_not_called()
    assert all(runner.stop.call_count == 1 for runner in runners)
    bus.stop.assert_called_once_with()
    assert handle.perception_started is False
    assert handle.started is False


def test_rebuild_runner_starts_new_runner_when_perception_started():
    camera_service = _FakeCameraService(
        devices={"carousel": _FakeDevice(width=1920, height=1080)}
    )
    handle = _empty_handle(camera_service)
    handle.perception_started = True
    runner = MagicMock(spec=PerceptionRunner)
    zone = RectZone(x=0, y=0, w=1920, h=1080)

    with patch(
        "rt.bootstrap._build_perception_runner_for_role",
        return_value=(runner, zone, ""),
    ):
        rebuilt = handle.rebuild_runner_for_role("c4", logger=LOG)

    assert rebuilt is runner
    runner.start.assert_called_once_with()
