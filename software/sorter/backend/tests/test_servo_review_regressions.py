"""Regressions for the 2026-09-05 review of the door-servo safeguards."""
import logging
import queue
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hardware.waveshare_bus_service import WaveshareBusService
from hardware.waveshare_servo import WaveshareServoMotor
from subsystems.distribution.sending import CHUTE_SETTLE_MS
from subsystems.distribution.states import DistributionState
from tests.test_distribution_sending import (
    SendingChuteReopenGateTests,
    _FakeDoor,
    _FakeVision,
    _GlobalConfig,
    _mkSending,
)
from tests.test_waveshare_servo import _FakeBus


class _TorqueBus(_FakeBus):
    def __init__(self):
        super().__init__()
        self.max_torque = 1000
        self.torque_writes = []
        self.move_ok = True
        self.position = 100

    def read_max_torque(self, servo_id):
        return self.max_torque

    def set_max_torque(self, servo_id, permille):
        self.torque_writes.append(permille); self.max_torque = permille; return True

    def move_to(self, servo_id, position, time_ms=500):
        if not self.move_ok:
            return False
        self.position = position
        return super().move_to(servo_id, position, time_ms)

    def read_position(self, servo_id):
        return self.position


class TorqueCapThroughBusServiceTests(unittest.TestCase):
    def test_initialize_writes_the_cap_through_the_service(self):
        fake = _TorqueBus()
        with patch("hardware.waveshare_bus_service.ScServoBus", return_value=fake):
            service = WaveshareBusService("/dev/null")
            service.attach_persistent()
            motor = WaveshareServoMotor(service, 16, max_torque_permille=600)
            motor.initialize()
        self.assertEqual([600], fake.torque_writes)
        self.assertEqual(600, service.read_max_torque(16))


class TargetReachedTests(unittest.TestCase):
    def test_rejected_close_never_counts_as_arrived(self):
        bus = _TorqueBus()
        motor = WaveshareServoMotor(bus, 16)
        motor.initialize()
        motor.close()                      # accepted: position follows
        self.assertTrue(motor.target_reached())
        bus.move_ok = False
        motor.open()                       # rejected: flap stays closed
        self.assertFalse(motor.target_reached())

    def test_measured_position_is_compared_with_the_requested_one(self):
        bus = _TorqueBus()
        motor = WaveshareServoMotor(bus, 16)
        motor.initialize()
        motor.close()
        bus.position = 100                 # something pushed it back open
        self.assertFalse(motor.target_reached())
        self.assertIsNone(WaveshareServoMotor(_TorqueBus(), 2).target_reached(), "nothing commanded yet")


class SendingHoldRegressionTests(unittest.TestCase):
    def _sending(self, gc, door, live_ids):
        helper = SendingChuteReopenGateTests()
        transport = helper._mkTransportWithDrop(tracked_global_id=9)
        shared = helper._mkSharedWithTransport(transport)
        shared.set_chute_motion(False, target_bin=SimpleNamespace(layer_index=0))
        return _mkSending(vision=_FakeVision(live_ids_by_role={"carousel": live_ids}), cooldown_s=0.0,
                          shared=shared, event_queue=queue.Queue(), gc=gc, servos=[door])

    def test_door_is_held_once_even_while_the_gate_keeps_waiting(self):
        door = _FakeDoor()
        sending = self._sending(_GlobalConfig(), door, live_ids={9})  # tracker still sees the piece
        self.assertIsNone(sending.step())
        sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 1.0
        for _ in range(5):
            self.assertIsNone(sending.step())  # settle done, waiting for the piece to leave
        self.assertEqual(["hold", "release"], door.calls)
        sending.vision.setLive("carousel", set())
        self.assertEqual(DistributionState.IDLE, sending.step())
        self.assertEqual(["hold", "release"], door.calls)

    def test_disable_servos_skips_the_hold(self):
        gc = _GlobalConfig()
        gc.disable_servos = True
        door = _FakeDoor()
        sending = self._sending(gc, door, live_ids=set())
        self.assertIsNone(sending.step())
        sending.start_time = time.time() - (CHUTE_SETTLE_MS / 1000.0) - 1.0
        sending.step()
        self.assertEqual([], door.calls)


if __name__ == "__main__":
    unittest.main()
