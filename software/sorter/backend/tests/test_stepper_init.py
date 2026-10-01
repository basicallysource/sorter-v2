"""Stepper init stops, with the reason, when a driver did not take its settings.

Driver writes are one-way: the control board acknowledges them without hearing
from the TMC2209. So init counts the writes it sends and compares the driver's
IFCNT (writes it accepted) before and after."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hardware.bus import MCUBusError
from hardware.fault import HardwareFault
from irl.config import IRLInterface, _TMC_REG_IFCNT, _configureStepper


class _Logger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    warning = info


class _Driver:
    """A stepper whose TMC2209 counts the register writes that reach it."""

    def __init__(self, *, drop_writes: int = 0, answers: bool = True, diag_pin: bool = True):
        self.ifcnt = 250  # near the wrap, which the check must survive
        self.drop_writes = drop_writes
        self.answers = answers
        self.diag_pin = diag_pin
        self.stallguard_sgthrs = None
        self.stallguard_tcoolthrs = 0xFFFFF
        self.stallguard_enabled = False
        self.detection_on = False

    def _write(self) -> None:
        if self.drop_writes > 0:
            self.drop_writes -= 1
            return
        self.ifcnt = (self.ifcnt + 1) % 256

    def read_driver_register(self, address: int) -> int:
        if not self.answers:
            raise MCUBusError("Error response received, command: 0x0e, payload: Failed to read register 2")
        assert address == _TMC_REG_IFCNT
        return self.ifcnt

    def write_driver_register(self, _address: int, _value: int) -> None:
        self._write()

    def set_microsteps(self, _microsteps: int) -> None:
        self._write()

    def set_current(self, _irun: int, _ihold: int, _ihold_delay: int) -> None:
        self._write()

    def set_speed_limits(self, _min: int, _max: int) -> None:
        pass

    def set_default_acceleration(self, _acceleration: int) -> None:
        pass

    def set_acceleration(self, _acceleration: int) -> None:
        pass

    def clear_stall(self) -> None:
        pass

    def enable_stall_detection(self, enable: bool) -> None:
        if not self.diag_pin:
            raise MCUBusError("Error response received, command: 0x1a, payload: No DIAG pin on channel 4")
        self.detection_on = enable


_STEPPER_CONFIG = SimpleNamespace(
    microsteps=8, default_steps_per_second=3000, acceleration_microsteps_per_second_sq=20000
)


def _configure(driver: _Driver, *, no_power: bool = False, stallguard: bool = True) -> None:
    gc = SimpleNamespace(logger=_Logger(), no_power_development_mode=no_power)
    machine_config = SimpleNamespace(
        stepper_current_overrides={},
        stepper_stallguard={"chute_stepper": (60, 0x3FF, True)} if stallguard else {},
    )
    with patch("irl.config.time.sleep"):
        _configureStepper(gc, driver, "chute_stepper", "chute", _STEPPER_CONFIG, machine_config)


class StepperInitTests(unittest.TestCase):
    def test_a_driver_that_takes_every_write_is_configured(self) -> None:
        driver = _Driver()
        _configure(driver)
        self.assertTrue(driver.detection_on)
        self.assertTrue(driver.stallguard_enabled)
        self.assertEqual((250 + 5) % 256, driver.ifcnt)

    def test_a_dropped_write_stops_init_naming_the_stepper(self) -> None:
        with self.assertRaises(HardwareFault) as caught:
            _configure(_Driver(drop_writes=1))
        self.assertEqual("Stepper settings not applied", caught.exception.title)
        self.assertIn("chute", caught.exception.message)
        self.assertIn("4 of the 5", caught.exception.message)

    def test_a_driver_that_does_not_answer_stops_init(self) -> None:
        with self.assertRaises(HardwareFault) as caught:
            _configure(_Driver(answers=False))
        self.assertEqual("Stepper setup failed", caught.exception.title)
        self.assertIn("motor power", caught.exception.message)

    def test_stall_detection_that_cannot_be_armed_stops_init(self) -> None:
        with self.assertRaises(HardwareFault) as caught:
            _configure(_Driver(diag_pin=False))
        self.assertIn("arm stall detection for the chute stepper", caught.exception.message)

    def test_without_stallguard_three_writes_are_expected(self) -> None:
        driver = _Driver()
        _configure(driver, stallguard=False)
        self.assertFalse(driver.detection_on)
        self.assertEqual((250 + 3) % 256, driver.ifcnt)

    def test_no_power_mode_sends_the_settings_unchecked(self) -> None:
        driver = _Driver(answers=False)  # unpowered drivers cannot answer reads
        _configure(driver, no_power=True)
        self.assertTrue(driver.detection_on)


class _Bus:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class IRLShutdownTests(unittest.TestCase):
    def test_buses_close_even_when_a_board_no_longer_answers(self) -> None:
        bus = _Bus()

        def unanswered() -> None:
            raise MCUBusError("Response timeout")

        irl = IRLInterface()
        irl.interfaces = {"board": SimpleNamespace(_bus=bus, shutdown=unanswered)}
        with self.assertRaises(MCUBusError):
            irl.shutdown()
        self.assertTrue(bus.closed)


if __name__ == "__main__":
    unittest.main()
