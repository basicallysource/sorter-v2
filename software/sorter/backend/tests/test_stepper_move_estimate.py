"""The move-time estimate must cover the firmware's acceleration ramps: the
firmware rejects a new move until the previous one has fully stopped, so a
caller that waits only steps/speed re-issues too early and loses the move."""

import unittest
from types import SimpleNamespace

from hardware.sorter_interface import StepperMotor


class _Device:
    def send_command(self, command, channel, payload=b""):
        return SimpleNamespace(payload=b"\x01")


def _stepper() -> StepperMotor:
    gc = SimpleNamespace(logger=SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None))
    return StepperMotor(_Device(), 2, gc)


class MoveEstimateTests(unittest.TestCase):
    def test_short_pulse_is_a_ramp_triangle_not_steps_over_speed(self) -> None:
        stepper = _stepper()
        stepper.set_speed_limits(16, 2000)
        # Measured on the B1 machine: a 30° (133-step) C3 move is rejected at
        # +150 ms and accepted at +350 ms; the model says ~230 ms + margin.
        ms = stepper.estimateMoveStepsMs(133, max_speed=2000)
        self.assertGreater(ms, 200)
        self.assertLess(ms, 350)
        self.assertGreater(stepper.estimateMoveStepsMs(96, max_speed=2000), 150)

    def test_long_move_is_a_trapezoid(self) -> None:
        stepper = _stepper()
        stepper.set_speed_limits(16, 2000)
        # 325° (1444 steps): rejected at +800 ms, accepted at +1100 ms.
        ms = stepper.estimateMoveStepsMs(1444, max_speed=2000)
        self.assertGreater(ms, 950)
        self.assertLess(ms, 1150)

    def test_applied_acceleration_and_ceiling_are_honoured(self) -> None:
        stepper = _stepper()
        stepper.set_speed_limits(16, 4000)
        fast = stepper.estimateMoveStepsMs(1444, max_speed=2000)
        stepper.set_acceleration(2500)
        slow = stepper.estimateMoveStepsMs(1444, max_speed=2000)
        self.assertGreater(slow, fast)
        # The ceiling is the lower of the caller's speed and the applied limit.
        stepper.set_speed_limits(16, 1000)
        self.assertGreater(stepper.estimateMoveStepsMs(1444, max_speed=2000), slow)

    def test_zero_steps_is_free(self) -> None:
        self.assertEqual(_stepper().estimateMoveStepsMs(0), 0)


if __name__ == "__main__":
    unittest.main()
