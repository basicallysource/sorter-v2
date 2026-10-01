"""The move-time estimate follows the firmware's ramp, so a pause starts when the move ends."""

from hardware.sorter_interface import StepperMotor


def _stepper(accel: int = 10000, min_speed: int = 16) -> StepperMotor:
    stepper = StepperMotor.__new__(StepperMotor)
    stepper._applied_acceleration = accel
    stepper._default_acceleration = None
    stepper._applied_speed_limits = (min_speed, 2000)
    return stepper


def test_a_short_pulse_never_reaches_top_speed() -> None:
    # A 2 degree exit pulse on a feeder channel: the firmware's own trapezoid
    # (replayed tick by tick against the control log) takes 181 ms; distance
    # over top speed said 48 ms.
    assert abs(_stepper().estimateMoveStepsMs(96, max_speed=2000) - 181) <= 15


def test_a_long_pulse_ramps_cruises_and_brakes() -> None:
    # A 30 degree drop pulse: 906 ms in the firmware replay, 722 ms by distance alone.
    assert abs(_stepper().estimateMoveStepsMs(1444, max_speed=2000) - 906) <= 20


def test_direction_does_not_matter_and_zero_is_zero() -> None:
    stepper = _stepper()
    assert stepper.estimateMoveStepsMs(-96, max_speed=2000) == stepper.estimateMoveStepsMs(96, max_speed=2000)
    assert stepper.estimateMoveStepsMs(0, max_speed=2000) == 0
