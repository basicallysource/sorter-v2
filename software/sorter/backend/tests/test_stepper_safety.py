import logging
from types import SimpleNamespace

from machine_platform.stepper_safety import stopAllSteppers, stopStepper


class _Stepper:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list = []
        self.fail = fail

    def move_at_speed(self, speed: int) -> None:
        if self.fail:
            raise RuntimeError("bus down")
        self.calls.append(("speed", speed))

    def halt(self, *, disable_driver: bool) -> bool:
        self.calls.append(("halt", disable_driver))
        return True


def test_stop_zeroes_speed_then_halts_without_disabling() -> None:
    s = _Stepper()
    stopStepper(s)
    assert s.calls == [("speed", 0), ("halt", False)]


def test_stop_all_covers_every_stepper_once_and_survives_a_failure() -> None:
    belt, chute, broken = _Stepper(), _Stepper(), _Stepper(fail=True)
    irl = SimpleNamespace(
        c_channel_1_rotor_stepper=belt,
        chute_stepper=chute,
        carousel_stepper=broken,
        c_channel_4_rotor_stepper=broken,  # same object under two names
    )
    stopped = stopAllSteppers(irl, logging.getLogger("t"), reason="test")
    assert stopped == ["c_channel_1_rotor_stepper", "chute_stepper"]
    assert belt.calls[0] == ("speed", 0) and chute.calls[0] == ("speed", 0)
