from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.routers.steppers import _validate_manual_move_safety


def test_manual_stepper_move_rejects_excessive_degrees() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_manual_move_safety(
            degrees=721.0,
            speed=12_000,
            min_speed=6_000,
            acceleration=80_000,
        )

    assert exc.value.status_code == 400
    assert "degrees exceeds" in str(exc.value.detail)


def test_manual_stepper_move_rejects_excessive_speed() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_manual_move_safety(
            degrees=360.0,
            speed=12_001,
            min_speed=6_000,
            acceleration=80_000,
        )

    assert exc.value.status_code == 400
    assert "speed exceeds" in str(exc.value.detail)


def test_manual_stepper_move_rejects_excessive_acceleration() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_manual_move_safety(
            degrees=360.0,
            speed=12_000,
            min_speed=6_000,
            acceleration=80_001,
        )

    assert exc.value.status_code == 400
    assert "acceleration exceeds" in str(exc.value.detail)


def test_manual_stepper_move_accepts_safe_boundary_values() -> None:
    _validate_manual_move_safety(
        degrees=-720.0,
        speed=12_000,
        min_speed=6_000,
        acceleration=80_000,
    )


def test_carousel_manual_move_uses_tighter_debug_limits() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_manual_move_safety(
            degrees=37.0,
            speed=250,
            min_speed=250,
            acceleration=600,
            stepper_name="carousel",
        )

    assert exc.value.status_code == 400
    assert "degrees exceeds" in str(exc.value.detail)


def test_carousel_manual_move_accepts_small_ramped_probe() -> None:
    _validate_manual_move_safety(
        degrees=9.0,
        speed=120,
        min_speed=16,
        acceleration=300,
        stepper_name="carousel",
    )


def test_carousel_manual_move_rejects_aggressive_acceleration() -> None:
    with pytest.raises(HTTPException) as exc:
        _validate_manual_move_safety(
            degrees=36.0,
            speed=250,
            min_speed=16,
            acceleration=601,
            stepper_name="carousel",
        )

    assert exc.value.status_code == 400
    assert "acceleration exceeds" in str(exc.value.detail)
