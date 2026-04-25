from __future__ import annotations

from types import SimpleNamespace

from rt.perception.track_policy import (
    action_track,
    admission_basis,
    is_visible_track,
    stable_detection,
)


def _track(**overrides):
    data = {
        "ghost": False,
        "confirmed_real": False,
        "hit_count": 2,
        "score": 0.8,
        "first_seen_ts": 1.0,
        "last_seen_ts": 1.3,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_ghost_flag_is_diagnostic_by_default() -> None:
    ghost = _track(ghost=True, confirmed_real=True, hit_count=99, score=1.0)

    assert is_visible_track(ghost) is True
    assert stable_detection(ghost) is True
    assert action_track(ghost) is True
    assert admission_basis(ghost) == "confirmed_real"


def test_ghost_flag_can_be_reenabled_as_hard_negative(monkeypatch) -> None:
    monkeypatch.setenv("RT_TRACK_GHOST_HARD_NEGATIVE", "1")
    ghost = _track(ghost=True, confirmed_real=True, hit_count=99, score=1.0)

    assert is_visible_track(ghost) is False
    assert stable_detection(ghost) is False
    assert action_track(ghost) is False
    assert admission_basis(ghost) == "ghost"


def test_stable_detection_is_actionable_before_motion_confirmation() -> None:
    track = _track(confirmed_real=False, hit_count=2, score=0.6)

    assert is_visible_track(track) is True
    assert stable_detection(track) is True
    assert action_track(track) is True
    assert admission_basis(track) == "stable_detection"


def test_motion_confirmation_overrides_stability_thresholds() -> None:
    track = _track(confirmed_real=True, hit_count=1, score=0.1)

    assert stable_detection(track, min_hits=5, min_score=0.9) is True
    assert admission_basis(track) == "confirmed_real"
