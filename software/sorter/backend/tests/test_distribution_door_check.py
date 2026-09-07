import logging
import unittest
from types import SimpleNamespace

from subsystems.distribution.positioning import Positioning


class _Door:
    def __init__(self, reached, close_raises: bool = False):
        self.reached = reached
        self.closes = 0
        self.holds = 0
        self.releases = 0
        self.position = 123
        self.close_raises = close_raises

    def target_reached(self, tolerance: int = 15):
        return self.reached

    def close(self):
        self.closes += 1
        if self.close_raises:
            raise RuntimeError("bus gone")

    def hold(self):
        self.holds += 1

    def release(self):
        self.releases += 1


def _positioning(door) -> Positioning:
    p = Positioning.__new__(Positioning)
    p.gc = SimpleNamespace(disable_servos=False, logger=logging.getLogger("test"))
    p.logger = p.gc.logger
    p.irl = SimpleNamespace(servos=[door])
    p._door_servo_index = 0
    p._door_retries = 0
    p._door_unknown_reads = 0
    p._door_handed_off = False
    p._moving_started_at = 0.0
    p.shared = SimpleNamespace(held_door=None)
    p.alerts = []
    p._raiseChuteJamAlert = lambda msg: p.alerts.append(msg)
    p._markLayerUnavailable = lambda index, reason: p.alerts.append(f"unavailable:{reason}")
    return p


class DoorArrivalCheckTests(unittest.TestCase):
    def test_reached_passes_and_unknown_does_not(self):
        self.assertTrue(_positioning(_Door(True))._targetDoorArrived(10.0))
        door = _Door(None)
        unknown = _positioning(door)
        # One bus read per tick: the first two unreadable ticks just wait,
        # the third counts as "unknown" and triggers the single re-close.
        self.assertFalse(unknown._targetDoorArrived(10.0), "no reading is not a pass")
        self.assertFalse(unknown._targetDoorArrived(10.1))
        self.assertEqual(0, door.closes)
        self.assertFalse(unknown._targetDoorArrived(10.2))
        self.assertEqual(1, door.closes)

    def test_failed_reclose_never_passes(self):
        door = _Door(False, close_raises=True)
        p = _positioning(door)
        self.assertFalse(p._targetDoorArrived(10.0))
        self.assertEqual(1, door.closes)
        self.assertTrue(any(a.startswith("unavailable:") for a in p.alerts))
        self.assertTrue(any("re-close failed" in a for a in p.alerts))
        self.assertFalse(p._targetDoorArrived(11.0), "still no dispense afterwards")

    def test_verified_door_is_held_before_ready_and_released_on_abort(self):
        door = _Door(True)
        p = _positioning(door)
        p._holdVerifiedDoor()
        self.assertEqual(1, door.holds)
        self.assertIs(p.shared.held_door, door)
        self.assertTrue(p._door_handed_off)
        # Handed off to READY/SENDING: positioning's cleanup leaves it held.
        p._door_handed_off = True
        p._releaseSharedDoor("test")  # what sending / the state machine do later
        self.assertEqual(1, door.releases)
        self.assertIsNone(p.shared.held_door)

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
