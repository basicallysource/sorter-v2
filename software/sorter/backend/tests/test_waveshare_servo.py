import time
import os
import tempfile
import unittest
from unittest import mock
from unittest.mock import patch

from hardware.waveshare_bus_service import WaveshareBusRegistry, WaveshareBusService
from hardware import waveshare_servo
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

    def test_send_retries_after_comm_failure(self) -> None:
        wrong_header, wrong_body = _ping_packet(1)
        good_header, good_body = _ping_packet(7)
        reads = [wrong_header, wrong_body, good_header, good_body]

        with patch("hardware.waveshare_servo.serial.Serial", return_value=_FakeSerial(reads)):
            bus = ScServoBus("/dev/null")
            self.assertTrue(bus.ping(7))

    def test_nonzero_status_byte_is_success_and_recorded(self) -> None:
        header, body = _ping_packet(7, error=0x20)

        with patch("hardware.waveshare_servo.serial.Serial", return_value=_FakeSerial([header, body])):
            bus = ScServoBus("/dev/null")
            with self.assertLogs("hardware.waveshare_servo", level="WARNING"):
                self.assertTrue(bus.ping(7))
            self.assertEqual(bus.last_status_flags(7), 0x20)

    def test_read_succeeds_despite_status_flags(self) -> None:
        header, body = _read_packet(3, bytes([0x01, 0x02]), error=0x04)

        with patch("hardware.waveshare_servo.serial.Serial", return_value=_FakeSerial([header, body])):
            bus = ScServoBus("/dev/null")
            with self.assertLogs("hardware.waveshare_servo", level="WARNING"):
                self.assertEqual(bus.read_word(3, 56), 0x0102)
            self.assertEqual(bus.last_status_flags(3), 0x04)

    def test_unchanged_status_flags_logged_only_once(self) -> None:
        first = _ping_packet(7, error=0x20)
        second = _ping_packet(7, error=0x20)

        with patch("hardware.waveshare_servo.serial.Serial", return_value=_FakeSerial([*first, *second])):
            bus = ScServoBus("/dev/null")
            with self.assertLogs("hardware.waveshare_servo", level="WARNING") as captured:
                self.assertTrue(bus.ping(7))
                self.assertTrue(bus.ping(7))
            self.assertEqual(len(captured.records), 1)


class _FakeBus:
    """ServoBus stand-in for WaveshareServoMotor tests."""

    def __init__(self):
        self.move_results: list[bool] = []
        self.moves: list[int] = []
        self.torque_calls: list[tuple[int, bool]] = []

    def set_torque(self, servo_id: int, enable: bool) -> bool:
        self.torque_calls.append((servo_id, enable))
        return True

    def move_to(self, servo_id: int, position: int, time_ms: int = 500) -> bool:
        self.moves.append(position)
        return self.move_results.pop(0) if self.move_results else True

    def read_position(self, servo_id: int) -> int | None:
        return None

    def read_load(self, servo_id: int) -> int | None:
        return None

    def read_angle_limits(self, servo_id: int) -> tuple[int, int] | None:
        return (100, 900)

    def set_angle_limits(self, servo_id: int, min_val: int, max_val: int) -> bool:
        return True

    def set_pid(self, servo_id: int, p: int, d: int, i: int) -> bool:
        return True


class WaveshareServoMotorTests(unittest.TestCase):
    def test_open_releases_torque_after_the_move_without_a_stopped_poll(self) -> None:
        bus = _FakeBus()
        motor = WaveshareServoMotor(bus, 1)
        motor.initialize()
        motor.open()
        self.assertEqual(bus.torque_calls[-1], (1, True))
        time.sleep(0.8)
        self.assertEqual(bus.torque_calls[-1], (1, False))
        self.assertTrue(motor.stopped)
        # The poll after the timer must not release a second time.
        self.assertEqual(bus.torque_calls.count((1, False)), 1)

    def test_back_to_back_moves_release_once_after_the_last_one(self) -> None:
        bus = _FakeBus()
        motor = WaveshareServoMotor(bus, 1)
        motor.initialize()
        motor.open()
        motor.close()
        time.sleep(0.8)
        self.assertEqual(bus.moves, [100, 900])
        self.assertEqual(bus.torque_calls.count((1, False)), 1)
        self.assertEqual(bus.torque_calls[-1], (1, False))

    def test_explicit_hold_cancels_the_pending_release(self) -> None:
        bus = _FakeBus()
        motor = WaveshareServoMotor(bus, 1)
        motor.initialize()
        motor.open()
        motor.enabled = True
        time.sleep(0.8)
        self.assertNotIn((1, False), bus.torque_calls)

    def test_available_flips_after_consecutive_failures_and_recovers(self) -> None:
        bus = _FakeBus()
        motor = WaveshareServoMotor(bus, 1)

        bus.move_results = [False, False]
        with self.assertLogs("hardware.waveshare_servo", level="WARNING"):
            motor.move_to(90)
            motor.move_to(90)
        self.assertTrue(motor.available)

        bus.move_results = [False]
        with self.assertLogs("hardware.waveshare_servo", level="WARNING"):
            motor.move_to(90)
        self.assertFalse(motor.available)

        bus.move_results = [True]
        self.assertTrue(motor.move_to(90))
        self.assertTrue(motor.available)

    def test_failed_open_keeps_last_known_position(self) -> None:
        bus = _FakeBus()
        motor = WaveshareServoMotor(bus, 1)

        bus.move_results = [True]
        motor.close()
        self.assertTrue(motor.isClosed())

        bus.move_results = [False]
        with self.assertLogs("hardware.waveshare_servo", level="WARNING"):
            motor.open()
        self.assertTrue(motor.isClosed())

        bus.move_results = [True]
        motor.open()
        self.assertTrue(motor.isOpen())


class _FakeServiceBus:
    """ScServoBus stand-in for WaveshareBusService tests."""

    def __init__(self):
        self.position_results: list[int | None] = []
        self.move_results: list[bool] = []

    def close(self) -> None:
        pass

    def ping(self, servo_id: int) -> bool:
        return False

    def read_position(self, servo_id: int) -> int | None:
        return self.position_results.pop(0) if self.position_results else None

    def move_to(self, servo_id: int, position: int, time_ms: int = 500) -> bool:
        return self.move_results.pop(0) if self.move_results else False


class WaveshareBusServiceTests(unittest.TestCase):
    @staticmethod
    def _service() -> WaveshareBusService:
        service = WaveshareBusService("/dev/null")
        service.attach_persistent()
        return service

    def test_failed_moves_count_toward_soft_recovery(self) -> None:
        fake = _FakeServiceBus()
        with patch("hardware.waveshare_bus_service.ScServoBus", return_value=fake), \
                patch("hardware.waveshare_bus_service.time.sleep"), \
                self.assertLogs("waveshare_bus", level="WARNING"):
            service = self._service()
            self.assertFalse(service.move_to(1, 100))
            self.assertFalse(service.move_to(1, 100))
            self.assertEqual(service.consecutive_failures, 2)
            self.assertEqual(service.recovery_attempts, 0)
            self.assertFalse(service.move_to(1, 100))
            self.assertEqual(service.recovery_attempts, 1)
            # The attempt resets the counter so the cooldown gates re-fires.
            self.assertEqual(service.consecutive_failures, 0)

    def test_truthy_result_resets_failure_counter(self) -> None:
        fake = _FakeServiceBus()
        fake.move_results = [False, True]
        with patch("hardware.waveshare_bus_service.ScServoBus", return_value=fake), \
                self.assertLogs("waveshare_bus", level="WARNING"):
            service = self._service()
            self.assertFalse(service.move_to(1, 100))
            self.assertEqual(service.consecutive_failures, 1)
            self.assertTrue(service.move_to(1, 100))
            self.assertEqual(service.consecutive_failures, 0)

    def test_read_polls_do_not_trigger_recovery(self) -> None:
        # Feedback polling hits offline servos routinely; a single dead servo
        # must not drive the whole port into soft recovery.
        fake = _FakeServiceBus()
        with patch("hardware.waveshare_bus_service.ScServoBus", return_value=fake):
            service = self._service()
            for _ in range(5):
                self.assertIsNone(service.read_position(1))
            self.assertEqual(service.consecutive_failures, 0)
            self.assertEqual(service.recovery_attempts, 0)

    def test_recovery_cooldown_gates_repeated_attempts(self) -> None:
        fake = _FakeServiceBus()
        with patch("hardware.waveshare_bus_service.ScServoBus", return_value=fake), \
                patch("hardware.waveshare_bus_service.time.sleep"), \
                self.assertLogs("waveshare_bus", level="WARNING"):
            service = self._service()
            for _ in range(3):
                service.move_to(1, 100)
            self.assertEqual(service.recovery_attempts, 1)
            # Within the cooldown window further failures must not stall the
            # bus with another close/reopen cycle.
            for _ in range(3):
                service.move_to(1, 100)
            self.assertEqual(service.recovery_attempts, 1)

    def test_registry_resolves_symlink_and_target_to_one_service(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "ttyACM0")
            open(target, "w").close()
            link = os.path.join(tmp, "usb-waveshare-bus")
            os.symlink(target, link)

            registry = WaveshareBusRegistry()
            via_link = registry.get_service(link)
            via_target = registry.get_service(target)
            self.assertIs(via_link, via_target)
            # The service opens the path it was given first.
            self.assertEqual(via_link.port, link)


if __name__ == "__main__":
    unittest.main()


class _SimServo:
    """Hard-stop door model for calibration tests.

    Free travel between ``stop_min`` and ``stop_max``. A command beyond a stop
    parks the horn a few counts past the free position (compression, as the
    real doors read 64 with a 69 limit) at high duty; inside the range the duty
    is ~0. Angle limits clamp every goal like the real EEPROM limits do.
    """

    def __init__(self, stop_min=64, stop_max=321, compression=4, start=200, limits=(0, 1023)):
        self.stop_min, self.stop_max, self.compression = stop_min, stop_max, compression
        self.limits = tuple(limits)
        self.pos = start
        self.duty = 0
        self.torque_calls: list[bool] = []
        self.limit_writes: list[tuple[int, int]] = []
        self.moves: list[int] = []
        self.fail_reads_after: int | None = None
        self.reads = 0

    def set_torque(self, servo_id, enable):
        self.torque_calls.append(bool(enable))
        return True

    def move_to(self, servo_id, position, time_ms=500):
        target = max(self.limits[0], min(self.limits[1], int(position)))
        self.moves.append(target)
        if target < self.stop_min:
            self.pos, self.duty = self.stop_min - self.compression, -300
        elif target > self.stop_max:
            self.pos, self.duty = self.stop_max + self.compression, 300
        else:
            self.pos, self.duty = target, 0
        return True

    def _read_ok(self):
        self.reads += 1
        return self.fail_reads_after is None or self.reads <= self.fail_reads_after

    def read_position(self, servo_id):
        return self.pos if self._read_ok() else None

    def read_load(self, servo_id):
        return self.duty if self._read_ok() else None

    def read_angle_limits(self, servo_id):
        return self.limits

    def set_angle_limits(self, servo_id, min_val, max_val):
        self.limits = (int(min_val), int(max_val))
        self.limit_writes.append(self.limits)
        return True

    def set_pid(self, servo_id, p, d, i):
        return True


class CalibrationTests(unittest.TestCase):
    def setUp(self) -> None:
        p = mock.patch.object(waveshare_servo, "_sleep", lambda s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_limits_sit_inside_the_free_travel_with_margin(self) -> None:
        sim = _SimServo(stop_min=64, stop_max=321)
        safe_min, safe_max = waveshare_servo.calibrate_servo(sim, 2)
        # margin counts from the pressed position (stop ∓ compression)
        self.assertGreaterEqual(safe_min, sim.stop_min - sim.compression + waveshare_servo._CAL_MARGIN_MIN)
        self.assertLessEqual(safe_max, sim.stop_max + sim.compression - waveshare_servo._CAL_MARGIN_MIN)
        self.assertGreater(safe_min, sim.stop_min)
        self.assertLess(safe_max, sim.stop_max)
        self.assertEqual(sim.limits, (safe_min, safe_max))
        self.assertFalse(sim.torque_calls[-1])
        # Parked at the calibrated ends the door is unloaded.
        sim.move_to(2, safe_min)
        self.assertEqual(sim.duty, 0)
        sim.move_to(2, safe_max)
        self.assertEqual(sim.duty, 0)

    def test_telemetry_loss_restores_the_previous_limits_and_releases(self) -> None:
        sim = _SimServo(limits=(100, 900))
        sim.fail_reads_after = 12
        with self.assertRaises(waveshare_servo.CalibrationError):
            waveshare_servo.calibrate_servo(sim, 2)
        self.assertEqual(sim.limits, (100, 900))
        self.assertFalse(sim.torque_calls[-1])

    def test_free_spinning_horn_is_rejected(self) -> None:
        sim = _SimServo(stop_min=-5000, stop_max=5000, limits=(100, 900))
        with self.assertRaises(waveshare_servo.CalibrationError) as ctx:
            waveshare_servo.calibrate_servo(sim, 2)
        self.assertIn("boundary", str(ctx.exception))
        self.assertEqual(sim.limits, (100, 900))

    def test_travel_too_small_is_rejected(self) -> None:
        sim = _SimServo(stop_min=200, stop_max=225, start=210, limits=(100, 900))
        with self.assertRaises(waveshare_servo.CalibrationError):
            waveshare_servo.calibrate_servo(sim, 2)
        self.assertEqual(sim.limits, (100, 900))

    def test_initialize_refuses_an_uncalibrated_servo_without_moving(self) -> None:
        sim = _SimServo()
        motor = WaveshareServoMotor(sim, 2)
        with self.assertRaises(RuntimeError) as ctx:
            motor.initialize()
        self.assertIn("not calibrated", str(ctx.exception))
        self.assertEqual(sim.moves, [])

    def test_initialize_accepts_calibrated_limits(self) -> None:
        sim = _SimServo(limits=(76, 309))
        motor = WaveshareServoMotor(sim, 2)
        motor.initialize()
        self.assertEqual((motor._open_position, motor._closed_position), (76, 309))

    def test_recalibrate_returns_the_new_limits(self) -> None:
        sim = _SimServo(limits=(76, 309))
        motor = WaveshareServoMotor(sim, 2)
        motor.initialize()
        self.assertEqual(motor.recalibrate(), sim.limits)

    def test_limits_look_uncalibrated(self) -> None:
        self.assertTrue(waveshare_servo.limits_look_uncalibrated(0, 1023))
        self.assertTrue(waveshare_servo.limits_look_uncalibrated(5, 1018))
        self.assertTrue(waveshare_servo.limits_look_uncalibrated(200, 225))
        self.assertFalse(waveshare_servo.limits_look_uncalibrated(69, 316))
        self.assertFalse(waveshare_servo.limits_look_uncalibrated(430, 705))
