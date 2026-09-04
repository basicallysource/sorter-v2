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
