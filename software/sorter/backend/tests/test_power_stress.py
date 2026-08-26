import unittest
from typing import Any

from subsystems.power_stress import (
    MIN_SPEED,
    SAFE_ACCELERATION,
    PhaseSegment,
    PowerStressTestRunner,
    buildPhasePlan,
)


class FakeLogger:
    def info(self, _message: str) -> None:
        pass

    def warning(self, _message: str) -> None:
        pass


class FakeGlobalConfig:
    def __init__(self) -> None:
        self.logger = FakeLogger()


class FakeIRL:
    c_channel_1_rotor_stepper = None
    c_channel_2_rotor_stepper = None
    c_channel_3_rotor_stepper = None
    c_channel_4_rotor_stepper = None
    carousel_stepper = None


class FakeStepper:
    def __init__(self) -> None:
        self.name = "fake"
        self._stopped = False
        self.speed_limits: list[tuple[int, int]] = []
        self.accelerations: list[int] = []
        self.speeds: list[int] = []
        self.enabled = True

    @property
    def stopped(self) -> bool:
        return self._stopped

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits.append((min_speed, max_speed))

    def set_acceleration(self, acceleration: int) -> None:
        self.accelerations.append(acceleration)

    def move_at_speed(self, speed: int) -> bool:
        self.speeds.append(speed)
        if speed == 0:
            self._stopped = True
        return True


class PhasePlanTests(unittest.TestCase):
    def test_ten_minute_plan_has_equal_primary_phases(self) -> None:
        plan = buildPhasePlan(600)

        self.assertAlmostEqual(sum(item.duration_s for item in plan), 600)
        self.assertEqual(plan[0], PhaseSegment("stable", 1, 200))
        self.assertEqual(plan[1], PhaseSegment("random", 1, 200))
        self.assertTrue(all(item.phase == "mixed" for item in plan[2:]))

    def test_mixed_segment_uses_both_stepper_modes(self) -> None:
        runner = PowerStressTestRunner(FakeGlobalConfig(), FakeIRL())

        modes = runner._segmentModes(PhaseSegment("mixed", 1, 30))

        self.assertEqual(set(modes["steppers"].values()), {"continuous", "burst"})


class StepperStopSafetyTests(unittest.TestCase):
    def test_stop_sets_safe_floor_and_acceleration_before_zero_speed(self) -> None:
        runner = PowerStressTestRunner(FakeGlobalConfig(), FakeIRL())
        stepper = FakeStepper()

        runner._stopSteppers({"fake": stepper}, 12000)

        self.assertEqual(stepper.speed_limits[-1], (MIN_SPEED, 12000))
        self.assertEqual(stepper.accelerations[-1], SAFE_ACCELERATION)
        self.assertEqual(stepper.speeds[-1], 0)
        self.assertGreaterEqual(MIN_SPEED, SAFE_ACCELERATION / 1000)


if __name__ == "__main__":
    unittest.main()
