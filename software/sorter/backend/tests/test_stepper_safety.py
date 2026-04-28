from __future__ import annotations

import pytest
from fastapi import HTTPException

from server import shared_state
from server.routers import steppers
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


def test_carousel_manual_move_allows_large_degrees_but_caps_speed() -> None:
    _validate_manual_move_safety(
        degrees=7200.0,
        speed=steppers.CAROUSEL_MANUAL_MOVE_MAX_SPEED,
        min_speed=steppers.CAROUSEL_MANUAL_MOVE_MAX_MIN_SPEED,
        acceleration=steppers.CAROUSEL_MANUAL_MOVE_MAX_ACCELERATION,
        stepper_name="carousel",
    )

    with pytest.raises(HTTPException) as exc:
        _validate_manual_move_safety(
            degrees=7200.0,
            speed=steppers.CAROUSEL_MANUAL_MOVE_MAX_SPEED + 1,
            min_speed=16,
            acceleration=600,
            stepper_name="carousel",
        )

    assert exc.value.status_code == 400
    assert "speed exceeds" in str(exc.value.detail)


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
            acceleration=steppers.CAROUSEL_MANUAL_MOVE_MAX_ACCELERATION + 1,
            stepper_name="carousel",
        )

    assert exc.value.status_code == 400
    assert "acceleration exceeds" in str(exc.value.detail)


class _Stepper:
    def __init__(self) -> None:
        self.enabled_values: list[bool] = []
        self.speed_limits: list[tuple[int, int]] = []
        self.accelerations: list[int] = []
        self.moves: list[float] = []

    @property
    def enabled(self) -> bool:
        return bool(self.enabled_values[-1]) if self.enabled_values else False

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self.enabled_values.append(bool(value))

    @property
    def stopped(self) -> bool:
        return True

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits.append((int(min_speed), int(max_speed)))

    def set_acceleration(self, acceleration: int) -> None:
        self.accelerations.append(int(acceleration))

    def move_degrees(self, degrees: float) -> bool:
        self.moves.append(float(degrees))
        return True


def test_carousel_manual_move_gets_default_ramp_when_ui_sends_only_speed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stepper = _Stepper()
    monkeypatch.setattr(steppers, "_resolve_stepper", lambda _name: stepper)
    monkeypatch.setattr(steppers, "_validate_manual_move_safety", lambda **_kwargs: None)
    shared_state.pulse_locks.clear()

    response = steppers.move_stepper_degrees(
        stepper="carousel",
        degrees=30.0,
        speed=2000,
    )

    assert response.success is True
    assert stepper.enabled_values == [True]
    assert stepper.accelerations == [steppers.CAROUSEL_MANUAL_DEFAULT_ACCELERATION]
    assert stepper.speed_limits == [(steppers.CAROUSEL_MANUAL_DEFAULT_MIN_SPEED, 2000)]
    assert stepper.moves == [30.0]


def test_carousel_manual_default_ramp_passes_safety_at_conservative_speed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stepper = _Stepper()
    monkeypatch.setattr(steppers, "_resolve_stepper", lambda _name: stepper)
    shared_state.pulse_locks.clear()

    response = steppers.move_stepper_degrees(
        stepper="carousel",
        degrees=30.0,
        speed=250,
    )

    assert response.success is True
    assert stepper.enabled_values == [True]
    assert stepper.accelerations == [steppers.CAROUSEL_MANUAL_DEFAULT_ACCELERATION]
    assert stepper.speed_limits == [(steppers.CAROUSEL_MANUAL_DEFAULT_MIN_SPEED, 250)]
    assert stepper.moves == [30.0]
