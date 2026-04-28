from rt.services.feeder_ladder import run_feeder_ladder_selftest


def test_feeder_ladder_selftest_passes() -> None:
    payload = run_feeder_ladder_selftest()

    assert payload["ok"] is True
    assert payload["scenario_count"] >= 6
    names = {scenario["name"] for scenario in payload["scenarios"]}
    assert "happy_path_c1_to_c3_to_c4_event" in names
    assert "c3_suspect_multi_payload" in names
    assert "c1_recovery_admission_denied" in names
