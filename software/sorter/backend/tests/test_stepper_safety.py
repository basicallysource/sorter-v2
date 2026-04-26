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
