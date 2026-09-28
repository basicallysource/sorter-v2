import logging
import unittest
from types import SimpleNamespace

from irl.parse_user_toml import _parseStepperEncoders, applyStepperEncoder


def _gc():
    return SimpleNamespace(logger=logging.getLogger("test"))


class _Stepper:
    def __init__(self):
        self.calls = []

    def configure_encoder(self, **kwargs):
        self.calls.append(kwargs)


class StepperEncoderConfigTests(unittest.TestCase):
    def test_parses_defaults_and_overrides(self):
        raw = {
            "stepper_encoder": {
                "chute_stepper": {},
                "carousel": {"enabled": False, "sign": -1, "counts_per_rev": 4096, "tolerance_fullsteps": 2.5},
            }
        }
        parsed = _parseStepperEncoders(_gc(), raw)
        self.assertEqual((True, 1, 4096, 4.0), parsed["chute_stepper"])
        self.assertEqual((False, -1, 4096, 2.5), parsed["carousel"])

    def test_rejects_invalid_entries(self):
        raw = {"stepper_encoder": {"chute_stepper": {"sign": 2}, "carousel": "nope"}}
        self.assertEqual({}, _parseStepperEncoders(_gc(), raw))
        self.assertEqual({}, _parseStepperEncoders(_gc(), {}))

    def test_apply_derives_counts_per_microstep_and_tolerance(self):
        stepper = _Stepper()
        applyStepperEncoder(stepper, "chute_stepper", {"chute_stepper": (True, -1, 4096, 4.0)}, 8, _gc())
        self.assertEqual(1, len(stepper.calls))
        call = stepper.calls[0]
        self.assertTrue(call["enable"])
        self.assertEqual(-1, call["sign"])
        self.assertAlmostEqual(4096 / 1600, call["counts_per_microstep"])
        self.assertEqual(32, call["tolerance_microsteps"])

    def test_apply_skips_steppers_without_entry(self):
        stepper = _Stepper()
        applyStepperEncoder(stepper, "carousel", {"chute_stepper": (True, 1, 4096, 4.0)}, 8, _gc())
        self.assertEqual([], stepper.calls)


if __name__ == "__main__":
    unittest.main()
