from __future__ import annotations

from rt.services.sector_carousel import run_sector_carousel_ladder_selftest


def test_sector_carousel_ladder_selftest_passes() -> None:
    payload = run_sector_carousel_ladder_selftest()

    assert payload["ok"] is True
    assert payload["scenario_count"] == 5
    assert payload["failed_count"] == 0
    names = {item["name"] for item in payload["scenarios"]}
    assert names == {
        "phase_gate",
        "single_piece_lifecycle",
        "five_token_ring",
        "fault_injection",
        "slow_classifier_stale_result",
    }
