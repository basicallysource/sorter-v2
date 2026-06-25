from __future__ import annotations

import asyncio
import importlib.util
import sys
from types import SimpleNamespace
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "probe_webrtc_view_scaling.py"
SPEC = importlib.util.spec_from_file_location("probe_webrtc_view_scaling", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)


def _sessions(*, peers: int, encoders: int, subscribers: int, compliant: bool = True) -> dict:
    return {
        "ok": True,
        "target_ready": True,
        "target_architecture_compliant": compliant,
        "sessions": [
            {
                "physical_source": "video:5",
                "roles": ["c_channel_2", "feeder"],
            }
        ],
        "runtime": {
            "active_peer_count_by_source": {"video:5": peers},
            "active_encoder_instances_by_source": {"video:5": encoders},
            "fanout_subscriber_count_by_source": {"video:5": subscribers},
            "active_view_to_encoder_ratio": peers / encoders if encoders else None,
            "encoder_scaling_model": "per_physical_source"
            if encoders <= 1
            else "per_view_or_invalid",
            "process_resource": {
                "wall_time_monotonic_s": 10.0 + peers,
                "process_cpu_seconds": 2.0 + peers * 0.05,
            },
        },
        "runtime_invariants": {
            "one_active_encoder_per_physical_source": encoders <= 1,
            "encoder_count_does_not_scale_with_views": encoders <= 1,
            "multi_view_sources_share_one_encoder": encoders == 1,
            "fanout_subscribers_match_active_peers": subscribers == peers,
            "software_h264_fallback_forbidden": True,
        },
    }


def test_view_scaling_probe_accepts_multi_view_single_encoder_runtime() -> None:
    payload = probe.evaluate_view_scaling_result(
        role="c_channel_2",
        requested_views=3,
        opened_views=3,
        before_sessions=_sessions(peers=0, encoders=0, subscribers=0),
        after_sessions=_sessions(peers=3, encoders=1, subscribers=3),
    )

    assert payload["ok"] is True
    assert payload["physical_source"] == "video:5"
    assert payload["active_peers_for_source"] == 3
    assert payload["active_encoders_for_source"] == 1
    assert payload["fanout_subscribers_for_source"] == 3
    assert payload["encoder_scaling_model"] == "per_physical_source"
    assert payload["cpu_delta"]["available"] is True
    assert payload["cpu_delta"]["process_cpu_seconds"] == 0.15
    assert payload["missing"] == []


def test_view_scaling_probe_rejects_per_view_encoder_runtime() -> None:
    payload = probe.evaluate_view_scaling_result(
        role="c_channel_2",
        requested_views=3,
        opened_views=3,
        before_sessions=_sessions(peers=0, encoders=0, subscribers=0),
        after_sessions=_sessions(peers=3, encoders=3, subscribers=3),
    )

    assert payload["ok"] is False
    assert payload["active_encoders_for_source"] == 3
    assert payload["encoder_scaling_model"] == "per_view_or_invalid"
    assert any("expected one" in item for item in payload["missing"])
    assert any(
        "one_active_encoder_per_physical_source" in item
        for item in payload["missing"]
    )


def test_view_scaling_probe_rejects_missing_fanout_subscribers() -> None:
    payload = probe.evaluate_view_scaling_result(
        role="c_channel_2",
        requested_views=3,
        opened_views=3,
        before_sessions=_sessions(peers=0, encoders=0, subscribers=0),
        after_sessions=_sessions(peers=3, encoders=1, subscribers=1),
    )

    assert payload["ok"] is False
    assert payload["fanout_subscribers_for_source"] == 1
    assert any("Fanout reports 1 subscribers" in item for item in payload["missing"])
    assert any(
        "fanout_subscribers_match_active_peers" in item
        for item in payload["missing"]
    )


def test_view_scaling_probe_refuses_to_open_views_until_target_architecture_is_compliant(monkeypatch) -> None:
    def fake_json_request(method: str, url: str, payload=None, *, timeout_s: float = 8.0) -> dict:
        del method, url, payload, timeout_s
        return {
            **_sessions(peers=0, encoders=0, subscribers=0, compliant=False),
            "blockers": ["staging source pipeline"],
            "migration_warnings": [],
            "gates": {
                "target_ready": True,
                "target_architecture_compliant": False,
                "source_pipeline_target_compliant": False,
            },
        }

    monkeypatch.setattr(probe, "_json_request", fake_json_request)
    args = SimpleNamespace(
        backend_url="http://backend.test",
        role="c_channel_2",
        views=3,
        settle_s=0.0,
    )

    payload = asyncio.run(probe.run_probe(args))

    assert payload["ok"] is False
    assert payload["reason"] == "Hardware WebRTC transport is not target-architecture compliant."
    assert payload["blockers"] == ["staging source pipeline"]
    assert payload["gates"]["source_pipeline_target_compliant"] is False
