"""Scenarios across the door safeguards: motor + positioning + controller
together, the way the machine actually runs them."""
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import irl  # noqa: F401  — resolves the irl <-> machine_platform import cycle in the package order main.py uses
from hardware.waveshare_servo import WaveshareServoMotor
from machine_platform.servo_controller import LayerServoAssignment, WaveshareServoController
from subsystems.distribution.positioning import Positioning
from tests.test_servo_review_regressions import _TorqueBus


def _positioning(door):
    p = Positioning.__new__(Positioning)
    p.gc = SimpleNamespace(disable_servos=False, logger=logging.getLogger("test"))
    p.logger = p.gc.logger
    p.irl = SimpleNamespace(servos=[door])
    p._door_servo_index = 0
    p._door_retries = 0
    p._moving_started_at = 0.0
    p.alerts = []
    p._raiseChuteJamAlert = lambda msg: p.alerts.append(msg)
    p._markLayerUnavailable = lambda index, reason: p.alerts.append(f"unavailable:{reason}")
    return p


class CloseFailsNoDispenseTests(unittest.TestCase):
    def test_rejected_close_commands_end_in_a_jam_alert_not_a_dispense(self):
        bus = _TorqueBus()
        door = WaveshareServoMotor(bus, 16)
        door.initialize()
        door.open()
        bus.move_ok = False              # the bus now rejects every move
        door.close()                     # what positioning's door config does
        p = _positioning(door)
        self.assertFalse(p._targetDoorArrived(1.0), "first check: re-close attempt")
        self.assertFalse(p._targetDoorArrived(2.0), "second check: alert")
        self.assertEqual(1, len(p.alerts))
        self.assertNotIn("unavailable", p.alerts[0])

    def test_flap_pushed_back_after_a_good_close_is_caught(self):
        bus = _TorqueBus()
        door = WaveshareServoMotor(bus, 16)
        door.initialize()
        door.close()
        p = _positioning(door)
        self.assertTrue(p._targetDoorArrived(1.0))
        bus.position = door._open_position   # yielded to a piece
        self.assertFalse(p._targetDoorArrived(2.0))


class _ResetBus(_TorqueBus):
    """A servo whose calibration was cleared by 'Install position'."""
    def read_angle_limits(self, servo_id):
        return (0, 1023)


class _Service:
    def __init__(self, bus):
        self._bus = bus
        self.attached = 0

    def attach_persistent(self):
        self.attached += 1

    def __getattr__(self, name):
        return getattr(self._bus, name)


class CalibrationResetLocksLayerTests(unittest.TestCase):
    def test_uncalibrated_servo_leaves_its_layer_offline(self):
        controller = WaveshareServoController(
            SimpleNamespace(logger=logging.getLogger("test")),
            port="/dev/fake",
            assignments=[LayerServoAssignment(id=16, invert=False)],
            mcu_ports=[],
            max_torque_percent=60,
        )
        service = _Service(_ResetBus())
        layout = SimpleNamespace(layers=[SimpleNamespace(enabled=True)])
        with patch.object(controller, "_resolve_port", return_value="/dev/fake"), \
                patch("hardware.waveshare_bus_service.get_waveshare_bus_service", return_value=service):
            servos = controller.create_layer_servos(layout)
        self.assertEqual(1, len(servos))
        self.assertFalse(servos[0].available)
        self.assertIn("calibrat", str(controller.issues).lower())


if __name__ == "__main__":
    unittest.main()
