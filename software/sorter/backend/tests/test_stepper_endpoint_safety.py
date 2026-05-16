from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from server import shared_state
from server.routers import steppers


class _RejectingStepper:
    def __init__(self) -> None:
        self.enabled = False
        self.stopped = True
        self.speed_limits: list[tuple[int, int]] = []

    def move_at_speed(self, _speed: int) -> bool:
        return False

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits.append((int(min_speed), int(max_speed)))

    def move_degrees(self, _degrees: float) -> bool:
        return False


@pytest.fixture(autouse=True)
def _reset_motion_state(monkeypatch):
    old_state = shared_state.hardware_state
    old_worker = shared_state.hardware_worker_thread
    shared_state.hardware_state = "standby"
    shared_state.hardware_worker_thread = None
    shared_state.pulse_locks.clear()
    yield
    shared_state.hardware_state = old_state
    shared_state.hardware_worker_thread = old_worker
    shared_state.pulse_locks.clear()


def test_pulse_reports_rejected_firmware_start_and_releases_lock(monkeypatch) -> None:
    stepper = _RejectingStepper()
    monkeypatch.setattr(
        steppers.shared_state,
        "getActiveIRL",
        lambda: SimpleNamespace(carousel_stepper=stepper),
    )

    with pytest.raises(HTTPException) as exc:
        steppers.pulse_stepper("carousel", "cw", duration_s=0.1, speed=100)

    assert exc.value.status_code == 500
    assert "move_at_speed was not acknowledged" in str(exc.value.detail)
    assert not shared_state.pulse_locks["carousel"].locked()


def test_move_degrees_reports_rejected_firmware_start_and_releases_lock(monkeypatch) -> None:
    stepper = _RejectingStepper()
    monkeypatch.setattr(
        steppers.shared_state,
        "getActiveIRL",
        lambda: SimpleNamespace(carousel_stepper=stepper),
    )

    with pytest.raises(HTTPException) as exc:
        steppers.move_stepper_degrees("carousel", degrees=1.0, speed=100)

    assert exc.value.status_code == 500
    assert "move_degrees was not acknowledged" in str(exc.value.detail)
    assert not shared_state.pulse_locks["carousel"].locked()


def test_move_degrees_halts_if_background_stopped_poll_crashes(monkeypatch) -> None:
    class Stepper:
        def __init__(self) -> None:
            self.enabled = False
            self.halted = False

        def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
            pass

        def move_degrees(self, _degrees: float) -> bool:
            return True

        @property
        def stopped(self) -> bool:
            raise RuntimeError("poll failed")

        def halt(self, *, disable_driver: bool = True) -> bool:
            self.halted = disable_driver
            return True

    class ImmediateThread:
        def __init__(self, target, args=(), daemon=False) -> None:
            self._target = target
            self._args = args

        def start(self) -> None:
            self._target(*self._args)

    stepper = Stepper()
    monkeypatch.setattr(
        steppers.shared_state,
        "getActiveIRL",
        lambda: SimpleNamespace(carousel_stepper=stepper),
    )
    monkeypatch.setattr(steppers.threading, "Thread", ImmediateThread)

    response = steppers.move_stepper_degrees("carousel", degrees=1.0, speed=100)

    assert response.success is True
    assert stepper.halted is True
    assert not shared_state.pulse_locks["carousel"].locked()
