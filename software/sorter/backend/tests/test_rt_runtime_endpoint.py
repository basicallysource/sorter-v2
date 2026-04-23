"""Tests for /api/rt/status and the detector-rebuild hook wired from
the detection-config POST handlers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call

import numpy as np
import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from server import shared_state  # noqa: E402
from server import api as api_module  # noqa: E402
from server.routers import detection as detection_router  # noqa: E402
from server.routers import rt_runtime as rt_runtime_router  # noqa: E402


class _FakeHandle:
    """Shape-compatible with the real RtRuntimeHandle for the status endpoint."""

    def __init__(
        self,
        skipped: list[dict[str, str]],
        *,
        started: bool = True,
        perception_started: bool = True,
        snapshot: dict[str, Any] | None = None,
    ) -> None:
        self.skipped_roles = skipped
        self.started = started
        self.perception_started = perception_started
        self.paused = False
        self._snapshot = dict(snapshot or {})

    def status_snapshot(self) -> dict[str, Any]:
        if self._snapshot:
            return dict(self._snapshot)
        return {
            "perception_started": bool(self.perception_started),
            "started": bool(self.started),
            "paused": bool(self.paused),
            "runners": [],
            "skipped_roles": list(self.skipped_roles),
            "runtime_health": {},
            "runtime_debug": {},
            "slot_debug": {},
            "maintenance": {},
        }


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
        "perception_started": False,
        "started": False,
        "paused": False,
        "runners": [],
        "skipped_roles": [],
        "runtime_health": {},
        "runtime_debug": {},
        "slot_debug": {},
        "maintenance": {},
    }


def test_rt_status_surfaces_runners_and_skipped_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skipped = [{"role": "c4", "reason": "no_camera_config"}]
    handle = _FakeHandle(
        skipped,
        snapshot={
            "perception_started": True,
            "started": True,
            "paused": False,
            "runners": [
                {
                    "feed_id": "c2_feed",
                    "detector_slug": "hive:c-channel-yolo11n-320",
                    "zone_kind": "rect",
                    "running": True,
                    "last_frame_age_ms": None,
                    "detection_count": None,
                    "raw_track_count": None,
                    "confirmed_track_count": None,
                    "confirmed_real_track_count": None,
                    "raw_track_preview": [],
                    "confirmed_track_preview": [],
                },
                {
                    "feed_id": "c3_feed",
                    "detector_slug": "hive:c-channel-yolo11n-320",
                    "zone_kind": "polygon",
                    "running": True,
                    "last_frame_age_ms": None,
                    "detection_count": None,
                    "raw_track_count": None,
                    "confirmed_track_count": None,
                    "confirmed_real_track_count": None,
                    "raw_track_preview": [],
                    "confirmed_track_preview": [],
                },
            ],
            "skipped_roles": skipped,
            "runtime_health": {},
            "runtime_debug": {},
            "slot_debug": {},
            "maintenance": {},
        },
    )
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    payload = rt_runtime_router.get_rt_status()
    assert payload["rt_handle_ready"] is True
    assert payload["perception_started"] is True
    assert payload["started"] is True
    assert payload["paused"] is False
    assert payload["skipped_roles"] == [{"role": "c4", "reason": "no_camera_config"}]
    assert payload["runtime_health"] == {}
    assert payload["runtime_debug"] == {}
    assert payload["maintenance"] == {}

    feeds = {entry["feed_id"]: entry for entry in payload["runners"]}
    assert set(feeds.keys()) == {"c2_feed", "c3_feed"}
    assert feeds["c2_feed"]["detector_slug"] == "hive:c-channel-yolo11n-320"
    assert feeds["c2_feed"]["zone_kind"] == "rect"
    assert feeds["c3_feed"]["zone_kind"] == "polygon"
    assert feeds["c2_feed"]["running"] is True
    assert feeds["c2_feed"]["detection_count"] is None
    assert feeds["c2_feed"]["raw_track_count"] is None
    assert feeds["c2_feed"]["confirmed_track_count"] is None
    assert feeds["c2_feed"]["confirmed_real_track_count"] is None


def test_rt_status_distinguishes_idle_perception_from_full_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle([], started=False, perception_started=True)
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    payload = rt_runtime_router.get_rt_status()

    assert payload["rt_handle_ready"] is True
    assert payload["perception_started"] is True
    assert payload["started"] is False


def test_rt_status_surfaces_runtime_and_slot_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(
        [],
        snapshot={
            "perception_started": True,
            "started": True,
            "paused": False,
            "runners": [
                {
                    "feed_id": "c2_feed",
                    "detector_slug": "hive:c-channel-yolo11n-320",
                    "zone_kind": "rect",
                    "running": True,
                    "last_frame_age_ms": 12.5,
                    "detection_count": 2,
                    "raw_track_count": 2,
                    "confirmed_track_count": 2,
                    "confirmed_real_track_count": 1,
                    "raw_track_preview": [],
                    "confirmed_track_preview": [],
                },
            ],
            "skipped_roles": [],
            "runtime_health": {
                "c2": {"state": "idle", "blocked_reason": None, "last_tick_ms": 1.2}
            },
            "runtime_debug": {"c2": {"ring_count": 4, "downstream_taken": 1}},
            "slot_debug": {
                "c2_to_c3": {"capacity": 1, "taken": 1, "available": 0}
            },
            "maintenance": {},
        },
    )
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    payload = rt_runtime_router.get_rt_status()

    runner = payload["runners"][0]
    assert runner["detection_count"] == 2
    assert runner["raw_track_count"] == 2
    assert runner["confirmed_track_count"] == 2
    assert runner["confirmed_real_track_count"] == 1
    assert payload["runtime_debug"]["c2"] == {"ring_count": 4, "downstream_taken": 1}
    assert payload["slot_debug"]["c2_to_c3"] == {
        "capacity": 1,
        "taken": 1,
        "available": 0,
    }


def test_rt_status_surfaces_maintenance_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle(
        [],
        snapshot={
            "perception_started": True,
            "started": True,
            "paused": False,
            "runners": [],
            "skipped_roles": [],
            "runtime_health": {},
            "runtime_debug": {},
            "slot_debug": {},
            "maintenance": {
                "c234_purge": {
                    "active": True,
                    "phase": "purging",
                    "counts": {"c2": 2, "c3": 1, "c4_raw": 1, "c4_dossiers": 0},
                }
            },
        },
    )
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    payload = rt_runtime_router.get_rt_status()

    assert payload["maintenance"] == {
        "c234_purge": {
            "active": True,
            "phase": "purging",
            "counts": {"c2": 2, "c3": 1, "c4_raw": 1, "c4_dossiers": 0},
        }
    }


def test_start_c234_purge_endpoint_starts_handle_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle([])
    handle.start_c234_purge = MagicMock(return_value=True)  # type: ignore[attr-defined]
    handle.c234_purge_status = MagicMock(  # type: ignore[attr-defined]
        return_value={"active": True, "phase": "starting"}
    )
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)
    monkeypatch.setattr(shared_state, "hardware_state", "ready", raising=False)
    monkeypatch.setattr(shared_state, "publishSorterState", MagicMock(), raising=False)
    monkeypatch.setattr(shared_state, "getActiveIRL", lambda: None, raising=False)

    payload = rt_runtime_router.start_c234_purge()

    assert payload == {"ok": True, "status": {"active": True, "phase": "starting"}}
    handle.start_c234_purge.assert_called_once()


def test_start_c234_purge_endpoint_requires_ready_hardware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle([])
    handle.start_c234_purge = MagicMock(return_value=True)  # type: ignore[attr-defined]
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)
    monkeypatch.setattr(shared_state, "hardware_state", "standby", raising=False)

    with pytest.raises(Exception) as exc_info:
        rt_runtime_router.start_c234_purge()

    assert getattr(exc_info.value, "status_code", None) == 409
    handle.start_c234_purge.assert_not_called()


def test_cancel_c234_purge_endpoint_forwards_to_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handle = _FakeHandle([])
    handle.cancel_c234_purge = MagicMock(return_value=True)  # type: ignore[attr-defined]
    handle.c234_purge_status = MagicMock(  # type: ignore[attr-defined]
        return_value={"active": True, "phase": "cancelling", "cancel_requested": True}
    )
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    payload = rt_runtime_router.cancel_c234_purge()

    assert payload == {
        "ok": True,
        "cancelled": True,
        "status": {
            "active": True,
            "phase": "cancelling",
            "cancel_requested": True,
        },
    }
    handle.cancel_c234_purge.assert_called_once()


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
        "server.services.detection_config.getFeederDetectionConfig",
        lambda: {},
    )
    monkeypatch.setattr(
        "server.services.detection_config.setFeederDetectionConfig",
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
        "server.services.detection_config.getClassificationChannelDetectionConfig",
        lambda: {},
    )
    monkeypatch.setattr(
        "server.services.detection_config.setClassificationChannelDetectionConfig",
        lambda cfg: None,
    )

    payload = detection_router.AuxiliaryDetectionConfigPayload(
        algorithm="hive:c-channel-yolo11n-320",
    )
    detection_router.save_carousel_detection_config(payload=payload)

    handle.rebuild_runner_for_role.assert_called_once_with("c4")


def test_save_config_without_rt_handle_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No rt handle → no exception, no rebuild."""
    monkeypatch.setattr(shared_state, "rt_handle", None, raising=False)
    monkeypatch.setattr(
        "server.services.detection_config.getFeederDetectionConfig",
        lambda: {},
    )
    monkeypatch.setattr(
        "server.services.detection_config.setFeederDetectionConfig",
        lambda cfg: None,
    )

    payload = detection_router.AuxiliaryDetectionConfigPayload(
        algorithm="hive:c-channel-yolo11n-320",
    )
    # Should not raise.
    result = detection_router.save_feeder_detection_config(payload=payload, role="c_channel_2")
    assert result["ok"] is True


def test_save_classification_config_uses_service_and_applies_vm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saved_configs: list[dict[str, Any]] = []

    class _FakeVisionManager:
        def __init__(self) -> None:
            self.algorithm: str | None = None
            self.openrouter_model: str | None = None

        def setClassificationDetectionAlgorithm(self, algorithm: str) -> bool:
            self.algorithm = algorithm
            return True

        def setClassificationOpenRouterModel(self, model: str) -> None:
            self.openrouter_model = model

    vision_manager = _FakeVisionManager()
    monkeypatch.setattr(shared_state, "vision_manager", vision_manager, raising=False)
    monkeypatch.setattr(
        "server.services.detection_config.setClassificationDetectionConfig",
        lambda cfg: saved_configs.append(dict(cfg)),
    )

    payload = detection_router.ClassificationDetectionConfigPayload(
        algorithm="hive:classification-chamber-yolo11n-320",
        openrouter_model="google/gemini-3-flash-preview",
    )
    result = detection_router.save_classification_detection_config(payload=payload)

    assert result["ok"] is True
    assert result["algorithm"] == "hive:classification-chamber-yolo11n-320"
    assert result["baseline_loaded"] is True
    assert saved_configs == [
        {
            "algorithm": "hive:classification-chamber-yolo11n-320",
            "openrouter_model": "google/gemini-3-flash-preview",
        }
    ]
    assert vision_manager.algorithm == "hive:classification-chamber-yolo11n-320"
    assert vision_manager.openrouter_model == "google/gemini-3-flash-preview"


def test_get_classification_channel_config_uses_c4_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "server.routers.detection._public_aux_scope",
        lambda: "classification_channel",
    )
    monkeypatch.setattr(
        "server.routers.detection.getClassificationChannelDetectionConfig",
        lambda: {"algorithm": "hive:c-channel-yolo11n-320"},
    )
    monkeypatch.setattr(shared_state, "vision_manager", None, raising=False)

    payload = detection_router.get_carousel_detection_config()

    assert payload["algorithm"] == "hive:c-channel-yolo11n-320"
    assert [item["id"] for item in payload["available_algorithms"]] == [
        "hive:c-channel-yolo11n-320"
    ]


def test_save_polygons_rebuilds_rt_perception_runners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "blob_manager.setChannelPolygons",
        lambda payload: recorded.append(("channel", payload)),
    )
    monkeypatch.setattr(
        "blob_manager.setClassificationPolygons",
        lambda payload: recorded.append(("classification", payload)),
    )

    handle = MagicMock()
    handle.rebuild_runner_for_role = MagicMock(
        side_effect=[object(), object(), object()]
    )
    monkeypatch.setattr(shared_state, "rt_handle", handle, raising=False)

    payload = api_module.save_polygons(
        {
            "channel": {"polygons": {"classification_channel": []}},
            "classification": {"polygons": {"top": []}},
        }
    )

    assert recorded == [
        ("channel", {"polygons": {"classification_channel": []}}),
        ("classification", {"polygons": {"top": []}}),
    ]
    assert payload["ok"] is True
    assert payload["requires_restart"] is False
    assert payload["rt_rebuild_attempted_roles"] == ["c2", "c3", "c4"]
    assert payload["rt_rebuilt_roles"] == ["c2", "c3", "c4"]
    assert payload["rt_rebuild_failed_roles"] == []
    assert handle.rebuild_runner_for_role.call_args_list == [
        call("c2"),
        call("c3"),
        call("c4"),
    ]
