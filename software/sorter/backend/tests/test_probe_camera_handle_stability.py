from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_camera_handle_stability.py"
SPEC = importlib.util.spec_from_file_location("probe_camera_handle_stability", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def _media_plane(*, handles: int, processes: int = 1, captures: int = 1, legacy_clients: int = 0) -> dict:
    return {
        "ok": True,
        "roles": {
            "c_channel_2": {
                "physical_source": "video:5",
            }
        },
        "physical_sources": [
            {
                "source": "video:5",
                "roles": ["c_channel_2", "feeder"],
                "capture_instances": captures,
                "os_handle_audit": {
                    "available": True,
                    "expected_device_path": "/dev/video5",
                    "handle_count": handles,
                    "process_count": processes,
                    "processes": [],
                },
            }
        ],
        "legacy_transports": {
            "mjpeg": {
                "active_clients": legacy_clients,
            }
        },
    }


def test_handle_stability_accepts_multiple_clients_without_extra_video_handles() -> None:
    result = probe.evaluate_handle_stability(
        role="c_channel_2",
        expected_clients=2,
        connected_clients=2,
        before=_media_plane(handles=1, legacy_clients=0),
        during=_media_plane(handles=1, legacy_clients=2),
        after=_media_plane(handles=1, legacy_clients=0),
    )

    assert result["ok"] is True
    assert result["physical_source"] == "video:5"
    assert result["legacy_mjpeg_active_clients_during"] == 2
    assert result["before"]["handle_count"] == 1
    assert result["during"]["handle_count"] == 1
    assert result["after"]["handle_count"] == 1
    assert result["missing"] == []


def test_handle_stability_rejects_extra_video_handle_during_clients() -> None:
    result = probe.evaluate_handle_stability(
        role="c_channel_2",
        expected_clients=2,
        connected_clients=2,
        before=_media_plane(handles=1),
        during=_media_plane(handles=2, legacy_clients=2),
        after=_media_plane(handles=1),
    )

    assert result["ok"] is False
    assert any("handle count grew from 1 to 2" in item for item in result["missing"])


def test_handle_stability_rejects_duplicate_capture_instances() -> None:
    result = probe.evaluate_handle_stability(
        role="c_channel_2",
        expected_clients=2,
        connected_clients=2,
        before=_media_plane(handles=1),
        during=_media_plane(handles=1, captures=2, legacy_clients=2),
        after=_media_plane(handles=1),
    )

    assert result["ok"] is False
    assert any("Capture instances during stream test: 2" in item for item in result["missing"])


def test_handle_stability_rejects_unconnected_clients() -> None:
    result = probe.evaluate_handle_stability(
        role="c_channel_2",
        expected_clients=2,
        connected_clients=1,
        before=_media_plane(handles=1),
        during=_media_plane(handles=1, legacy_clients=1),
        after=_media_plane(handles=1),
    )

    assert result["ok"] is False
    assert any("Connected 1 of 2 requested" in item for item in result["missing"])
