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
        self.assertEqual("automatic", config["incident_handling"]["exit_stuck"])
        self.assertEqual("automatic", config["incident_handling"]["feeder_jam"])
        self.assertEqual("manual", config["incident_handling"]["distribution_chute_jam"])
        self.assertEqual("manual", config["incident_handling"]["distribution_servo_bus_offline"])
        self.assertEqual("manual", config["incident_handling"]["distribution_no_bin_available"])
        definition_kinds = [item["kind"] for item in config["incident_definitions"]]
        self.assertEqual(
            [
                "exit_stuck",
                "feeder_jam",
                "distribution_chute_jam",
                "distribution_servo_bus_offline",
                "distribution_no_bin_available",
            ],
            definition_kinds,
        )

    def test_dashboard_config_only_lists_default_codepath_kinds(self) -> None:
        config = getDashboardConfig()

        # Kinds only raised on legacy codepaths must not get a policy row.
        for legacy_kind in (
            "channel_dropzone_stuck",
            "c2_separation_needed",
            "bulk_feeder_stalled",
            "feeder_detection_unavailable",
            "classification_unresolved",
            "classification_multi_drop_collision",
            "classification_intake_request_timeout",
            "classification_track_lost",
            "classification_exit_stuck",
            "classification_exit_release",
            "channel_exit_stuck",
        ):
            self.assertNotIn(legacy_kind, config["incident_handling"])
            self.assertFalse(
                any(item["kind"] == legacy_kind for item in config["incident_definitions"])
            )

    def test_dashboard_config_persists_valid_incident_modes_only(self) -> None:
        config = setDashboardConfig(
            {
                "incident_handling": {
                    "classification_exit_release": "manual",
                    "distribution_chute_jam": "off",
                    "distribution_servo_bus_offline": "manual",
                    "distribution_no_bin_available": "off",
                    "bulk_feeder_stalled": "off",
                    "c2_separation_needed": "bogus",
                    "unknown_incident": "automatic",
                }
            }
        )

        self.assertEqual("manual", config["incident_handling"]["exit_stuck"])
        self.assertEqual("off", config["incident_handling"]["distribution_chute_jam"])
        self.assertEqual("manual", config["incident_handling"]["distribution_servo_bus_offline"])
        self.assertEqual("off", config["incident_handling"]["distribution_no_bin_available"])
        self.assertNotIn("bulk_feeder_stalled", config["incident_handling"])
        self.assertNotIn("c2_separation_needed", config["incident_handling"])
        self.assertNotIn("unknown_incident", config["incident_handling"])
        self.assertNotIn("classification_exit_release", config["incident_handling"])
        self.assertTrue(incidentHandlingOff("distribution_chute_jam"))
        self.assertTrue(incidentHandlingOff("distribution_no_bin_available"))
        self.assertFalse(incidentHandlingAutomatic("exit_stuck"))

        config = setDashboardConfig({"incident_handling": {"classification_exit_stuck": "off"}})

        self.assertEqual("off", config["incident_handling"]["exit_stuck"])
        self.assertTrue(incidentHandlingOff("exit_stuck"))
        self.assertTrue(incidentHandlingOff("classification_exit_release"))
        self.assertTrue(incidentHandlingOff("channel_exit_stuck"))
        self.assertTrue(incidentHandlingOff("classification_exit_stuck"))

        config = setDashboardConfig({"incident_handling": {"exit_stuck": "automatic"}})

        self.assertEqual("automatic", config["incident_handling"]["exit_stuck"])
        self.assertTrue(incidentHandlingAutomatic("exit_stuck"))


if __name__ == "__main__":
    unittest.main()
