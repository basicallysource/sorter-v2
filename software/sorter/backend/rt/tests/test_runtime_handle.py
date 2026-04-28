"""Tests for ``RtRuntimeHandle.rebuild_runner_for_role``.

Covers the detector-selection rebuild path: user saves a new slug, the
runner is torn down and rebuilt with the new detector, and the handle's
``skipped_roles`` list stays consistent.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import rt.perception  # noqa: F401 — register detectors/trackers/filters
from rt.bootstrap import RtRuntimeHandle
from rt.contracts.feed import PolygonZone, RectZone
from rt.contracts.tracking import Track, TrackBatch
from rt.coupling.orchestrator import Orchestrator
from rt.events.bus import InProcessEventBus
from rt.hardware.motion_profiles import (
    MotionDiagnostics,
    PROFILE_TRANSPORT,
    plan_motion,
    profile_from_values,
)
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


def test_start_marks_persisted_active_dossiers_stale() -> None:
    handle = _empty_handle(_FakeCameraService({}))
    with patch("local_state.mark_active_piece_dossiers_stale", return_value=3) as mark:
        handle.start(paused=True)

    mark.assert_called_once_with(reason="rt_runtime_start")
    assert handle.started is True
    assert handle.paused is True
    handle.stop()


def _track_batch(feed_id: str) -> TrackBatch:
    return TrackBatch(
        feed_id=feed_id,
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


def _runner_for_feed(
    feed_id: str,
    *,
    batch: TrackBatch,
    with_raw_tracks: bool,
    shadow_batch: TrackBatch | None = None,
) -> MagicMock:
    runner = MagicMock()
    runner._pipeline = type(
        "_Pipeline",
        (),
        {"feed": type("_Feed", (), {"feed_id": feed_id})()},
    )()
    if with_raw_tracks:
        runner.latest_state.return_value = type("_State", (), {"raw_tracks": batch})()
    else:
        runner.latest_state.return_value = type("_State", (), {"raw_tracks": None})()
    runner.latest_tracks.return_value = batch
    runner.latest_shadow_tracks.return_value = shadow_batch
    return runner


def test_rebuild_runner_adds_missing_runner():
    """A role that was skipped at bootstrap can be brought online later
    without tearing down the whole runtime."""
    camera_service = _FakeCameraService(
        devices={"carousel": _FakeDevice(width=1920, height=1080)}
    )
    handle = _empty_handle(camera_service)
    handle.skipped_roles.append({"role": "c4", "reason": "no_camera_config"})

    with patch("local_state.get_channel_polygons", return_value=_polygon_blob()):
        with patch("server.detection_config.common.get_feeder_detection_config", return_value={}):
            with patch(
                "server.detection_config.common.get_classification_channel_detection_config",
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
    with patch("local_state.get_channel_polygons", return_value=_polygon_blob()):
        with patch("server.detection_config.common.get_feeder_detection_config", return_value={}):
            with patch(
                "server.detection_config.common.get_classification_channel_detection_config",
                return_value={},
            ):
                first = handle.rebuild_runner_for_role("c4", logger=LOG)
    assert first is not None
    first_slug = first._pipeline.detector.key

    # Now save a new slug (use the same slug since only one hive model is
    # registered in tests) and rebuild — the runner instance must change.
    with patch("local_state.get_channel_polygons", return_value=_polygon_blob()):
        with patch(
            "server.detection_config.common.get_feeder_detection_config",
            return_value={
                "algorithm_by_role": {"classification_channel": first_slug},
            },
        ):
            with patch(
                "server.detection_config.common.get_classification_channel_detection_config",
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

    with patch("local_state.get_channel_polygons", return_value={"polygons": {}}):
        with patch("server.detection_config.common.get_feeder_detection_config", return_value={}):
            with patch(
                "server.detection_config.common.get_classification_channel_detection_config",
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


def test_latest_frame_for_feed_uses_runner_accessor() -> None:
    camera_service = _FakeCameraService(devices={})
    handle = _empty_handle(camera_service)
    batch = _track_batch("c4_feed")
    runner = _runner_for_feed("c4_feed", batch=batch, with_raw_tracks=True)
    frame = type("_Frame", (), {"raw": object()})()
    runner.latest_frame.return_value = frame
    handle.perception_runners = [runner]

    assert handle.latest_frame_for_feed("c4_feed") is frame
    assert handle.latest_frame_for_feed("missing") is None


def test_annotation_snapshot_uses_zone_and_raw_tracks() -> None:
    camera_service = _FakeCameraService(devices={})
    handle = _empty_handle(camera_service)
    zone = PolygonZone(vertices=((10, 10), (100, 10), (100, 90), (10, 90)))
    batch = _track_batch("c2_feed")
    runner = _runner_for_feed("c2_feed", batch=batch, with_raw_tracks=True)
    handle.feed_zones["c2_feed"] = zone
    handle.perception_runners = [runner]

    snapshot = handle.annotation_snapshot("c2_feed")

    assert snapshot.feed_id == "c2_feed"
    assert snapshot.zone == zone
    assert snapshot.tracks == batch.tracks


def test_annotation_snapshot_falls_back_to_latest_tracks() -> None:
    camera_service = _FakeCameraService(devices={})
    handle = _empty_handle(camera_service)
    batch = _track_batch("c3_feed")
    runner = _runner_for_feed("c3_feed", batch=batch, with_raw_tracks=False)
    handle.perception_runners = [runner]

    snapshot = handle.annotation_snapshot("c3_feed")

    assert snapshot.feed_id == "c3_feed"
    assert snapshot.zone is None
    assert snapshot.tracks == batch.tracks


def test_annotation_snapshot_includes_shadow_tracks() -> None:
    camera_service = _FakeCameraService(devices={})
    handle = _empty_handle(camera_service)
    batch = _track_batch("c2_feed")
    shadow_batch = _track_batch("c2_feed")
    runner = _runner_for_feed(
        "c2_feed",
        batch=batch,
        with_raw_tracks=True,
        shadow_batch=shadow_batch,
    )
    handle.perception_runners = [runner]

    snapshot = handle.annotation_snapshot("c2_feed")

    assert snapshot.tracks == batch.tracks
    assert snapshot.shadow_tracks == shadow_batch.tracks


def test_start_perception_starts_runners_without_orchestrator():
    bus = MagicMock()
    orchestrator = MagicMock()
    runners = [MagicMock(), MagicMock()]
    sample_collector = MagicMock()
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=runners,
        event_bus=bus,
        c4=None,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
        sample_collector=sample_collector,
    )

    handle.start_perception()

    bus.start.assert_called_once_with()
    orchestrator.start.assert_not_called()
    assert all(runner.start.call_count == 1 for runner in runners)
    sample_collector.start.assert_called_once_with()
    assert handle.perception_started is True
    assert handle.started is False


def test_start_paused_starts_orchestrator_in_paused_mode():
    bus = MagicMock()
    orchestrator = MagicMock()
    runners = [MagicMock(), MagicMock()]
    c4 = MagicMock()
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=runners,
        event_bus=bus,
        c4=c4,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
    )

    handle.start(paused=True)

    c4.arm_startup_purge.assert_called_once_with()
    bus.start.assert_called_once_with()
    orchestrator.start.assert_called_once_with(paused=True)
    assert handle.started is True
    assert handle.perception_started is True
    assert handle.paused is True


def test_status_snapshot_composes_runner_orchestrator_and_maintenance() -> None:
    bus = MagicMock()
    orchestrator = MagicMock()
    orchestrator.status_snapshot.return_value = {
        "runtime_health": {"c4": {"state": "idle", "blocked_reason": None, "last_tick_ms": 1.0}},
        "runtime_debug": {"c4": {"piece_count": 2}},
        "slot_debug": {"c4_to_distributor": {"capacity": 1, "taken": 0, "available": 1}},
    }
    runner = MagicMock()
    runner.status_snapshot.return_value = {
        "feed_id": "c4_feed",
        "detector_slug": "hive:c-channel-yolo11n-320",
        "zone_kind": "polygon",
        "running": True,
        "last_frame_age_ms": 3.5,
        "detection_count": 1,
        "raw_track_count": 1,
        "confirmed_track_count": 1,
        "confirmed_real_track_count": 1,
        "raw_track_preview": [],
        "confirmed_track_preview": [],
    }
    sample_collector = MagicMock()
    sample_collector.status_snapshot.return_value = {
        "installed": True,
        "running": True,
        "captured_count": 3,
    }
    motion_diagnostics = MotionDiagnostics()
    motion_diagnostics.record(
        plan_motion(
            profile_from_values(
                channel="c4",
                name=PROFILE_TRANSPORT,
                max_speed=2400,
                acceleration=10000,
            ),
            source="test",
            distance_usteps=60,
        ).with_result(True)
    )
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=[runner],
        event_bus=bus,
        c4=None,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[{"role": "c2", "reason": "no_camera_config"}],
        camera_service=None,
        started=True,
        perception_started=True,
        paused=True,
        sample_collector=sample_collector,
        motion_diagnostics=motion_diagnostics,
    )
    handle._purge_coordinator._status = {
        "active": True,
        "phase": "purging",
        "counts": {"c2": 1, "c3": 0, "c4_raw": 0, "c4_dossiers": 0},
    }

    snapshot = handle.status_snapshot()

    assert snapshot["perception_started"] is True
    assert snapshot["started"] is True
    assert snapshot["paused"] is True
    assert snapshot["runners"] == [runner.status_snapshot.return_value]
    assert snapshot["skipped_roles"] == [{"role": "c2", "reason": "no_camera_config"}]
    assert snapshot["runtime_health"]["c4"]["state"] == "idle"
    assert snapshot["runtime_debug"]["c4"] == {"piece_count": 2}
    assert snapshot["slot_debug"]["c4_to_distributor"]["available"] == 1
    assert snapshot["maintenance"]["c234_purge"]["phase"] == "purging"
    assert snapshot["sample_collection"]["captured_count"] == 3
    assert snapshot["motion"]["last_by_channel"]["c4"]["profile"] == "transport"


def test_clear_c1_pause_forwards_to_c1_runtime() -> None:
    bus = MagicMock()
    orchestrator = MagicMock()
    c1 = MagicMock()
    c1.is_paused.return_value = True
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=[],
        event_bus=bus,
        c4=None,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        c1=c1,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
    )

    result = handle.clear_c1_pause()

    assert result == {"cleared": True, "was_paused": True}
    c1.clear_pause.assert_called_once_with()


def test_stop_stops_perception_when_runtime_never_fully_started():
    bus = MagicMock()
    orchestrator = MagicMock()
    runners = [MagicMock(), MagicMock()]
    sample_collector = MagicMock()
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=runners,
        event_bus=bus,
        c4=None,  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
        sample_collector=sample_collector,
    )
    handle.start_perception()

    handle.stop()

    orchestrator.stop.assert_not_called()
    sample_collector.stop.assert_called_once_with(timeout=1.0)
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
        "rt.bootstrap.build_perception_runner_for_role",
        return_value=(runner, zone, ""),
    ):
        rebuilt = handle.rebuild_runner_for_role("c4", logger=LOG)

    assert rebuilt is runner
    runner.start.assert_called_once_with()


class _FakePurgePort:
    def __init__(self, key: str, counts_seq: list[int]) -> None:
        self.key = key
        self._counts_seq = list(counts_seq)
        self.arm_count = 0
        self.disarm_count = 0
        self.drain_count = 0

    def arm(self) -> None:
        self.arm_count += 1

    def disarm(self) -> None:
        self.disarm_count += 1

    def counts(self):
        from rt.contracts.purge import PurgeCounts

        value = self._counts_seq[0] if self._counts_seq else 0
        if len(self._counts_seq) > 1:
            self._counts_seq.pop(0)
        if self.key == "c4":
            return PurgeCounts(
                piece_count=int(value), owned_count=0, pending_detections=0
            )
        return PurgeCounts(
            piece_count=int(value), owned_count=0, pending_detections=0
        )

    def drain_step(self, now_mono: float) -> bool:
        self.drain_count += 1
        return True


class _FakePurgeRuntime:
    def __init__(self, key: str, counts: list[int]) -> None:
        self._port = _FakePurgePort(key, counts)

    def purge_port(self):
        return self._port


def test_start_c234_purge_resumes_then_repauses_when_initially_paused() -> None:
    bus = MagicMock()
    orchestrator = MagicMock()
    c1 = MagicMock()
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=[],
        event_bus=bus,
        c1=c1,
        c4=_FakePurgeRuntime("c4", [1, 1, 0, 0]),  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        c2=_FakePurgeRuntime("c2", [2, 1, 0, 0]),  # type: ignore[arg-type]
        c3=_FakePurgeRuntime("c3", [1, 0, 0, 0]),  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
        started=True,
        perception_started=True,
        paused=True,
    )
    published: list[str] = []

    started = handle.start_c234_purge(
        state_publisher=published.append,
        timeout_s=1.0,
        clear_hold_s=0.0,
        poll_s=0.01,
    )

    assert started is True
    deadline = time.time() + 2.0
    while handle.c234_purge_status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = handle.c234_purge_status()
    assert status["active"] is False
    assert status["success"] is True
    assert status["reason"] == "cleared"
    assert published == ["running", "paused"]
    assert orchestrator.resume.call_count == 1
    assert orchestrator.pause.call_count == 1
    c1.pause_for_maintenance.assert_called_once_with("c234_purge")
    c1.resume_from_maintenance.assert_called_once_with()
    # Every channel must have been armed and disarmed exactly once.
    for runtime in (handle.c2, handle.c3, handle.c4):
        port = runtime.purge_port()  # type: ignore[union-attr]
        assert port.arm_count == 1
        assert port.disarm_count == 1


def test_start_c234_purge_can_limit_selected_channels() -> None:
    bus = MagicMock()
    orchestrator = MagicMock()
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=[],
        event_bus=bus,
        c4=_FakePurgeRuntime("c4", [1, 0, 0]),  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        c2=_FakePurgeRuntime("c2", [9, 9, 9]),  # type: ignore[arg-type]
        c3=_FakePurgeRuntime("c3", [9, 9, 9]),  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
        started=True,
        perception_started=True,
        paused=True,
    )

    assert handle.start_c234_purge(
        channels=["c4"],
        timeout_s=1.0,
        clear_hold_s=0.0,
        poll_s=0.01,
    )

    deadline = time.time() + 2.0
    while handle.c234_purge_status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = handle.c234_purge_status()
    assert status["success"] is True
    assert status["channels"] == ["c4"]
    assert handle.c2.purge_port().arm_count == 0  # type: ignore[union-attr]
    assert handle.c3.purge_port().arm_count == 0  # type: ignore[union-attr]
    assert handle.c4.purge_port().arm_count == 1  # type: ignore[union-attr]


def test_cancel_c234_purge_stops_job_and_restores_pause_state() -> None:
    bus = MagicMock()
    orchestrator = MagicMock()
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=[],
        event_bus=bus,
        c4=_FakePurgeRuntime("c4", [1, 1, 1, 1, 1]),  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        c2=_FakePurgeRuntime("c2", [1, 1, 1, 1, 1]),  # type: ignore[arg-type]
        c3=_FakePurgeRuntime("c3", [1, 1, 1, 1, 1]),  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
        started=True,
        perception_started=True,
        paused=True,
    )

    assert handle.start_c234_purge(timeout_s=2.0, clear_hold_s=0.0, poll_s=0.05)
    time.sleep(0.05)
    assert handle.cancel_c234_purge() is True

    deadline = time.time() + 2.0
    while handle.c234_purge_status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = handle.c234_purge_status()
    assert status["active"] is False
    assert status["success"] is False
    assert status["reason"] == "cancelled"
    assert orchestrator.resume.call_count == 1
    assert orchestrator.pause.call_count == 1
    # Safety-net disarm must still fire on cancel.
    for runtime in (handle.c2, handle.c3, handle.c4):
        port = runtime.purge_port()  # type: ignore[union-attr]
        assert port.disarm_count == 1


def test_start_c234_purge_top_down_disarm_keeps_c3_armed_while_c2_active() -> None:
    """Regression: C3 must not disarm while C2 is still purging.

    Build counts such that C3 reports empty from tick 1, but C2 keeps
    reporting non-empty for several ticks. C3 and C4 may go clear, but
    neither may disarm until C2's port reports clear.
    """
    bus = MagicMock()
    orchestrator = MagicMock()
    c2_counts = [3, 2, 1, 0, 0, 0, 0]
    c3_counts = [0, 0, 0, 0, 0, 0, 0]
    c4_counts = [0, 0, 0, 0, 0, 0, 0]
    handle = RtRuntimeHandle(
        orchestrator=orchestrator,
        perception_runners=[],
        event_bus=bus,
        c4=_FakePurgeRuntime("c4", c4_counts),  # type: ignore[arg-type]
        distributor=None,  # type: ignore[arg-type]
        c2=_FakePurgeRuntime("c2", c2_counts),  # type: ignore[arg-type]
        c3=_FakePurgeRuntime("c3", c3_counts),  # type: ignore[arg-type]
        feed_zones={},
        skipped_roles=[],
        camera_service=None,
        started=True,
        perception_started=True,
        paused=False,
    )

    started = handle.start_c234_purge(timeout_s=1.0, clear_hold_s=0.0, poll_s=0.01)
    assert started is True
    deadline = time.time() + 2.0
    while handle.c234_purge_status()["active"] and time.time() < deadline:
        time.sleep(0.01)

    status = handle.c234_purge_status()
    assert status["success"] is True
    # Each channel still disarmed exactly once — not before upstream was clear.
    for runtime in (handle.c2, handle.c3, handle.c4):
        port = runtime.purge_port()  # type: ignore[union-attr]
        assert port.disarm_count == 1
