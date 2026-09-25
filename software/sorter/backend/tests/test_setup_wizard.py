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
        self._old_local_state_db = os.environ.get("LOCAL_STATE_DB_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        tmp_path = Path(self._tmpdir.name)
        self.machine_params_path = tmp_path / "machine_params.toml"
        self.local_state_db_path = tmp_path / "local_state.sqlite"
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.machine_params_path)
        os.environ["LOCAL_STATE_DB_PATH"] = str(self.local_state_db_path)

    def tearDown(self) -> None:
        if self._old_machine_params is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old_machine_params

        if self._old_local_state_db is None:
            os.environ.pop("LOCAL_STATE_DB_PATH", None)
        else:
            os.environ["LOCAL_STATE_DB_PATH"] = self._old_local_state_db

        self._tmpdir.cleanup()

    def test_modes_report_what_the_machine_runs_when_the_toml_names_none(self) -> None:
        from irl.config import DEFAULT_CLASSIFICATION_CHANNEL_MODE, DEFAULT_FEEDER_MODE

        self.machine_params_path.write_text('[cameras]\nlayout = "default"\n', encoding="utf-8")
        classification = setup.get_classification_channel_mode()
        feeder = setup.get_feeder_subsystem_mode()
        self.assertEqual(classification["mode"], DEFAULT_CLASSIFICATION_CHANNEL_MODE.value)
        self.assertEqual(classification["default"], DEFAULT_CLASSIFICATION_CHANNEL_MODE.value)
        self.assertEqual(feeder["mode"], DEFAULT_FEEDER_MODE.value)
        self.assertEqual(feeder["default"], DEFAULT_FEEDER_MODE.value)

    def test_split_feeder_is_the_layout_when_the_toml_names_none(self) -> None:
        from irl.config import mkIRLConfig

        no_boards = {
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
        cases = {
            # What SorterOS's first boot wrote until 2026-09-25, then since.
            "[cameras]\nfeeder = -1\nclassification_top = -1\nclassification_bottom = -1\n": "split_feeder",
            "[cameras]\n": "split_feeder",
            "": "split_feeder",
            '[cameras]\nlayout = "default"\nfeeder = 0\n': "default",
        }
        for toml, layout in cases.items():
            with self.subTest(toml=toml):
                self.machine_params_path.write_text(toml, encoding="utf-8")
                with (
                    patch("server.routers.setup._discover_control_board_summary", return_value=no_boards),
                    patch("server.routers.setup.getMachineNickname", return_value=None),
                    patch("server.routers.setup.shared_state.hardware_state", "standby"),
                    patch("server.routers.setup.shared_state.hardware_error", None),
                    patch("server.routers.setup.shared_state.hardware_homing_step", None),
                    patch("server.routers.setup.shared_state.getActiveIRL", return_value=None),
                ):
                    summary = setup.get_setup_wizard_summary()
                self.assertEqual(layout, summary["discovery"]["recommended_camera_layout"])
                self.assertEqual(layout, cameras.get_camera_config()["layout"])
                self.assertEqual(layout, mkIRLConfig().camera_layout)

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
        # On the classification-channel default the carousel logical stepper
        # is surfaced as c_channel_4. Either label is acceptable.
        carousel_entry = by_name.get("carousel") or by_name.get("c_channel_4")
        self.assertIsNotNone(carousel_entry)
        self.assertTrue(carousel_entry["inverted"])

    def test_feeding_mode_defaults_to_auto_channels(self) -> None:
        response = setup.get_feeding_mode()

        self.assertEqual("auto_channels", response["mode"])
        self.assertEqual("classification_channel", response["machine_setup"]["key"])
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
        self.assertEqual("manual_carousel", summary["config"]["machine_setup"]["key"])

    def test_machine_setup_defaults_to_classification_channel(self) -> None:
        response = setup.get_machine_setup()

        self.assertEqual("classification_channel", response["setup"])
        self.assertEqual("classification_channel", response["machine_setup"]["key"])
        self.assertTrue(response["requires_rehome"])

    def test_machine_setup_roundtrip_is_reflected_in_setup_summary(self) -> None:
        setup.set_machine_setup(
            setup.MachineSetupPayload(setup="classification_channel")
        )

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

        self.assertEqual("classification_channel", summary["config"]["machine_setup"]["key"])
        self.assertEqual("auto_channels", summary["config"]["feeding"]["mode"])

    def test_feeding_mode_auto_preserves_classification_channel_setup(self) -> None:
        setup.set_machine_setup(
            setup.MachineSetupPayload(setup="classification_channel")
        )

        response = setup.set_feeding_mode(
            setup.FeedingModePayload(mode="auto_channels")
        )

        self.assertEqual("auto_channels", response["mode"])
        self.assertEqual("classification_channel", response["machine_setup"]["key"])

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

            machine_setup_response = client.post(
                "/api/machine-setup",
                json={"setup": "classification_channel"},
            )
            self.assertEqual(200, machine_setup_response.status_code)
            self.assertEqual("classification_channel", machine_setup_response.json()["setup"])

            summary_response = client.get("/api/setup-wizard")
            self.assertEqual(200, summary_response.status_code)
            self.assertEqual(
                "split_feeder",
                summary_response.json()["config"]["camera_assignments"]["layout"],
            )
            self.assertEqual(
                "classification_channel",
                summary_response.json()["config"]["machine_setup"]["key"],
            )

    def test_setup_is_needed_only_by_a_machine_never_set_up(self) -> None:
        cases = [
            (None, "", True),
            (None, "[cameras]\nfeeder = -1\nclassification_top = -1\nclassification_bottom = -1\n", True),
            ("Sorting Bench A", "", False),
            (None, "[cameras]\nc_channel_2 = 0\n", False),
            (None, '[cameras]\nlayout = "default"\nfeeder = "usb-cam"\n', False),
        ]
        for nickname, toml, needed in cases:
            with self.subTest(nickname=nickname, toml=toml):
                self.machine_params_path.write_text(toml, encoding="utf-8")
                with patch("server.routers.setup.getMachineNickname", return_value=nickname):
                    self.assertEqual(setup.get_setup_wizard_needed(), {"needed": needed})

    def test_discovery_says_when_a_blank_board_waits_in_its_bootloader(self) -> None:
        for boards, present, expected in [([], True, True), ([], False, False)]:
            with self.subTest(present=present):
                with (
                    patch("server.routers.setup.bootloaderPresent", return_value=present),
                    patch("server.routers.setup._enumerate_usb_devices", return_value=[]),
                    patch("server.routers.setup.shared_state.getActiveIRL", return_value=None),
                ):
                    payload = setup._build_discovery_payload(
                        board_summaries=boards,
                        mcu_ports=[],
                        source="fresh",
                        issue_messages=["No MCU buses found."],
                    )
                self.assertIs(payload["bootloader_board"], expected)

    def test_simultaneous_requests_share_one_board_scan(self) -> None:
        import threading
        import time as _time

        calls: list[int] = []

        def slow_scan(gc):
            calls.append(1)
            _time.sleep(0.3)
            return {"boards": [{"port": "/dev/ttyACM0"}], "source": "scan"}

        setup._last_scan = None
        results: list[dict] = []
        with (
            patch("server.routers.setup._scan_control_boards", side_effect=slow_scan),
            patch("server.routers.setup.shared_state.getActiveIRL", return_value=None),
            patch("server.routers.setup.shared_state.hardware_worker_thread", None),
            patch("server.routers.setup.shared_state.hardware_state", "standby"),
            patch("server.routers.setup.shared_state.gc_ref", object()),
        ):
            threads = [threading.Thread(target=lambda: results.append(setup._discover_control_board_summary())) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        setup._last_scan = None
        self.assertEqual(1, len(calls))
        self.assertEqual(3, len([r for r in results if r["boards"]]))

if __name__ == "__main__":
    unittest.main()
