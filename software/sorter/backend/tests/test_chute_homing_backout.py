"""Homing starts outside the endstop flag: the backout probes until the sensor
releases, halts on a probe that does not finish, and never leaves a stale
home reference behind."""
import inspect
import logging
import unittest
from types import SimpleNamespace

from subsystems.distribution.chute import Chute, HOME_BACKOUT_MAX_PROBES


class _Stepper:
    def __init__(self, probe_results=None):
        self.moves: list[float] = []
        self.probe_results = list(probe_results or [])
        self.enabled = False
        self.force_calls: list[bool] = []
        self.position_degrees = 0.0

    def move_degrees_blocking(self, degrees, timeout_ms=5000):
        self.moves.append(degrees)
        return self.probe_results.pop(0) if self.probe_results else True

    def enable_force(self, value):
        self.force_calls.append(bool(value))

    def estimateMoveDegreesMs(self, delta, max_speed=None):
        return 100

    def set_speed_limits(self, lo, hi):
        pass


class _Pin:
    """Endstop that releases after ``active_reads`` reads."""

    def __init__(self, active_reads):
        self.active_reads = active_reads
        self.reads = 0

    @property
    def value(self):
        self.reads += 1
        return self.reads <= self.active_reads


def _chute(stepper, pin, homed=False):
    gc = SimpleNamespace(logger=logging.getLogger("test"), disable_chute=False)
    wanted = dict(stepper=stepper, home_pin=pin, layout=SimpleNamespace(layers=[]),
                  num_sections=6, section_width_deg=51.75, first_section_offset_deg=8.25, max_angle_deg=350)
    accepted = inspect.signature(Chute.__init__).parameters
    chute = Chute(gc, **{k: v for k, v in wanted.items() if k in accepted})
    if hasattr(chute, "_applyOperatingSpeed"):
        chute._applyOperatingSpeed = lambda: None
    chute._homed = homed
    return chute


class BackoutTests(unittest.TestCase):
    def test_probes_until_the_sensor_releases(self):
        stepper = _Stepper()
        chute = _chute(stepper, _Pin(active_reads=3))  # initial check + 2 probes still active
        self.assertTrue(chute._backOutOfEndstop())
        self.assertEqual(3, len(stepper.moves))
        self.assertTrue(stepper.enabled, "driver re-enabled before probing")

    def test_inactive_sensor_needs_no_backout(self):
        stepper = _Stepper()
        self.assertTrue(_chute(stepper, _Pin(active_reads=0))._backOutOfEndstop())
        self.assertEqual([], stepper.moves)

    def test_stuck_sensor_gives_up_after_the_probe_budget(self):
        stepper = _Stepper()
        chute = _chute(stepper, _Pin(active_reads=10_000))
        self.assertFalse(chute._backOutOfEndstop())
        self.assertEqual(HOME_BACKOUT_MAX_PROBES, len(stepper.moves))

    def test_unfinished_probe_halts_and_aborts(self):
        stepper = _Stepper(probe_results=[True, False])
        chute = _chute(stepper, _Pin(active_reads=10_000), homed=True)
        self.assertFalse(chute.home())
        self.assertEqual(2, len(stepper.moves), "no further probe on top of a move that may still run")
        self.assertEqual([False], stepper.force_calls, "driver cut so the unfinished move cannot continue")
        self.assertFalse(chute.homed, "a failed backout leaves no stale home reference")


if __name__ == "__main__":
    unittest.main()
