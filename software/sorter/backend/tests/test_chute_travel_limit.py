import logging
import unittest
from types import SimpleNamespace

from irl.parse_user_toml import loadChuteCalibrationConfig
from subsystems.distribution.chute import Chute
from subsystems.distribution.positioning import Positioning


class _Stepper:
    def __init__(self):
        self.moves = []
        self.position_degrees = 0.0

    def estimateMoveDegreesMs(self, delta, max_speed=None):
        return 100

    def move_degrees(self, delta):
        self.moves.append(delta)

    def set_speed_limits(self, lo, hi):
        pass


def _chute(max_angle_deg):
    gc = SimpleNamespace(logger=logging.getLogger("test"), disable_chute=False)
    chute = Chute(gc, stepper=_Stepper(), home_pin=SimpleNamespace(value=False), layout=SimpleNamespace(layers=[]),
                  num_sections=6, section_width_deg=51.75, first_section_offset_deg=8.25, max_angle_deg=max_angle_deg)
    chute._applyOperatingSpeed = lambda: None
    return chute


class ChuteTravelLimitTests(unittest.TestCase):
    def test_bins_beyond_the_limit_are_unreachable(self):
        wide, narrow = _chute(350), _chute(305)
        # section 5 starts at 308.25°: reachable with the code default, not on this machine
        self.assertIsNotNone(wide.angleForVirtualBin(5, 0, 3))
        self.assertIsNone(narrow.angleForVirtualBin(5, 0, 3))
        self.assertIsNotNone(narrow.angleForVirtualBin(4, 2, 3))

    def test_target_moves_beyond_the_limit_are_refused(self):
        chute = _chute(305)
        chute.moveToAngle(300)
        self.assertEqual(1, len(chute.stepper.moves))
        with self.assertRaises(ValueError):
            chute.moveToAngle(320)
        with self.assertRaises(ValueError):
            chute.moveToAngleBlocking(-1)
        self.assertEqual(1, len(chute.stepper.moves), "a refused target must not move")

    def test_limit_comes_from_machine_toml(self):
        gc = SimpleNamespace(logger=logging.getLogger("test"))
        self.assertEqual(305.0, loadChuteCalibrationConfig(gc, {"chute": {"max_angle_deg": 305}}).max_angle_deg)
        self.assertEqual(350.0, loadChuteCalibrationConfig(gc, {"chute": {}}).max_angle_deg)
        self.assertEqual(350.0, loadChuteCalibrationConfig(gc, {"chute": {"max_angle_deg": 5}}).max_angle_deg)


class _Door:
    def __init__(self, answers):
        self.answers = list(answers)
        self.closes = 0
        self.position = 77

    def target_reached(self, tolerance: int = 15):
        return self.answers.pop(0) if self.answers else None

    def close(self):
        self.closes += 1


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


class DoorFeedbackUnknownTests(unittest.TestCase):
    def test_a_late_reading_still_passes(self):
        p = _positioning(_Door([None, None, True]))
        self.assertTrue(p._targetDoorArrived(1.0))
        self.assertEqual([], p.alerts)

    def test_no_reading_at_all_blocks_the_dispense(self):
        door = _Door([None] * 10)
        p = _positioning(door)
        self.assertFalse(p._targetDoorArrived(1.0))
        self.assertEqual(1, door.closes, "one re-close attempt")
        self.assertFalse(p._targetDoorArrived(2.0))
        self.assertEqual(1, len(p.alerts))
        self.assertIn("unknown", p.alerts[0])

    def test_exceptions_count_as_unknown(self):
        class _Broken(_Door):
            def target_reached(self, tolerance: int = 15):
                raise RuntimeError("bus down")
        door = _Broken([])
        p = _positioning(door)
        self.assertFalse(p._targetDoorArrived(1.0))
        self.assertFalse(p._targetDoorArrived(2.0))
        self.assertEqual(1, len(p.alerts))


if __name__ == "__main__":
    unittest.main()
