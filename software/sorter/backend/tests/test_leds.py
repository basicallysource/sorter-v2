import unittest
from collections.abc import Sequence
from typing import Any

from hardware.sorter_interface import (
    DIGITAL_OUTPUT_DUTY_MAX,
    DigitalOutputPin,
    InterfaceCommandCode,
)
from irl.leds import LedController, brightnessPercentToDuty, discoverLedOutputs
from machine_platform.control_board import BoardIdentity


class FakeDevice:
    def send_command(self, command: int, channel: int, payload: bytes) -> object:
        return None


class FakeInterface:
    def __init__(self, gc: Any, led_gpios: Sequence[int], output_count: int) -> None:
        self.digital_outputs = tuple(
            DigitalOutputPin(FakeDevice(), ch, gc) for ch in range(output_count)
        )
        self._led_gpios = list(led_gpios)

    def get_observability_info(self, *, force_refresh: bool = False) -> dict:
        return {"led_gpios": list(self._led_gpios)}


class FakeBoard:
    def __init__(self, gc: Any, role: str, led_gpios: Sequence[int], output_count: int) -> None:
        self.identity = BoardIdentity(
            family="basically", role=role, device_name=f"{role}-board", port="/dev/null", address=0
        )
        self.interface = FakeInterface(gc, led_gpios, output_count)


class FakeLogger:
    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass


class FakeGlobalConfig:
    def __init__(self) -> None:
        self.logger = FakeLogger()


class BrightnessMappingTests(unittest.TestCase):
    def test_percent_maps_to_full_duty_range(self) -> None:
        self.assertEqual(brightnessPercentToDuty(0), 0)
        self.assertEqual(brightnessPercentToDuty(100), DIGITAL_OUTPUT_DUTY_MAX)
        self.assertEqual(brightnessPercentToDuty(50), round(DIGITAL_OUTPUT_DUTY_MAX / 2))

    def test_percent_is_clamped(self) -> None:
        self.assertEqual(brightnessPercentToDuty(-20), 0)
        self.assertEqual(brightnessPercentToDuty(500), DIGITAL_OUTPUT_DUTY_MAX)


class LedOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gc: Any = FakeGlobalConfig()
        self.boards = [
            FakeBoard(self.gc, "feeder", [1, 6], output_count=2),
            FakeBoard(self.gc, "distribution", [], output_count=2),
        ]
        self.outputs = discoverLedOutputs(self.gc, self.boards)

    def test_only_firmware_declared_gpios_become_outputs(self) -> None:
        self.assertEqual(
            [(o.output_id, o.gpio) for o in self.outputs], [("feeder:1", 1), ("feeder:6", 6)]
        )

    def test_shared_gpio_gets_one_duty_and_unclaimed_outputs_go_dark(self) -> None:
        LedController(self.gc, self.outputs).apply(
            {
                "assignments": {
                    "c_channel_2": "feeder:1",
                    "c_channel_3": "feeder:1",
                    "classification_channel": None,
                },
                "brightness": {"feeder:1": 40, "feeder:6": 100},
            }
        )

        self.assertEqual(self.outputs[0].pin.duty, brightnessPercentToDuty(40))
        self.assertEqual(self.outputs[1].pin.duty, 0)

    def test_claimed_output_without_a_stored_brightness_comes_up_lit(self) -> None:
        LedController(self.gc, self.outputs).apply(
            {"assignments": {"c_channel_2": "feeder:6"}, "brightness": {}}
        )

        self.assertEqual(self.outputs[1].pin.duty, DIGITAL_OUTPUT_DUTY_MAX)

    def test_all_off_zeroes_every_output(self) -> None:
        controller = LedController(self.gc, self.outputs)
        controller.apply({"assignments": {"c_channel_2": "feeder:1"}, "brightness": {}})

        controller.allOff()

        self.assertEqual([o.pin.duty for o in self.outputs], [0, 0])

    def test_all_on_drives_every_output_at_full_duty(self) -> None:
        controller = LedController(self.gc, self.outputs)

        controller.allOn()

        self.assertEqual(
            [o.pin.duty for o in self.outputs],
            [DIGITAL_OUTPUT_DUTY_MAX, DIGITAL_OUTPUT_DUTY_MAX],
        )


class RecordingDevice:
    def __init__(self) -> None:
        self.commands: list[tuple[int, int, bytes]] = []

    def send_command(self, command: int, channel: int, payload: bytes) -> object:
        self.commands.append((command, channel, payload))
        return None


class PwmArmingTests(unittest.TestCase):
    # The board only routes a pad to its PWM block on the first duty write after
    # a plain one, and its INIT (sent on every host start) drives the pad low
    # without clearing that flag. So a host process has to assume the board may
    # still think it is in PWM mode and open with a plain write.
    def setUp(self) -> None:
        self.gc: Any = FakeGlobalConfig()
        self.device = RecordingDevice()
        self.pin = DigitalOutputPin(self.device, 0, self.gc)

    def test_first_duty_write_is_preceded_by_a_plain_write(self) -> None:
        self.pin.setDuty(DIGITAL_OUTPUT_DUTY_MAX)

        self.assertEqual(
            [command for command, _, _ in self.device.commands],
            [InterfaceCommandCode.DIGITAL_WRITE, InterfaceCommandCode.DIGITAL_WRITE_PWM],
        )

    def test_later_duty_writes_do_not_repeat_it(self) -> None:
        self.pin.setDuty(DIGITAL_OUTPUT_DUTY_MAX)
        self.device.commands.clear()

        self.pin.setDuty(0)

        self.assertEqual(
            [command for command, _, _ in self.device.commands],
            [InterfaceCommandCode.DIGITAL_WRITE_PWM],
        )

    def test_a_plain_write_re_arms_the_next_duty_write(self) -> None:
        self.pin.setDuty(DIGITAL_OUTPUT_DUTY_MAX)
        self.pin.value = True
        self.device.commands.clear()

        self.pin.setDuty(DIGITAL_OUTPUT_DUTY_MAX)

        self.assertEqual(
            [command for command, _, _ in self.device.commands],
            [InterfaceCommandCode.DIGITAL_WRITE, InterfaceCommandCode.DIGITAL_WRITE_PWM],
        )


if __name__ == "__main__":
    unittest.main()
