from __future__ import annotations

import pytest

from rt.services.c4_optical_home import (
    phase_error_for_detection,
    run_c4_optical_home,
)


def test_phase_error_for_detection_uses_sector_phase() -> None:
    assert phase_error_for_detection(
        {"ok": True, "sector_offset_deg": 4.0},
        target_wall_angle_deg=30.0,
        sector_count=5,
    ) == pytest.approx(26.0)


def test_optical_home_applies_runtime_phase_when_aligned() -> None:
    applied: list[dict] = []

    payload = run_c4_optical_home(
        detect_phase=lambda: {
            "ok": True,
            "sector_count": 5,
            "sector_offset_deg": 30.5,
        },
        move_tray_degrees=lambda _deg: False,
        apply_phase=lambda result: applied.append(dict(result)) or True,
        target_wall_angle_deg=30.0,
        sector_count=5,
        tolerance_deg=2.5,
        execute_move=False,
        max_iterations=0,
    )

    assert payload["ok"] is True
    assert payload["applied_to_runtime"] is True
    assert applied[0]["sector_offset_deg"] == pytest.approx(30.5)
    assert payload["iterations"][0]["message"] == "target phase reached"


def test_optical_home_does_not_probe_when_already_aligned() -> None:
    moves: list[float] = []

    payload = run_c4_optical_home(
        detect_phase=lambda: {
            "ok": True,
            "sector_count": 5,
            "sector_offset_deg": 30.0,
        },
        move_tray_degrees=lambda deg: moves.append(float(deg)) or True,
        apply_phase=lambda _result: True,
        target_wall_angle_deg=30.0,
        sector_count=5,
        tolerance_deg=2.5,
        execute_move=True,
        probe_move_deg=2.0,
        max_iterations=2,
    )

    assert payload["ok"] is True
    assert moves == []
    assert payload["probe"] is None


def test_optical_home_default_uses_nominal_gain_without_probe() -> None:
    offset = 0.0
    moves: list[float] = []

    def detect_phase() -> dict:
        return {
            "ok": True,
            "sector_count": 5,
            "sector_offset_deg": offset,
        }

    def move_tray_degrees(deg: float) -> bool:
        nonlocal offset
        moves.append(float(deg))
        offset += float(deg)
        return True

    payload = run_c4_optical_home(
        detect_phase=detect_phase,
        move_tray_degrees=move_tray_degrees,
        apply_phase=lambda _result: True,
        target_wall_angle_deg=30.0,
        sector_count=5,
        tolerance_deg=2.5,
        settle_s=0.0,
        max_iterations=5,
    )

    assert payload["ok"] is True
    assert payload["probe"] == {"source": "payload", "motion_response_gain": 1.0}
    assert moves == pytest.approx([12.0, 12.0, 6.0])
    assert payload["motion_response_gain"] == pytest.approx(1.0)
    assert payload["iterations"][0]["move_clamped"] is True


def test_optical_home_uses_probe_gain_and_correction_move() -> None:
    offset = 0.0
    moves: list[float] = []

    def detect_phase() -> dict:
        return {
            "ok": True,
            "sector_count": 5,
            "sector_offset_deg": offset,
        }

    def move_tray_degrees(deg: float) -> bool:
        nonlocal offset
        moves.append(float(deg))
        offset += float(deg)
        return True

    payload = run_c4_optical_home(
        detect_phase=detect_phase,
        move_tray_degrees=move_tray_degrees,
        apply_phase=lambda _result: True,
        target_wall_angle_deg=30.0,
        sector_count=5,
        tolerance_deg=2.5,
        motion_response_gain=None,
        probe_move_deg=2.0,
        max_move_deg=None,
        settle_s=0.0,
        max_iterations=2,
    )

    assert payload["ok"] is True
    assert moves == pytest.approx([2.0, 28.0])
    assert payload["motion_response_gain"] == pytest.approx(1.0)
    assert payload["iterations"][-1]["phase_error_deg"] == pytest.approx(0.0)


def test_optical_home_does_not_apply_failed_phase() -> None:
    applied: list[dict] = []

    payload = run_c4_optical_home(
        detect_phase=lambda: {
            "ok": True,
            "sector_count": 5,
            "sector_offset_deg": 0.0,
        },
        move_tray_degrees=lambda _deg: False,
        apply_phase=lambda result: applied.append(dict(result)) or True,
        target_wall_angle_deg=30.0,
        sector_count=5,
        tolerance_deg=2.5,
        execute_move=False,
        max_iterations=0,
    )

    assert payload["ok"] is False
    assert payload["applied_to_runtime"] is False
    assert applied == []
    assert payload["iterations"][0]["message"] == "no further correction attempted"
