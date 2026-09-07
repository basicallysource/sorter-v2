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
        from subsystems.feeder.belt.flow import BeltLoadMonitor
        flow._load = BeltLoadMonitor(0, 3)
        flow._load_next_poll_at = 0.0
        flow._load_last_log_at = 0.0
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


class BeltLoadMonitorTests(unittest.TestCase):
    def test_watch_mode_records_but_never_blocks(self) -> None:
        from subsystems.feeder.belt.flow import BeltLoadMonitor
        m = BeltLoadMonitor(threshold=0, samples=3)
        for sg in (400, 10, 0, 0, 0):
            self.assertFalse(m.observe(sg))
        self.assertEqual(m.last_sg, 0)

    def test_blocks_after_consecutive_low_reads_only(self) -> None:
        from subsystems.feeder.belt.flow import BeltLoadMonitor
        m = BeltLoadMonitor(threshold=60, samples=3)
        self.assertFalse(m.observe(500))
        self.assertFalse(m.observe(30))
        self.assertFalse(m.observe(20))
        self.assertFalse(m.observe(300))   # a free read resets the streak
        self.assertFalse(m.observe(10))
        self.assertFalse(m.observe(10))
        self.assertTrue(m.observe(5))
        self.assertFalse(m.observe(None))  # an unreadable register is not evidence

    def test_defaults_are_watch_only_and_jam_window_is_shorter(self) -> None:
        cfg = BeltFeederConfig()
        self.assertEqual(cfg.load_block_sg_threshold, 0)
        self.assertEqual(cfg.jam_timeout_s, 20.0)


class _StepStepper:
    def __init__(self) -> None:
        self.speeds: list[int] = []
        self.limits: list[tuple[int, int]] = []
        self.stalled = False

    def move_at_speed(self, speed: int) -> bool:
        self.speeds.append(speed)
        return True

    def set_speed_limits(self, lo: int, hi: int) -> None:
        self.limits.append((lo, hi))


def _stepFlow(cfg: BeltFeederConfig, c3_pieces: int = 0, state_age_s: float = 0.0):
    """A BeltFeeding double wired for _step_belt: fake stepper, a perception
    service whose C3 state is ``state_age_s`` old, no chute move, no incidents."""
    import time as _time
    from subsystems.feeder.belt.flow import BeltLoadMonitor

    stepper = _StepStepper()
    state = SimpleNamespace(ts=_time.time() - state_age_s, n_pieces=c3_pieces)
    flow = BeltFeeding.__new__(BeltFeeding)
    flow.irl = SimpleNamespace(belt_stepper=stepper)
    flow.gc = SimpleNamespace(
        logger=SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
        perception_service=SimpleNamespace(read_states=lambda: {3: state}),
        rotary_channel_steppers_can_operate_in_parallel=True,
    )
    flow.shared = SimpleNamespace(chute_move_in_progress=False)
    flow._belt_cfg = lambda: cfg
    flow._belt_cmd_speed = 0
    flow._belt_cmd_unacked = False
    flow._belt_next_cmd_at = 0.0
    flow._belt_speed_limit = 0
    flow._belt_running_since = None
    flow._last_arrival_at = 0.0
    flow._last_c3_pieces = 0
    flow._last_blocked_reason = None
    flow._status = {}
    flow._load = BeltLoadMonitor(0, 3)
    flow._load_next_poll_at = 0.0
    flow._load_last_log_at = 0.0
    flow._nudge_until = 0.0
    flow._nudges_since_arrival = 0
    flow._perception_reason = "no_perception"
    return flow, stepper, state


class BeltStepSafetyTests(unittest.TestCase):
    """The belt never runs blind, never drives a latched stall, and a watchdog
    nudge is one bounded run per stall."""

    def test_fresh_state_runs_the_belt(self) -> None:
        flow, stepper, _ = _stepFlow(BeltFeederConfig(belt_speed_usteps_per_s=2000))
        flow._step_belt()
        self.assertEqual(stepper.speeds, [2000])
        self.assertEqual(flow._status["reason"], "running")

    def test_stale_perception_stops_the_belt(self) -> None:
        flow, stepper, _ = _stepFlow(BeltFeederConfig(perception_stale_s=2.0), state_age_s=5.0)
        flow._belt_cmd_speed = 2000
        flow._belt_running_since = 1.0
        flow._step_belt()
        self.assertEqual(stepper.speeds, [0])
        self.assertEqual(flow._status["reason"], "stale_perception")

    def test_stall_latch_stops_the_belt_before_any_command(self) -> None:
        flow, stepper, _ = _stepFlow(BeltFeederConfig())
        flow._belt_cmd_speed = 2000
        flow._belt_running_since = 1.0
        stepper.stalled = True
        flow._step_belt()
        self.assertEqual(stepper.speeds, [0])
        self.assertEqual(flow._status["reason"], "stalled")

    def test_nudge_is_one_bounded_run_per_stall(self) -> None:
        cfg = BeltFeederConfig(belt_speed_usteps_per_s=2000, c3_full_speed_pieces=1, c3_stop_pieces=2,
                               nudge_run_ms=1500, nudge_max_attempts=1)
        flow, stepper, state = _stepFlow(cfg, c3_pieces=2)  # C3 full: belt stopped
        flow._step_belt()
        self.assertEqual(stepper.speeds, [])
        self.assertEqual(flow._status["reason"], "stopped_c3_full")
        self.assertTrue(flow._nudge_belt())
        flow._step_belt()
        self.assertEqual(stepper.speeds, [2000])
        self.assertEqual(flow._status["reason"], "nudging")
        self.assertFalse(flow._nudge_belt())             # second request on the same stall: refused
        flow._nudge_until = 0.0                           # the run time elapsed
        flow._step_belt()
        self.assertEqual(stepper.speeds, [2000, 0])       # back under the fill-level controller
        state.n_pieces = 3                                 # a new piece reached C3
        flow._step_belt()
        self.assertTrue(flow._nudge_belt())               # a fresh stall gets its one nudge again

    def test_nudge_refused_on_a_latched_stall(self) -> None:
        flow, stepper, _ = _stepFlow(BeltFeederConfig())
        stepper.stalled = True
        self.assertFalse(flow._nudge_belt())


class FeederModePairingTests(unittest.TestCase):
    """belt_feeder <-> belt_rev01 is enforced at the feeder-mode endpoint."""

    def _post(self, monkey, setup_key: str, mode: str):
        from server.routers import setup as setup_router
        written: dict = {}
        monkey.setattr(setup_router, "_read_machine_params_config",
                       lambda: ("params.toml", {"machine_setup": {"type": setup_key}}))
        monkey.setattr(setup_router, "_write_machine_params_config",
                       lambda path, config: written.update(config))
        return setup_router.set_feeder_subsystem_mode(SimpleNamespace(mode=mode)), written

    def test_pairing(self) -> None:
        import pytest
        from fastapi import HTTPException
        from _pytest.monkeypatch import MonkeyPatch
        monkey = MonkeyPatch()
        try:
            result, written = self._post(monkey, BELT_FEEDER_SETUP, "belt_rev01")
            self.assertTrue(result["ok"]) ; self.assertEqual(written["feeder"]["mode"], "belt_rev01")
            with pytest.raises(HTTPException):
                self._post(monkey, BELT_FEEDER_SETUP, "pulse_perception_rev01")
            with pytest.raises(HTTPException):
                self._post(monkey, "classification_channel", "belt_rev01")
            result, _ = self._post(monkey, "classification_channel", "pulse_perception_rev01")
            self.assertTrue(result["ok"])
        finally:
            monkey.undo()


if __name__ == "__main__":
    unittest.main()


class BeltLoadMonitorTests(unittest.TestCase):
    def test_watch_mode_records_but_never_blocks(self) -> None:
        from subsystems.feeder.belt.flow import BeltLoadMonitor
        m = BeltLoadMonitor(threshold=0, samples=3)
        for sg in (400, 10, 0, 0, 0):
            self.assertFalse(m.observe(sg))
        self.assertEqual(m.last_sg, 0)

    def test_blocks_after_consecutive_low_reads_only(self) -> None:
        from subsystems.feeder.belt.flow import BeltLoadMonitor
        m = BeltLoadMonitor(threshold=60, samples=3)
        self.assertFalse(m.observe(500))
        self.assertFalse(m.observe(30))
        self.assertFalse(m.observe(20))
        self.assertFalse(m.observe(300))   # a free read resets the streak
        self.assertFalse(m.observe(10))
        self.assertFalse(m.observe(10))
        self.assertTrue(m.observe(5))
        self.assertFalse(m.observe(None))  # an unreadable register is not evidence

    def test_defaults_are_watch_only_and_jam_window_is_shorter(self) -> None:
        cfg = BeltFeederConfig()
        self.assertEqual(cfg.load_block_sg_threshold, 0)
        self.assertEqual(cfg.jam_timeout_s, 20.0)
