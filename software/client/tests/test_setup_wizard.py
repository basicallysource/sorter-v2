import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from server.api import app
from server.routers import cameras, setup


class SetupWizardConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_machine_params = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._old_bin_layout = os.environ.get("BIN_LAYOUT_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmpdir.name)
        self.machine_params_path = tmp_path / "machine_params.toml"
        self.bin_layout_path = tmp_path / "bin_layout.json"
        self.bin_layout_path.write_text(
            json.dumps(
                {
                    "layers": [
                        {
                            "enabled": True,
                            "sections": [["medium", "medium"], ["medium", "medium"]],
                        },
                        {
                            "enabled": True,
                            "sections": [["medium", "medium"], ["medium", "medium"]],
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)
        os.environ["BIN_LAYOUT_PATH"] = str(self.bin_layout_path)

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params

        if self._old_bin_layout is None:
            os.environ.pop("BIN_LAYOUT_PATH", None)
        else:
            os.environ["BIN_LAYOUT_PATH"] = self._old_bin_layout

        self._tmpdir.cleanup()

    def test_camera_layout_roundtrip_supports_default(self) -> None:
        response = cameras.save_camera_layout(cameras.CameraLayoutPayload(layout="default"))

        self.assertEqual("default", response["layout"])
        current = cameras.get_camera_config()
        self.assertEqual("default", current["layout"])
        self.assertIsNone(current["feeder"])

    def test_assign_cameras_supports_default_feeder_role(self) -> None:
        cameras.save_camera_layout(cameras.CameraLayoutPayload(layout="default"))

        response = cameras.assign_cameras(
            cameras.CameraAssignment(
                feeder=2,
                classification_top="http://127.0.0.1:8080/video",
            )
        )

        self.assertTrue(response["ok"])
        self.assertEqual("default", response["assignment"]["layout"])
        self.assertEqual(2, response["assignment"]["feeder"])
        self.assertEqual(
            "http://127.0.0.1:8080/video",
            response["assignment"]["classification_top"],
        )

    def test_setup_stepper_direction_persists_and_reads_back(self) -> None:
        response = setup.set_stepper_direction(
            "carousel",
            setup.StepperDirectionPayload(inverted=True),
        )

        self.assertTrue(response["ok"])
        self.assertEqual("carousel", response["stepper"])
        self.assertTrue(response["inverted"])

        directions = setup.get_stepper_directions()
        by_name = {
            entry["name"]: entry
            for entry in directions["steppers"]
        }
        self.assertIn("carousel", by_name)
        self.assertTrue(by_name["carousel"]["inverted"])

    def test_feeding_mode_defaults_to_auto_channels(self) -> None:
        response = setup.get_feeding_mode()

        self.assertEqual("auto_channels", response["mode"])
        self.assertTrue(response["requires_rehome"])

    def test_feeding_mode_roundtrip_is_reflected_in_setup_summary(self) -> None:
        setup.set_feeding_mode(setup.FeedingModePayload(mode="manual_carousel"))

        discovery_payload = {
            "scanned_at_ms": 0,
            "source": "scan",
            "mcu_ports": [],
            "boards": [],
            "roles": {"feeder": True, "distribution": True},
            "missing_required_steppers": [],
            "pca_available": False,
            "waveshare_ports": [],
            "issues": [],
        }

        with (
            patch("server.routers.setup._discover_control_board_summary", return_value=discovery_payload),
            patch("server.routers.setup.getMachineNickname", return_value="Bench A"),
            patch("server.routers.setup.shared_state.hardware_state", "standby"),
            patch("server.routers.setup.shared_state.hardware_error", None),
            patch("server.routers.setup.shared_state.hardware_homing_step", None),
            patch("server.routers.setup.shared_state.getActiveIRL", return_value=None),
        ):
            summary = setup.get_setup_wizard_summary()

        self.assertEqual("manual_carousel", summary["config"]["feeding"]["mode"])

    def test_setup_summary_requires_explicit_camera_layout_selection(self) -> None:
        discovery_payload = {
            "scanned_at_ms": 0,
            "source": "scan",
            "mcu_ports": [],
            "boards": [
                {
                    "family": "sorter",
                    "role": "distribution",
                    "device_name": "Distribution Board",
                    "port": "/dev/ttyUSB0",
                    "address": 1,
                    "logical_steppers": ["c_channel_2_rotor", "c_channel_3_rotor", "carousel"],
                    "servo_count": 0,
                    "input_aliases": {},
                }
            ],
            "roles": {"feeder": True, "distribution": True},
            "missing_required_steppers": [],
            "pca_available": False,
            "waveshare_ports": [],
            "issues": [],
        }

        with (
            patch("server.routers.setup._discover_control_board_summary", return_value=discovery_payload),
            patch("server.routers.setup.getMachineNickname", return_value=None),
            patch("server.routers.setup.shared_state.hardware_state", "standby"),
            patch("server.routers.setup.shared_state.hardware_error", None),
            patch("server.routers.setup.shared_state.hardware_homing_step", None),
            patch("server.routers.setup.shared_state.getActiveIRL", return_value=None),
        ):
            summary = setup.get_setup_wizard_summary()

        self.assertIsNone(summary["config"]["camera_assignments"]["layout"])
        self.assertFalse(summary["readiness"]["camera_layout_selected"])
        self.assertEqual("split_feeder", summary["discovery"]["recommended_camera_layout"])

    def test_setup_routes_respond_via_fastapi_app(self) -> None:
        discovery_payload = {
            "scanned_at_ms": 0,
            "source": "unavailable",
            "mcu_ports": [],
            "boards": [],
            "roles": {"feeder": False, "distribution": False},
            "missing_required_steppers": [],
            "pca_available": False,
            "waveshare_ports": [],
            "issues": [],
        }

        with (
            patch("server.routers.setup._discover_control_board_summary", return_value=discovery_payload),
            patch("server.routers.setup.shared_state.hardware_state", "standby"),
            patch("server.routers.setup.shared_state.hardware_error", None),
            patch("server.routers.setup.shared_state.hardware_homing_step", None),
            patch("server.routers.setup.shared_state.getActiveIRL", return_value=None),
            TestClient(app) as client,
        ):
            layout_response = client.post(
                "/api/setup-wizard/camera-layout",
                json={"layout": "split_feeder"},
            )
            self.assertEqual(200, layout_response.status_code)
            self.assertEqual("split_feeder", layout_response.json()["layout"])

            feeding_response = client.post(
                "/api/feeding-mode",
                json={"mode": "manual_carousel"},
            )
            self.assertEqual(200, feeding_response.status_code)
            self.assertEqual("manual_carousel", feeding_response.json()["mode"])

            summary_response = client.get("/api/setup-wizard")
            self.assertEqual(200, summary_response.status_code)
            self.assertEqual(
                "split_feeder",
                summary_response.json()["config"]["camera_assignments"]["layout"],
            )
            self.assertEqual(
                "manual_carousel",
                summary_response.json()["config"]["feeding"]["mode"],
            )


if __name__ == "__main__":
    unittest.main()
