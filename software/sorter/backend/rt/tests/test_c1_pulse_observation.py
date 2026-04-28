from __future__ import annotations

import json
from pathlib import Path

import pytest

from rt.services.c1_pulse_observation import C1PulseObserver


def _provider(state: dict[str, float]) -> object:
    """Snapshot provider that returns the *current* contents of ``state``."""

    def _read() -> dict[str, float]:
        return dict(state)

    return _read


def test_pulse_observer_captures_pre_t1_t3() -> None:
    state: dict[str, float] = {"c2_piece_count_estimate": 0.0, "c4_dossier_count": 0.0}
    obs = C1PulseObserver(snapshot_provider=_provider(state))

    pulse_id = obs.record_dispatch("pulse", now_mono=10.0)
    assert pulse_id == 1
    assert obs.summary()["in_flight_count"] == 1
    assert obs.summary()["completed_count"] == 0

    # No deadline reached yet.
    obs.tick(now_mono=10.5)
    assert obs.summary()["in_flight_count"] == 1
    assert obs.in_flight()[0]["t1"] is None

    # +1.0 s deadline -> t1 captured, but observation not yet completed.
    state["c2_piece_count_estimate"] = 2.0
    obs.tick(now_mono=11.0)
    assert obs.summary()["in_flight_count"] == 1
    assert obs.in_flight()[0]["t1"] is not None
    assert obs.in_flight()[0]["t1"]["c2_piece_count_estimate"] == 2.0

    # +3.0 s deadline -> t3 captured + observation completed.
    state["c2_piece_count_estimate"] = 3.0
    state["c4_dossier_count"] = 1.0
    obs.tick(now_mono=13.0)
    assert obs.summary()["in_flight_count"] == 0
    assert obs.summary()["completed_count"] == 1

    recent = obs.recent()
    assert len(recent) == 1
    record = recent[0]
    assert record["pulse_id"] == 1
    assert record["action_id"] == "pulse"
    assert record["pre"]["c2_piece_count_estimate"] == 0.0
    assert record["t1"]["c2_piece_count_estimate"] == 2.0
    assert record["t3"]["c2_piece_count_estimate"] == 3.0
    assert record["delta_t1"]["c2_piece_count_estimate"] == 2.0
    assert record["delta_t3"]["c2_piece_count_estimate"] == 3.0
    assert record["delta_t3"]["c4_dossier_count"] == 1.0


def test_pulse_observer_persists_completed_records(tmp_path: Path) -> None:
    state: dict[str, float] = {"c2_piece_count_estimate": 1.0}
    log_path = tmp_path / "c1_pulses.jsonl"
    obs = C1PulseObserver(snapshot_provider=_provider(state), log_path=log_path)

    obs.record_dispatch("pulse", now_mono=0.0)
    obs.tick(now_mono=1.0)
    obs.tick(now_mono=3.0)

    rows = log_path.read_text().splitlines()
    assert len(rows) == 1
    payload = json.loads(rows[0])
    assert payload["pulse_id"] == 1
    assert payload["action_id"] == "pulse"
    assert payload["pre"]["c2_piece_count_estimate"] == 1.0


def test_pulse_observer_history_ring_caps_records() -> None:
    state: dict[str, float] = {"c2_piece_count_estimate": 0.0}
    obs = C1PulseObserver(
        snapshot_provider=_provider(state), history_limit=3
    )
    for n in range(5):
        obs.record_dispatch(f"pulse_{n}", now_mono=float(n) * 10)
        obs.tick(now_mono=float(n) * 10 + 1.0)
        obs.tick(now_mono=float(n) * 10 + 3.0)

    summary = obs.summary()
    assert summary["completed_count"] == 3
    recent = obs.recent(limit=10)
    assert [r["action_id"] for r in recent] == ["pulse_2", "pulse_3", "pulse_4"]


def test_pulse_observer_handles_provider_failures() -> None:
    def _broken_provider() -> dict[str, float]:
        raise RuntimeError("provider down")

    obs = C1PulseObserver(snapshot_provider=_broken_provider)

    # Even with a broken provider the observer must not raise — pre-state
    # falls back to {} so we still record the dispatch event itself.
    pulse_id = obs.record_dispatch("pulse", now_mono=0.0)
    assert pulse_id == 1
    obs.tick(now_mono=1.0)
    obs.tick(now_mono=3.0)

    record = obs.recent()[0]
    assert record["pre"] == {}
    assert record["t1"] == {}
    assert record["t3"] == {}


def test_pulse_observer_rejects_invalid_deadlines() -> None:
    state: dict[str, float] = {}
    with pytest.raises(ValueError, match="t1_s"):
        C1PulseObserver(snapshot_provider=_provider(state), t1_s=0.0)
    with pytest.raises(ValueError, match="t3_s"):
        C1PulseObserver(snapshot_provider=_provider(state), t1_s=2.0, t3_s=1.0)
