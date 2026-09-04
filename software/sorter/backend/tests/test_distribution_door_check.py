import logging
import unittest
from types import SimpleNamespace

from subsystems.distribution.positioning import Positioning


class _Door:
    def __init__(self, reached):
        self.reached = reached
        self.closes = 0
        self.position = 123

    def target_reached(self, tolerance: int = 15):
        return self.reached

    def close(self):
        self.closes += 1


def _positioning(door) -> Positioning:
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


class DoorArrivalCheckTests(unittest.TestCase):
    def test_reached_or_unknown_passes(self):
        self.assertTrue(_positioning(_Door(True))._targetDoorArrived(10.0))
        self.assertTrue(_positioning(_Door(None))._targetDoorArrived(10.0))

    def test_missed_door_is_reclosed_once_then_alerts(self):
        door = _Door(False)
        p = _positioning(door)
        self.assertFalse(p._targetDoorArrived(10.0))
        self.assertEqual(1, door.closes)
        self.assertEqual(10.0, p._moving_started_at)
        self.assertEqual([], p.alerts)
        self.assertFalse(p._targetDoorArrived(12.0))
        self.assertEqual(1, door.closes, "only one retry")
        self.assertEqual(1, len(p.alerts))
        self.assertIn("layer-0 door", p.alerts[0])

    def test_servos_without_feedback_are_trusted(self):
        p = _positioning(SimpleNamespace(close=lambda: None))
        self.assertTrue(p._targetDoorArrived(10.0))


if __name__ == "__main__":
    unittest.main()
