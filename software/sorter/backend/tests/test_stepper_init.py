"""Stepper init stops, with the reason, when a driver did not take its settings.

Driver writes are one-way: the control board acknowledges them without hearing
from the TMC2209. So init counts the writes it sends and compares the driver's
IFCNT (writes it accepted) before and after."""

import contextlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hardware.bus import MCUBusError
from hardware.fault import HardwareFault
from irl.config import IRLInterface, _TMC_REG_IFCNT, _bindHardware, _configureStepper
from machine_platform.control_board import BoardIdentity, DiscoveredStepper


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

    def set_hardware_name(self, name: str) -> None:
        self.hardware_name = name

    def set_name(self, name: str) -> None:
        self.name = name

    def set_direction_inverted(self, inverted: bool) -> None:
        self.direction_inverted = inverted


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


class _Board:
    """A basically V1-1 board: four driver sockets, each channel named by the firmware role."""

    servos = ()

    def __init__(self, role: str, channels: list[tuple[str, str, _Driver]]):
        self.identity = BoardIdentity("basically_rp2040", role, f"{role.upper()} MB", f"/dev/{role}", 0)
        self.interface = SimpleNamespace(name=role)
        self.board_key = role
        self._steppers = []
        for channel, (physical, canonical, driver) in enumerate(channels):
            driver.channel = channel
            driver.current_position_steps = 0
            self._steppers.append(DiscoveredStepper(canonical, physical, driver))

    @property
    def logical_stepper_names(self) -> tuple[str, ...]:
        return tuple(stepper.canonical_name for stepper in self._steppers)

    def iter_steppers(self) -> tuple[DiscoveredStepper, ...]:
        return tuple(self._steppers)


class _SteppersBound(Exception):
    pass


def _bindSteppers(boards: list[_Board]) -> IRLInterface:
    """Runs hardware init over the boards up to the end of stepper binding."""
    gc = SimpleNamespace(logger=_Logger(), no_power_development_mode=False)
    machine_config = SimpleNamespace(stepper_current_overrides={}, stepper_stallguard={})
    irl = IRLInterface()
    with (
        patch("irl.config.loadMachineSpecificParams", return_value={}),
        patch("irl.config.loadMachineConfig", return_value=machine_config),
        patch("irl.config.loadStepperBindingOverrides", return_value={}),
        patch("irl.config.loadStepperDirectionInverts", return_value={}),
        patch("irl.config.loadServoChannelConfig", return_value=None),
        patch("irl.config.MCUBus.enumerate_buses", return_value=[]),
        patch("irl.config.discover_control_boards", return_value=boards),
        patch("irl.config.discoverLedOutputs", return_value=[]),
        patch("irl.config.LedController"),
        patch("irl.config.get_led_state", return_value=None),
        patch("irl.config._apply_stepper_software_disable", side_effect=_SteppersBound),
        patch("irl.config.time.sleep"),
    ):
        with contextlib.suppress(_SteppersBound):
            _bindHardware(irl, SimpleNamespace(), gc)
    return irl


class SpareChannelTests(unittest.TestCase):
    def test_two_v1_1_boards_with_empty_aux_sockets_home(self) -> None:
        # A machine on two basically V1-1 boards: the distribution board drives
        # only the chute, and its three aux sockets hold no driver.
        chute = _Driver()
        empty = [_Driver(answers=False) for _ in range(3)]
        feeder = _Board(
            "feeder",
            [
                ("carousel", "carousel", _Driver()),
                ("third_c_channel_rotor", "c_channel_3_rotor", _Driver()),
                ("second_c_channel_rotor", "c_channel_2_rotor", _Driver()),
                ("first_c_channel_rotor", "c_channel_1_rotor", _Driver()),
            ],
        )
        distribution = _Board(
            "distribution",
            [("chute_stepper", "chute_stepper", chute)]
            + [(f"distribution_aux_{n}", f"distribution_aux_{n}", empty[n - 1]) for n in (1, 2, 3)],
        )

        irl = _bindSteppers([feeder, distribution])

        self.assertIs(chute, irl.chute_stepper)
        self.assertEqual(250 + 2, chute.ifcnt)  # GCONF and current, both taken
        for name in ("carousel", "c_channel_1_rotor", "c_channel_2_rotor", "c_channel_3_rotor"):
            self.assertTrue(hasattr(irl, f"{name}_stepper"), name)
        self.assertFalse(any(hasattr(driver, "name") for driver in empty))


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
