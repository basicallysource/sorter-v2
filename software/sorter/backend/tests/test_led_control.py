import importlib
import os
import tempfile
import unittest
from collections.abc import Sequence
from typing import Any

from hardware.bus import MCUBusError
from hardware.sorter_interface import DIGITAL_OUTPUT_DUTY_MAX, DigitalOutputPin
from irl.leds import BoundLed, LedController, bindGpioLeds, brightnessPercentToDuty
from irl.parse_user_toml import GpioLedConfig
from machine_platform.control_board import BoardIdentity


class FakeDevice:
    # Structurally a sorter_interface.DigitalOutputDevice.
    def __init__(self, pwm_supported: bool = True, reject_pwm: bool = False) -> None:
        self._pwm_supported = pwm_supported
        self.reject_pwm = reject_pwm
        self.commands: list[tuple[int, int, bytes]] = []

    @property
    def supports_digital_output_pwm(self) -> bool:
        return self._pwm_supported

    def send_command(self, command: int, channel: int, payload: bytes) -> object:
        if int(command) == 0x32 and self.reject_pwm:
            raise MCUBusError("Unknown command")
        self.commands.append((int(command), channel, payload))
        return None


class FakeBoardInterface:
    def __init__(self, digital_outputs: Sequence[DigitalOutputPin]) -> None:
        self.digital_outputs = digital_outputs


class FakeBoard:
    # Structurally a leds.LedCapableBoard — the real ControlBoard ABC demands a
    # whole SorterInterface, which these tests have no use for.
    def __init__(
        self, role: str, device_name: str, digital_outputs: Sequence[DigitalOutputPin]
    ) -> None:
        self.identity = BoardIdentity(
            family="basically",
            role=role,
            device_name=device_name,
            port="/dev/null",
            address=0,
        )
        self.interface = FakeBoardInterface(digital_outputs)


class FakeLogger:
    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass


class FakeGlobalConfig:
    def __init__(self) -> None:
        self.logger = FakeLogger()


def mkGc() -> Any:
    return FakeGlobalConfig()


class BrightnessMappingTests(unittest.TestCase):
    def test_percent_maps_to_full_duty_range(self) -> None:
        self.assertEqual(brightnessPercentToDuty(0), 0)
        self.assertEqual(brightnessPercentToDuty(100), DIGITAL_OUTPUT_DUTY_MAX)
        self.assertEqual(brightnessPercentToDuty(50), round(DIGITAL_OUTPUT_DUTY_MAX / 2))

    def test_percent_is_clamped(self) -> None:
        self.assertEqual(brightnessPercentToDuty(-20), 0)
        self.assertEqual(brightnessPercentToDuty(500), DIGITAL_OUTPUT_DUTY_MAX)


class DigitalOutputPwmTests(unittest.TestCase):
    def test_set_duty_sends_pwm_command(self) -> None:
        gc = mkGc()
        device = FakeDevice(pwm_supported=True)
        pin = DigitalOutputPin(device, 0, gc)

        pin.setDuty(30000)

        self.assertEqual(len(device.commands), 1)
        command, channel, payload = device.commands[0]
        self.assertEqual(command, 0x32)
        self.assertEqual(channel, 0)
        self.assertEqual(payload, (30000).to_bytes(2, "little"))
        self.assertEqual(pin.duty, 30000)
        self.assertTrue(pin.value)

    def test_set_duty_zero_reports_off(self) -> None:
        gc = mkGc()
        pin = DigitalOutputPin(FakeDevice(pwm_supported=True), 1, gc)

        pin.setDuty(0)

        self.assertEqual(pin.duty, 0)
        self.assertFalse(pin.value)

    def test_boolean_write_still_tracks_duty(self) -> None:
        gc = mkGc()
        device = FakeDevice(pwm_supported=True)
        pin = DigitalOutputPin(device, 0, gc)

        pin.value = True

        self.assertEqual(device.commands[0][0], 0x31)
        self.assertEqual(pin.duty, DIGITAL_OUTPUT_DUTY_MAX)

    def test_old_firmware_degrades_to_on_off(self) -> None:
        gc = mkGc()
        # Board claims support via observability but rejects the opcode — what a
        # board flashed with firmware predating WRITE_PWM would actually do if
        # the capability flag were ever wrong.
        device = FakeDevice(pwm_supported=True, reject_pwm=True)
        pin = DigitalOutputPin(device, 0, gc)

        pin.setDuty(20000)

        self.assertFalse(pin.pwm_supported)
        self.assertEqual([c[0] for c in device.commands], [0x31])
        self.assertTrue(pin.value)

        pin.setDuty(0)
        self.assertEqual([c[0] for c in device.commands], [0x31, 0x31])
        self.assertFalse(pin.value)

    def test_board_without_pwm_never_sends_pwm_command(self) -> None:
        gc = mkGc()
        device = FakeDevice(pwm_supported=False)
        pin = DigitalOutputPin(device, 0, gc)

        pin.setDuty(40000)

        self.assertEqual([c[0] for c in device.commands], [0x31])


class BindGpioLedsTests(unittest.TestCase):
    def test_binds_matching_boards_and_skips_missing_channels(self) -> None:
        gc = mkGc()
        outputs = (
            DigitalOutputPin(FakeDevice(), 0, gc),
            DigitalOutputPin(FakeDevice(), 1, gc),
        )
        boards = [
            FakeBoard("feeder", "feeder-board", outputs),
            FakeBoard("distribution", "dist-board", outputs),
        ]

        bound = bindGpioLeds(
            gc,
            boards,
            [
                GpioLedConfig(board="any", pin=0),
                GpioLedConfig(board="feeder", pin=1),
                GpioLedConfig(board="feeder", pin=9),
            ],
        )

        self.assertEqual(
            [(b.board_role, b.channel) for b in bound],
            [("feeder", 0), ("distribution", 0), ("feeder", 1)],
        )


class LedControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_db = os.environ.get("LOCAL_STATE_DB_PATH")
        os.environ["LOCAL_STATE_DB_PATH"] = os.path.join(self._tmp.name, "state.sqlite")
        import local_state

        importlib.reload(local_state)
        self.local_state = local_state
        importlib.reload(importlib.import_module("irl.leds"))

        self.gc = mkGc()
        self.device = FakeDevice(pwm_supported=True)
        self.pin = DigitalOutputPin(self.device, 0, self.gc)
        self.leds = [
            BoundLed(board_role="feeder", board_name="feeder-board", channel=0, pin=self.pin)
        ]

    def tearDown(self) -> None:
        if self._old_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_db
        self._tmp.cleanup()
        import local_state

        importlib.reload(local_state)
        importlib.reload(importlib.import_module("irl.leds"))

    def test_boot_turns_leds_on_by_default(self) -> None:
        controller = LedController(self.gc, self.leds)

        state = controller.applyBootState()

        self.assertTrue(state["enabled"])
        self.assertEqual(self.pin.duty, DIGITAL_OUTPUT_DUTY_MAX)

    def test_boot_leaves_leds_dark_when_on_at_boot_is_off(self) -> None:
        LedController(self.gc, self.leds).update({"on_at_boot": False})

        state = LedController(self.gc, self.leds).applyBootState()

        self.assertFalse(state["enabled"])
        self.assertEqual(self.pin.duty, 0)

    def test_brightness_persists_across_controllers(self) -> None:
        LedController(self.gc, self.leds).update({"brightness_percent": 40})

        state = LedController(self.gc, self.leds).state

        self.assertEqual(state["brightness_percent"], 40)

    def test_enabling_drives_configured_brightness(self) -> None:
        controller = LedController(self.gc, self.leds)

        controller.update({"brightness_percent": 25, "enabled": True})

        self.assertEqual(self.pin.duty, brightnessPercentToDuty(25))

    def test_disabling_drives_zero_without_losing_brightness(self) -> None:
        controller = LedController(self.gc, self.leds)
        controller.update({"brightness_percent": 25})

        controller.update({"enabled": False})

        self.assertEqual(self.pin.duty, 0)
        self.assertEqual(controller.state["brightness_percent"], 25)

    def test_status_reports_wiring_and_capability(self) -> None:
        controller = LedController(self.gc, self.leds)

        status = controller.status()

        self.assertTrue(status["configured"])
        self.assertTrue(status["pwm_supported"])
        self.assertEqual(status["leds"][0]["board_role"], "feeder")
        self.assertEqual(status["defaults"], dict(self.local_state.LED_CONTROL_DEFAULTS))

    def test_status_without_wiring_is_not_configured(self) -> None:
        status = LedController(self.gc, []).status()

        self.assertFalse(status["configured"])
        self.assertFalse(status["pwm_supported"])
        self.assertEqual(status["leds"], [])

    def test_brightness_is_clamped_on_write(self) -> None:
        controller = LedController(self.gc, self.leds)

        controller.update({"brightness_percent": 480})

        self.assertEqual(controller.state["brightness_percent"], 100)


if __name__ == "__main__":
    unittest.main()
