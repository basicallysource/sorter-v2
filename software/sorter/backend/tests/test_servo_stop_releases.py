import unittest
from types import SimpleNamespace

from hardware.sorter_interface import InterfaceCommandCode, ServoMotor


class _Device:
    def __init__(self) -> None:
        self.sent: list[tuple[int, int, bytes]] = []

    def send_command(self, command: int, channel: int, payload: bytes):
        self.sent.append((command, channel, payload))
        return SimpleNamespace(payload=b"\x01")


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def debug(self, *args, **kwargs) -> None:
        pass


class ServoStopTests(unittest.TestCase):
    def test_stopping_an_uncalibrated_servo_releases_it_and_never_drives_it(self) -> None:
        device = _Device()
        servo = ServoMotor(device, 2, SimpleNamespace(logger=_Logger()))
        servo.stop()
        self.assertEqual([(InterfaceCommandCode.SERVO_SET_ENABLED, 2, b"\x00")], device.sent)
        self.assertFalse(servo.enabled)


if __name__ == "__main__":
    unittest.main()
