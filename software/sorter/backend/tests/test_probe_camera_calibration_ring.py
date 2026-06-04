from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_camera_calibration_ring.py"
SPEC = importlib.util.spec_from_file_location("probe_camera_calibration_ring", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def _media_plane(
    *,
    age_ms: float = 42.0,
    handles: int = 1,
    captures: int = 1,
    ring_depth: int = 90,
    available: bool = True,
    latest: bool = True,
    second_capture: bool = False,
    legacy_cache: bool = False,
    source_exists: bool = True,
    timestamp: float = 100.0,
) -> dict:
    frame = (
        {
            "width": 1280,
            "height": 720,
            "timestamp": timestamp,
            "age_ms": age_ms,
            "has_uncorrected_raw": True,
        }
        if latest
        else None
    )
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
                "ring_buffer_depth": ring_depth,
                "source_exists": source_exists,
                "os_handle_audit": {
                    "available": True,
                    "expected_device_path": "/dev/video5",
                    "handle_count": handles,
                    "process_count": 1,
                    "processes": [],
                },
                "calibration_frame_source": {
                    "kind": "raw_ring_buffer",
                    "available": available,
                    "ring_buffer_depth": ring_depth,
                    "latest_frame_available": latest,
                    "latest_frame": frame,
                    "uses_second_capture": second_capture,
                    "uses_legacy_direct_stream_cache": legacy_cache,
                },
            }
        ],
    }


def test_calibration_ring_accepts_fresh_raw_ring_without_extra_capture() -> None:
    result = probe.evaluate_calibration_ring(
        roles=["c_channel_2"],
        before=_media_plane(timestamp=100.0),
        after=_media_plane(timestamp=101.0),
        max_age_ms=5000.0,
        require_frame_advance=True,
    )

    assert result["ok"] is True
    assert result["missing"] == []
    role_result = result["results"][0]
    assert role_result["physical_source"] == "video:5"
    assert role_result["kind"] == "raw_ring_buffer"
    assert role_result["ring_buffer_depth"] == 90
    assert role_result["uses_second_capture"] is False
    assert role_result["handle_count_before"] == 1
    assert role_result["handle_count_after"] == 1


def test_calibration_ring_rejects_second_capture_fallback() -> None:
    result = probe.evaluate_calibration_ring(
        roles=["c_channel_2"],
        before=_media_plane(),
        after=_media_plane(second_capture=True),
        max_age_ms=5000.0,
    )

    assert result["ok"] is False
    assert any("using a second capture" in item for item in result["missing"])


def test_calibration_ring_rejects_missing_latest_frame_or_empty_ring() -> None:
    result = probe.evaluate_calibration_ring(
        roles=["c_channel_2"],
        before=_media_plane(),
        after=_media_plane(available=False, latest=False, ring_depth=0),
        max_age_ms=5000.0,
    )

    assert result["ok"] is False
    assert any("unavailable" in item for item in result["missing"])
    assert any("Ring buffer depth" in item for item in result["missing"])
    assert any("No latest raw frame" in item for item in result["missing"])


def test_calibration_ring_rejects_stale_latest_frame() -> None:
    result = probe.evaluate_calibration_ring(
        roles=["c_channel_2"],
        before=_media_plane(age_ms=6000.0),
        after=_media_plane(age_ms=6000.0),
        max_age_ms=5000.0,
    )

    assert result["ok"] is False
    assert any("Latest raw frame age" in item for item in result["missing"])


def test_calibration_ring_rejects_missing_physical_source() -> None:
    result = probe.evaluate_calibration_ring(
        roles=["c_channel_2"],
        before=_media_plane(),
        after=_media_plane(source_exists=False),
        max_age_ms=5000.0,
    )

    assert result["ok"] is False
    assert any("does not exist" in item for item in result["missing"])


def test_calibration_ring_rejects_handle_growth_and_duplicate_capture() -> None:
    result = probe.evaluate_calibration_ring(
        roles=["c_channel_2"],
        before=_media_plane(handles=1, captures=1),
        after=_media_plane(handles=2, captures=2),
        max_age_ms=5000.0,
    )

    assert result["ok"] is False
    assert any("Capture instances" in item for item in result["missing"])
    assert any("handle count" in item for item in result["missing"])


def test_calibration_ring_rejects_non_advancing_frame_when_required() -> None:
    result = probe.evaluate_calibration_ring(
        roles=["c_channel_2"],
        before=_media_plane(timestamp=100.0),
        after=_media_plane(timestamp=100.0),
        max_age_ms=5000.0,
        require_frame_advance=True,
    )

    assert result["ok"] is False
    assert any("did not advance" in item for item in result["missing"])
