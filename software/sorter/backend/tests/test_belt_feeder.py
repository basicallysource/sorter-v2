"""B1 belt-feeder topology: setup registry, stepper requirements, and the
fill-level speed controller (pure math — no hardware)."""

import unittest
from types import SimpleNamespace

from machine_setup import BELT_FEEDER_SETUP, MACHINE_SETUPS
from irl.config import FeederMode, PERCEPTION_NATIVE_FEEDER_MODES, _requiredCanonicalStepperNames
from subsystems.feeder.belt.config import BeltFeederConfig, configFromDict, configToDict
from subsystems.feeder.belt.flow import BeltFeeding


class BeltFeederSetupTests(unittest.TestCase):
    def test_belt_feeder_setup_registered(self) -> None:
        definition = MACHINE_SETUPS[BELT_FEEDER_SETUP]
        self.assertTrue(definition.uses_belt_feeder)
        self.assertTrue(definition.automatic_feeder)
        self.assertTrue(definition.uses_classification_channel)
        self.assertFalse(definition.uses_carousel_transport)
        self.assertFalse(definition.requires_carousel_endstop)
        self.assertTrue(definition.to_dict()["uses_belt_feeder"])

    def test_other_setups_do_not_use_belt(self) -> None:
        for key, definition in MACHINE_SETUPS.items():
            if key == BELT_FEEDER_SETUP:
                continue
            self.assertFalse(definition.uses_belt_feeder, key)

    def test_belt_mode_is_perception_native(self) -> None:
        self.assertIn(FeederMode.BELT_REV01, PERCEPTION_NATIVE_FEEDER_MODES)

    def test_required_steppers_skip_c2(self) -> None:
        required = _requiredCanonicalStepperNames(MACHINE_SETUPS[BELT_FEEDER_SETUP], {})
        self.assertIn("c_channel_1_rotor", required)
        self.assertIn("c_channel_3_rotor", required)
        self.assertNotIn("c_channel_2_rotor", required)
        self.assertNotIn("carousel", required)


class BeltFeederConfigTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        cfg = BeltFeederConfig(belt_speed_usteps_per_s=3200, c3_stop_pieces=5)
        self.assertEqual(configFromDict(configToDict(cfg)), cfg)

    def test_from_dict_ignores_unknown_and_bad_values(self) -> None:
        cfg = configFromDict({"belt_speed_usteps_per_s": "1500", "nope": 1, "jam_timeout_s": None})
        self.assertEqual(cfg.belt_speed_usteps_per_s, 1500)
        self.assertEqual(cfg.jam_timeout_s, BeltFeederConfig().jam_timeout_s)


class BeltTargetSpeedTests(unittest.TestCase):
    """_target_speed is pure — full speed at/below the full-speed count,
    linear ramp, stop at/above the stop count."""

    def _speed(self, cfg: BeltFeederConfig, pieces: int) -> int:
        return BeltFeeding._target_speed(None, cfg, pieces)  # type: ignore[arg-type]

    def test_ramp(self) -> None:
        cfg = BeltFeederConfig(belt_speed_usteps_per_s=2000, c3_full_speed_pieces=1, c3_stop_pieces=3)
        self.assertEqual(self._speed(cfg, 0), 2000)
        self.assertEqual(self._speed(cfg, 1), 2000)
        self.assertEqual(self._speed(cfg, 2), 1000)
        self.assertEqual(self._speed(cfg, 3), 0)
        self.assertEqual(self._speed(cfg, 7), 0)

    def test_disabled_belt_never_moves(self) -> None:
        cfg = BeltFeederConfig(enable_belt=False)
        self.assertEqual(self._speed(cfg, 0), 0)

    def test_degenerate_thresholds_still_stop(self) -> None:
        # stop <= full is clamped to full+1 instead of dividing by zero.
        cfg = BeltFeederConfig(c3_full_speed_pieces=2, c3_stop_pieces=2)
        self.assertEqual(self._speed(cfg, 2), BeltFeederConfig().belt_speed_usteps_per_s)
        self.assertEqual(self._speed(cfg, 3), 0)


class BeltHoldMotionTests(unittest.TestCase):
    """The coordinator calls hold_motion instead of step during incidents /
    manual feed: a velocity move must be stopped explicitly, once."""

    class _Stepper:
        def __init__(self) -> None:
            self.speeds: list[int] = []

        def move_at_speed(self, speed: int) -> bool:
            self.speeds.append(speed)
            return True

    def _feeding(self, running_speed: int) -> tuple[BeltFeeding, "_Stepper"]:
        stepper = self._Stepper()
        flow = BeltFeeding.__new__(BeltFeeding)
        flow.irl = SimpleNamespace(belt_stepper=stepper)
        flow.gc = SimpleNamespace(logger=SimpleNamespace(warning=lambda *a, **k: None))
        flow._belt_cmd_speed = running_speed
        flow._belt_cmd_unacked = False
        flow._belt_running_since = 1.0 if running_speed else None
        flow._last_arrival_at = 0.0
        flow._last_blocked_reason = None
        flow._status = {}
        return flow, stepper

    def test_hold_stops_a_running_belt_once(self) -> None:
        flow, stepper = self._feeding(2000)
        flow.hold_motion()
        flow.hold_motion()
        self.assertEqual(stepper.speeds, [0])
        self.assertEqual(flow._belt_cmd_speed, 0)
        self.assertIsNone(flow._belt_running_since)
        self.assertEqual(flow._status["reason"], "held")

    def test_hold_is_a_no_op_while_stopped(self) -> None:
        flow, stepper = self._feeding(0)
        flow.hold_motion()
        self.assertEqual(stepper.speeds, [])

    def test_hold_retries_after_an_unacknowledged_command(self) -> None:
        flow, stepper = self._feeding(0)
        flow._belt_cmd_unacked = True
        flow.hold_motion()
        self.assertEqual(stepper.speeds, [0])
        self.assertFalse(flow._belt_cmd_unacked)


class BeltUpstreamTests(unittest.TestCase):
    """The C3 stuck watchdog must blame and nudge the belt, not a C2 that
    does not exist in this topology."""

    def test_c3_upstream_is_the_belt(self) -> None:
        flow = BeltFeeding.__new__(BeltFeeding)
        stepper = object()
        flow.irl = SimpleNamespace(belt_stepper=stepper)
        flow._belt_cfg = lambda: BeltFeederConfig(enable_belt=True)
        upstream = flow._c3_upstream(None)
        self.assertEqual(upstream.label, "B1 belt")
        self.assertIs(upstream.stepper, stepper)
        self.assertTrue(upstream.enabled)
        self.assertEqual(upstream.nudge, flow._nudge_belt)


if __name__ == "__main__":
    unittest.main()
