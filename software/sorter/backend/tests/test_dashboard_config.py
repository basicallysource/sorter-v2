import os
from pathlib import Path
import tempfile
import unittest

from toml_config import (
    getDashboardConfig,
    incidentHandlingAutomatic,
    incidentHandlingOff,
    setDashboardConfig,
)


class DashboardConfigTests(unittest.TestCase):
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

    def test_dashboard_config_exposes_incident_defaults_and_definitions(self) -> None:
        config = getDashboardConfig()

        self.assertFalse(config["show_sample_capture"])
        self.assertEqual("manual", config["incident_handling"]["channel_dropzone_stuck"])
        self.assertEqual("manual", config["incident_handling"]["exit_stuck"])
        self.assertEqual("manual", config["incident_handling"]["bulk_feeder_stalled"])
        self.assertEqual("manual", config["incident_handling"]["feeder_detection_unavailable"])
        self.assertEqual("manual", config["incident_handling"]["distribution_chute_jam"])
        self.assertEqual("manual", config["incident_handling"]["distribution_servo_bus_offline"])
        self.assertEqual("manual", config["incident_handling"]["classification_unresolved"])
        self.assertEqual("manual", config["incident_handling"]["classification_multi_drop_collision"])
        self.assertTrue(any(item["kind"] == "channel_dropzone_stuck" for item in config["incident_definitions"]))
        self.assertTrue(any(item["kind"] == "exit_stuck" for item in config["incident_definitions"]))
        self.assertTrue(any(item["kind"] == "bulk_feeder_stalled" for item in config["incident_definitions"]))
        self.assertTrue(any(item["kind"] == "feeder_detection_unavailable" for item in config["incident_definitions"]))
        self.assertTrue(any(item["kind"] == "distribution_chute_jam" for item in config["incident_definitions"]))
        self.assertTrue(any(item["kind"] == "distribution_servo_bus_offline" for item in config["incident_definitions"]))
        self.assertTrue(any(item["kind"] == "classification_unresolved" for item in config["incident_definitions"]))
        self.assertTrue(
            any(item["kind"] == "classification_multi_drop_collision" for item in config["incident_definitions"])
        )
        self.assertFalse(
            any(item["kind"] == "classification_exit_release" for item in config["incident_definitions"])
        )
        self.assertFalse(any(item["kind"] == "channel_exit_stuck" for item in config["incident_definitions"]))

    def test_dashboard_config_persists_valid_incident_modes_only(self) -> None:
        config = setDashboardConfig(
            {
                "incident_handling": {
                    "channel_dropzone_stuck": "automatic",
                    "classification_exit_release": "automatic",
                    "bulk_feeder_stalled": "off",
                    "feeder_detection_unavailable": "manual",
                    "distribution_chute_jam": "off",
                    "distribution_servo_bus_offline": "manual",
                    "classification_unresolved": "off",
                    "classification_multi_drop_collision": "manual",
                    "c2_separation_needed": "bogus",
                    "unknown_incident": "automatic",
                }
            }
        )

        self.assertEqual("automatic", config["incident_handling"]["channel_dropzone_stuck"])
        self.assertEqual("automatic", config["incident_handling"]["exit_stuck"])
        self.assertEqual("off", config["incident_handling"]["bulk_feeder_stalled"])
        self.assertEqual("manual", config["incident_handling"]["feeder_detection_unavailable"])
        self.assertEqual("off", config["incident_handling"]["distribution_chute_jam"])
        self.assertEqual("manual", config["incident_handling"]["distribution_servo_bus_offline"])
        self.assertEqual("off", config["incident_handling"]["classification_unresolved"])
        self.assertEqual("manual", config["incident_handling"]["classification_multi_drop_collision"])
        self.assertEqual("manual", config["incident_handling"]["c2_separation_needed"])
        self.assertNotIn("unknown_incident", config["incident_handling"])
        self.assertNotIn("classification_exit_release", config["incident_handling"])
        self.assertNotIn("channel_exit_stuck", config["incident_handling"])
        self.assertTrue(incidentHandlingAutomatic("channel_dropzone_stuck"))
        self.assertTrue(incidentHandlingAutomatic("classification_exit_release"))
        self.assertTrue(incidentHandlingAutomatic("channel_exit_stuck"))
        self.assertTrue(incidentHandlingOff("bulk_feeder_stalled"))
        self.assertTrue(incidentHandlingOff("classification_unresolved"))

        config = setDashboardConfig({"incident_handling": {"channel_exit_stuck": "off"}})

        self.assertEqual("off", config["incident_handling"]["exit_stuck"])
        self.assertTrue(incidentHandlingOff("classification_exit_release"))
        self.assertTrue(incidentHandlingOff("channel_exit_stuck"))


if __name__ == "__main__":
    unittest.main()
