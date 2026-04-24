from __future__ import annotations

import logging

from rt.hardware.motion_profiles import (
    MotionDiagnostics,
    PROFILE_GENTLE,
    PROFILE_TRANSPORT,
    move_degrees_with_profile,
    plan_motion,
    profile_from_values,
)


class _Stepper:
    def __init__(self) -> None:
        self.accelerations: list[int] = []
        self.speed_limits: list[tuple[int, int]] = []
        self.moves: list[float] = []

    def set_acceleration(self, acceleration: int) -> None:
        self.accelerations.append(acceleration)

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits.append((min_speed, max_speed))

    def microsteps_for_degrees(self, degrees: float) -> int:
        return int(round(float(degrees) * 10.0))

    def move_degrees(self, degrees: float) -> bool:
        self.moves.append(degrees)
        return True


def test_plan_motion_warns_when_transport_cannot_reach_target_speed() -> None:
    profile = profile_from_values(
        channel="c4",
        name=PROFILE_TRANSPORT,
        max_speed=2400,
        acceleration=10000,
    )

    plan = plan_motion(profile, source="test", distance_usteps=60, degrees=6.0)

    assert plan.reaches_cruise is False
    assert plan.peak_speed_usteps_per_s is not None
    assert plan.peak_speed_usteps_per_s < 2400
    assert plan.warnings == ("target_speed_unreachable",)


def test_plan_motion_does_not_warn_for_gentle_short_positioning() -> None:
    profile = profile_from_values(
        channel="c4",
        name=PROFILE_GENTLE,
        max_speed=4200,
        acceleration=9000,
    )

    plan = plan_motion(profile, source="test", distance_usteps=20, degrees=2.0)

    assert plan.reaches_cruise is False
    assert plan.warnings == ()


def test_move_degrees_with_profile_applies_profile_and_records_diagnostics() -> None:
    stepper = _Stepper()
    diagnostics = MotionDiagnostics(warn_throttle_s=0.0)
    profile = profile_from_values(
        channel="c2",
        name=PROFILE_TRANSPORT,
        max_speed=5000,
        acceleration=2500,
    )

    ok = move_degrees_with_profile(
        stepper,
        profile,
        100.0,
        source="c2_transport",
        logger=logging.getLogger("test"),
        diagnostics=diagnostics,
        expected_duration_ms=40.0,
    )

    assert ok is True
    assert stepper.accelerations == [2500]
    assert stepper.speed_limits == [(16, 5000)]
    assert stepper.moves == [100.0]
    motion = diagnostics.status_snapshot()["last_by_profile"]["c2.transport"]
    assert motion["distance_usteps"] == 1000
    assert motion["ok"] is True
    assert "estimated_duration_exceeds_expected" in motion["warnings"]
