import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from irl.config import mkIRLConfig
from server.routers import setup, steppers


class ClassificationChannelC4HardwareTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.machine_params_path = Path(self._tmpdir.name) / "machine_params.toml"
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params
        self._tmpdir.cleanup()

    def test_classification_setup_uses_c_channel_stepper_config_for_c4(self) -> None:
        self.machine_params_path.write_text(
            """
[machine_setup]
type = "classification_channel"

[cameras]
layout = "split_feeder"
c_channel_2 = 0
c_channel_3 = 1
classification_channel = 2
""".strip()
        )

        config = mkIRLConfig()

        self.assertEqual(8, config.carousel_stepper.microsteps)
        self.assertEqual(4000, config.carousel_stepper.default_steps_per_second)
        self.assertIs(config.c_channel_4_rotor_stepper, config.carousel_stepper)

    def test_stepper_api_exposes_c4_as_alias_for_carousel_port(self) -> None:
        stepper = object()
        irl = SimpleNamespace(carousel_stepper=stepper)

        with patch("server.routers.steppers.shared_state.getActiveIRL", return_value=irl):
            mapping = steppers._stepper_mapping()

        self.assertIs(mapping["c_channel_4"], stepper)
        self.assertIs(mapping["carousel"], stepper)

    def test_setup_direction_c4_persists_to_carousel_backing_axis(self) -> None:
        self.machine_params_path.write_text(
            """
[machine_setup]
type = "classification_channel"
""".strip()
        )
        stepper = SimpleNamespace(
            direction_inverted=False,
            set_direction_inverted=lambda value: setattr(stepper, "direction_inverted", value),
        )
        irl = SimpleNamespace(carousel_stepper=stepper)

        with patch("server.routers.setup.shared_state.getActiveIRL", return_value=irl):
            response = setup.set_stepper_direction(
                "c_channel_4",
                setup.StepperDirectionPayload(inverted=True),
            )

        persisted = tomllib.loads(self.machine_params_path.read_text())
        self.assertTrue(persisted["stepper_direction_inverts"]["carousel"])
        self.assertEqual("c_channel_4", response["stepper"])
        self.assertTrue(response["applied_live"])
        self.assertTrue(stepper.direction_inverted)
        self.assertIn(
            "c_channel_4",
            {entry["name"] for entry in response["steppers"]},
        )
