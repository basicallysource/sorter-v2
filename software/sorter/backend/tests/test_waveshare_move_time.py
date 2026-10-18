import logging
import time
import unittest
from types import SimpleNamespace

from hardware.waveshare_servo import WaveshareServoMotor
from irl.parse_user_toml import loadWaveshareServoConfig
from tests.test_waveshare_servo import _FakeBus


def _gc():
    return SimpleNamespace(logger=logging.getLogger("test"))


class _TimedBus(_FakeBus):
    def __init__(self):
        super().__init__()
        self.move_times = []

    def move_to(self, servo_id, position, time_ms=500):
        self.move_times.append(time_ms)
        return super().move_to(servo_id, position, time_ms)


class WaveshareMoveTimeTests(unittest.TestCase):
    def test_config_reads_move_time_and_rejects_nonsense(self):
        raw = {"servo": {"backend": "waveshare", "move_time_ms": 1200}}
        self.assertEqual(1200, loadWaveshareServoConfig(_gc(), raw).move_time_ms)
        self.assertEqual(500, loadWaveshareServoConfig(_gc(), {"servo": {"backend": "waveshare"}}).move_time_ms)
        self.assertEqual(500, loadWaveshareServoConfig(_gc(), {"servo": {"backend": "waveshare", "move_time_ms": 9}}).move_time_ms)
        self.assertEqual(500, loadWaveshareServoConfig(_gc(), {"servo": {"backend": "waveshare", "move_time_ms": "slow"}}).move_time_ms)

    def test_door_moves_use_the_configured_time(self):
        bus = _TimedBus()
        motor = WaveshareServoMotor(bus, 1, move_time_ms=1200)
        motor.initialize()
        motor.open()
        self.assertEqual([1200], bus.move_times)
        self.assertAlmostEqual(1.2, motor._move_duration)
        time.sleep(0.05)
        motor.close()
        self.assertEqual([1200, 1200], bus.move_times)


if __name__ == "__main__":
    unittest.main()


class _TorqueBus(_FakeBus):
    def __init__(self, current: int | None = 1000):
        super().__init__()
        self.max_torque = current
        self.torque_writes: list[int] = []

    def read_max_torque(self, servo_id):
        return self.max_torque

    def set_max_torque(self, servo_id, permille):
        self.torque_writes.append(permille)
        self.max_torque = permille
        return True


class WaveshareTorqueCapTests(unittest.TestCase):
    def test_config_reads_percent_and_rejects_nonsense(self):
        load = lambda servo: loadWaveshareServoConfig(_gc(), {"servo": {"backend": "waveshare", **servo}})
        self.assertEqual(40, load({"max_torque_percent": 40}).max_torque_percent)
        self.assertEqual(100, load({}).max_torque_percent)
        self.assertEqual(100, load({"max_torque_percent": 5}).max_torque_percent)
        self.assertEqual(100, load({"max_torque_percent": "half"}).max_torque_percent)

    def test_cap_is_written_only_when_it_differs(self):
        from hardware.waveshare_servo import apply_max_torque

        bus = _TorqueBus(current=1000)
        self.assertEqual(1000, apply_max_torque(bus, 2, 400))
        self.assertEqual([400], bus.torque_writes)
        self.assertIsNone(apply_max_torque(bus, 2, 400))
        self.assertEqual([400], bus.torque_writes)
        self.assertIsNone(apply_max_torque(bus, 2, None))
        self.assertIsNone(apply_max_torque(_FakeBus(), 2, 400), "buses without the register are left alone")

    def test_motor_initialize_applies_the_cap(self):
        bus = _TorqueBus(current=1000)
        motor = WaveshareServoMotor(bus, 2, max_torque_permille=400)
        motor.initialize()
        self.assertEqual([400], bus.torque_writes)
        untouched = _TorqueBus(current=1000)
        WaveshareServoMotor(untouched, 2).initialize()
        self.assertEqual([], untouched.torque_writes)
