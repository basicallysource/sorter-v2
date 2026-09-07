import logging
from types import SimpleNamespace

import irl  # noqa: F401  (breaks the irl <-> machine_platform import cycle)

from machine_platform.stepper_safety import stopAllSteppers, stopStepper


class _Stepper:
    def __init__(self, fail: bool = False, ack: bool = True) -> None:
        self.calls: list = []
        self.fail = fail
        self.ack = ack

    def move_at_speed(self, speed: int, force: bool = False) -> bool:
        if self.fail:
            raise RuntimeError("bus down")
        self.calls.append(("speed", speed, force))
        return self.ack

    def enable_force(self, value: bool) -> None:
        self.calls.append(("enable_force", value))


def test_stop_zeroes_speed_forced_past_a_software_disable() -> None:
    s = _Stepper()
    assert stopStepper(s)
    assert s.calls == [("speed", 0, True)]


def test_unacknowledged_stop_cuts_the_driver() -> None:
    s = _Stepper(ack=False)
    assert stopStepper(s)
    assert s.calls == [("speed", 0, True), ("enable_force", False)]


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
    assert belt.calls[0] == ("speed", 0, True) and chute.calls[0] == ("speed", 0, True)
