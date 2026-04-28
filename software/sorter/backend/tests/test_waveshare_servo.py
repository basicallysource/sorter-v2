import sys
import types
import unittest
from unittest.mock import patch

serial_stub = types.ModuleType("serial")
serial_stub.Serial = object
sys.modules.setdefault("serial", serial_stub)

from hardware.waveshare_servo import ScServoBus, WaveshareServoMotor, _checksum


class _FakeSerial:
    def __init__(self, reads: list[bytes]):
        self._buffer = b"".join(reads)

    def reset_input_buffer(self) -> None:
        pass

    def write(self, _data: bytes) -> None:
        pass

    def flush(self) -> None:
        pass

    def read(self, _size: int) -> bytes:
        if not self._buffer:
            return b""
        chunk = self._buffer[:_size]
        self._buffer = self._buffer[_size:]
        return chunk

    def close(self) -> None:
        pass


def _ping_packet(servo_id: int, *, error: int = 0) -> tuple[bytes, bytes]:
    header = bytes([0xFF, 0xFF, servo_id, 0x02, error])
    checksum = bytes([_checksum(header[2:])])
    return header, checksum


def _read_packet(servo_id: int, payload: bytes, *, error: int = 0) -> tuple[bytes, bytes]:
    header = bytes([0xFF, 0xFF, servo_id, len(payload) + 2, error])
    checksum = bytes([_checksum(header[2:] + payload)])
    return header, payload + checksum


class WaveshareServoBusTests(unittest.TestCase):
    def test_ping_accepts_response_without_echo(self) -> None:
        packet = bytes([0xFF, 0xFF, 7, 0x02, 0x00, _checksum(bytes([7, 0x02, 0x00]))])

        with patch("hardware.waveshare_servo.serial.Serial", return_value=_FakeSerial([packet])):
            bus = ScServoBus("/dev/null")
            self.assertTrue(bus.ping(7))

    def test_ping_accepts_matching_response_id(self) -> None:
        request_echo = bytes([0xFF, 0xFF, 7, 0x02, 0x01, _checksum(bytes([7, 0x02, 0x01]))])
        header, body = _ping_packet(7)

        with patch("hardware.waveshare_servo.serial.Serial", return_value=_FakeSerial([request_echo, header, body])):
            bus = ScServoBus("/dev/null")
            self.assertTrue(bus.ping(7))

    def test_ping_rejects_response_from_different_servo_id(self) -> None:
        request_echo = bytes([0xFF, 0xFF, 7, 0x02, 0x01, _checksum(bytes([7, 0x02, 0x01]))])
        header, body = _ping_packet(1)

        with patch("hardware.waveshare_servo.serial.Serial", return_value=_FakeSerial([request_echo, header, body])):
            bus = ScServoBus("/dev/null")
            self.assertFalse(bus.ping(7))

    def test_read_word_rejects_invalid_checksum(self) -> None:
        request = bytes([0xFF, 0xFF, 3, 0x04, 0x02, 56, 2, _checksum(bytes([3, 0x04, 0x02, 56, 2]))])
        header, body = _read_packet(3, bytes([0x12, 0x34]))
        invalid_body = body[:-1] + bytes([(body[-1] + 1) & 0xFF])

        with patch("hardware.waveshare_servo.serial.Serial", return_value=_FakeSerial([request, header, invalid_body])):
            bus = ScServoBus("/dev/null")
            self.assertIsNone(bus.read_word(3, 56))


class WaveshareServoMotorTests(unittest.TestCase):
    def test_recalibrate_returns_measured_limits_tuple(self) -> None:
        bus = types.SimpleNamespace(
            set_torque=lambda *_args, **_kwargs: None,
            read_position=lambda _servo_id: 512,
        )
        servo = WaveshareServoMotor(bus, servo_id=3)

        with patch("hardware.waveshare_servo.calibrate_servo", return_value=(123, 876)) as cal:
            result = servo.recalibrate()

        cal.assert_called_once_with(bus, 3)
        self.assertEqual(result, (123, 876))
        # And the endpoint-style unpack must succeed (this is what the router does).
        min_limit, max_limit = result
        self.assertEqual((min_limit, max_limit), (123, 876))
        self.assertEqual(servo._min_limit, 123)
        self.assertEqual(servo._max_limit, 876)


if __name__ == "__main__":
    unittest.main()
