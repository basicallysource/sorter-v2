from __future__ import annotations

import json
from pathlib import Path

import pytest

from rt.services.sector_shadow_observer import (
    ACTION_IDLE,
    ACTION_PULSE_NORMAL,
    ACTION_PULSE_PRECISE,
    ChannelGeometry,
    SectorShadowObserver,
    classify_channel,
)


_C2_GEOM = ChannelGeometry(
    name="c2",
    exit_arc_deg=30.0,
    intake_center_deg=180.0,
    intake_arc_deg=30.0,
)
_C3_GEOM = ChannelGeometry(
    name="c3",
    exit_arc_deg=20.0,
    intake_center_deg=180.0,
    intake_arc_deg=30.0,
)


def test_classify_channel_idle_when_empty() -> None:
    obs = classify_channel(_C2_GEOM, [])
    assert obs.action == ACTION_IDLE
    assert obs.piece_count == 0
    assert obs.intake_occupied is False


def test_classify_channel_normal_when_only_in_middle() -> None:
    # 90° is well outside both the exit (±30°) and intake (180° ± 30°) arcs.
    obs = classify_channel(_C2_GEOM, [90.0, -90.0])
    assert obs.action == ACTION_PULSE_NORMAL
    assert obs.piece_count == 2
    assert obs.pieces_in_exit == 0
    assert obs.pieces_in_intake == 0
    assert obs.intake_occupied is False


def test_classify_channel_precise_when_in_exit_arc() -> None:
    obs = classify_channel(_C2_GEOM, [12.0, -90.0])
    assert obs.action == ACTION_PULSE_PRECISE
    assert obs.pieces_in_exit == 1


def test_classify_channel_intake_occupied_near_intake_center() -> None:
    obs = classify_channel(_C2_GEOM, [-170.0])
    assert obs.intake_occupied is True
    assert obs.action == ACTION_PULSE_NORMAL  # not in exit arc


def test_classify_channel_handles_wrap_around_at_180() -> None:
    # 175° is within ±30° of intake_center=180°.
    obs = classify_channel(_C2_GEOM, [175.0])
    assert obs.intake_occupied is True
    # And the wrapped equivalent at -179° should also count.
    obs2 = classify_channel(_C2_GEOM, [-179.0])
    assert obs2.intake_occupied is True


def _provider(payload: dict) -> "object":
    def _read() -> dict:
        return dict(payload)
    return _read


def test_observer_records_main_allows_when_intake_clear() -> None:
    payload = {
        "c2_tracks": [{"angle_deg": -90.0}],   # nothing in intake or exit
        "c3_tracks": [],
        "c4_intake_blocked": False,
        "sorthive_c1_blocked_reason": None,
        "sorthive_c2_blocked_reason": None,
        "sorthive_c3_blocked_reason": None,
    }
    obs = SectorShadowObserver(
        snapshot_provider=_provider(payload),
        c2_geometry=_C2_GEOM,
        c3_geometry=_C3_GEOM,
        sample_period_s=0.001,
    )
    obs.tick(now_mono=0.0)
    sample = obs.recent()[0]
    assert sample["main_allow_c1"] is True
    assert sample["main_allow_c2"] is True
    assert sample["main_allow_c3"] is True
    assert sample["divergence_c1"] is False


def test_observer_flags_divergence_when_sorthive_blocks_but_main_allows() -> None:
    payload = {
        "c2_tracks": [{"angle_deg": -45.0}],   # 1 piece, not in intake
        "c3_tracks": [],
        "c4_intake_blocked": False,
        "sorthive_c1_blocked_reason": "vision_target_band",
        "sorthive_c2_blocked_reason": None,
        "sorthive_c3_blocked_reason": None,
    }
    obs = SectorShadowObserver(
        snapshot_provider=_provider(payload),
        c2_geometry=_C2_GEOM,
        c3_geometry=_C3_GEOM,
        sample_period_s=0.001,
    )
    obs.tick(now_mono=0.0)
    sample = obs.recent()[0]
    # Main: C2 intake clear → C1 allowed.
    # Sorthive: C1 blocked by vision_target_band.
    # That's a divergence.
    assert sample["main_allow_c1"] is True
    assert sample["sorthive_c1_blocked_reason"] == "vision_target_band"
    assert sample["divergence_c1"] is True

    summary = obs.summary()
    assert summary["divergence_counts"]["c1"] == 1


def test_observer_downsamples_to_sample_period() -> None:
    payload = {
        "c2_tracks": [],
        "c3_tracks": [],
        "c4_intake_blocked": False,
        "sorthive_c1_blocked_reason": None,
        "sorthive_c2_blocked_reason": None,
        "sorthive_c3_blocked_reason": None,
    }
    obs = SectorShadowObserver(
        snapshot_provider=_provider(payload),
        c2_geometry=_C2_GEOM,
        c3_geometry=_C3_GEOM,
        sample_period_s=0.5,
    )
    obs.tick(now_mono=0.0)
    obs.tick(now_mono=0.1)
    obs.tick(now_mono=0.2)
    obs.tick(now_mono=0.6)
    assert obs.summary()["sample_count"] == 2


def test_observer_persists_jsonl(tmp_path: Path) -> None:
    log_path = tmp_path / "shadow.jsonl"
    payload = {
        "c2_tracks": [{"angle_deg": 5.0}],     # in C2 exit arc
        "c3_tracks": [],
        "c4_intake_blocked": False,
        "sorthive_c1_blocked_reason": None,
        "sorthive_c2_blocked_reason": None,
        "sorthive_c3_blocked_reason": None,
    }
    obs = SectorShadowObserver(
        snapshot_provider=_provider(payload),
        c2_geometry=_C2_GEOM,
        c3_geometry=_C3_GEOM,
        sample_period_s=0.001,
        log_path=log_path,
    )
    obs.tick(now_mono=0.0)
    obs.tick(now_mono=1.0)

    rows = log_path.read_text().splitlines()
    assert len(rows) == 2
    first = json.loads(rows[0])
    assert first["c2"]["pieces_in_exit"] == 1
    assert first["c2"]["action"] == ACTION_PULSE_PRECISE


def test_observer_provider_failure_does_not_crash() -> None:
    def _broken() -> dict:
        raise RuntimeError("boom")

    obs = SectorShadowObserver(
        snapshot_provider=_broken,
        c2_geometry=_C2_GEOM,
        c3_geometry=_C3_GEOM,
        sample_period_s=0.001,
    )
    obs.tick(now_mono=0.0)
    obs.tick(now_mono=1.0)
    # Provider failure should not be recorded as a sample.
    assert obs.summary()["sample_count"] == 0


def test_observer_rejects_nonpositive_sample_period() -> None:
    with pytest.raises(ValueError, match="sample_period_s"):
        SectorShadowObserver(
            snapshot_provider=_provider({}),
            c2_geometry=_C2_GEOM,
            c3_geometry=_C3_GEOM,
            sample_period_s=0.0,
        )
