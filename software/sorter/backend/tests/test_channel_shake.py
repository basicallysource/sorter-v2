import logging
import unittest
from types import SimpleNamespace

from subsystems.classification_channel.simple_state_machine_rev01.channel_clear import (
    shakeChannelClear,
)


class _Stage(SimpleNamespace):
    pass


def _stage(name, amp, cycles=2, speed=900, accel=2000, settle_ms=0):
    return _Stage(
        name=name,
        amplitude_output_deg=amp,
        cycles=cycles,
        microsteps_per_second=speed,
        acceleration_microsteps_per_second_sq=accel,
        settle_ms=settle_ms,
    )


class _Perception:
    def __init__(self, counts):
        self._counts = list(counts)

    def read_state(self, channel):
        n = self._counts.pop(0) if len(self._counts) > 1 else self._counts[0]
        return SimpleNamespace(n_pieces=n)


class _Stepper:
    def __init__(self):
        self.calls = []

    def jitter_degrees(self, amplitude, cycles, speed, accel, *, force=False):
        self.calls.append((round(amplitude, 2), cycles, speed, accel, force))
        return True

    def is_jittering(self):
        return False


def _gc(counts):
    return SimpleNamespace(
        logger=logging.getLogger("test"), perception_service=_Perception(counts)
    )


def _irl_config(stages):
    return SimpleNamespace(
        exit_release_shimmy_stages=tuple(stages),
        exit_release_shimmy_stepper_per_output_deg=10.0,
    )


class ShakeChannelClearTests(unittest.TestCase):
    def test_walks_ladder_until_channel_empty(self):
        stepper = _Stepper()
        irl = SimpleNamespace(carousel_stepper=stepper)
        # occupied at start, still occupied after stage 1, empty after stage 2
        result = shakeChannelClear(
            _gc([1, 1, 0]), irl, _irl_config([_stage("a", 0.25), _stage("b", 0.5), _stage("c", 1.0)])
        )
        self.assertTrue(result.cleared)
        self.assertEqual("shaken_clear", result.reason)
        self.assertEqual([(2.5, 2, 900, 2000, True), (5.0, 2, 900, 2000, True)], stepper.calls)

    def test_reports_exhausted_when_piece_stays(self):
        stepper = _Stepper()
        irl = SimpleNamespace(carousel_stepper=stepper)
        result = shakeChannelClear(_gc([1]), irl, _irl_config([_stage("a", 0.25), _stage("b", 0.5)]))
        self.assertFalse(result.cleared)
        self.assertEqual("shake_exhausted", result.reason)
        self.assertEqual(2, len(stepper.calls))

    def test_skips_when_already_clear_or_unconfigured(self):
        stepper = _Stepper()
        irl = SimpleNamespace(carousel_stepper=stepper)
        self.assertEqual("already_clear", shakeChannelClear(_gc([0]), irl, _irl_config([_stage("a", 0.25)])).reason)
        self.assertEqual("no_shimmy_config", shakeChannelClear(_gc([1]), irl, _irl_config([])).reason)
        self.assertEqual([], stepper.calls)


if __name__ == "__main__":
    unittest.main()
