import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import app
from server.routers import camera_picture_settings, cameras, setup


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

    def test_channel_cameras_ignore_removed_layout_and_chamber_settings(self) -> None:
        from irl.config import mkIRLConfig

        for role in ("carousel", "classification_channel"):
            with self.subTest(role=role):
                self.machine_params_path.write_text(
                    '[cameras]\nlayout = "default"\nfeeder = 8\nclassification_top = 9\n'
                    f'c_channel_2 = 0\nc_channel_3 = 1\n{role} = 2\n'
                    f'[camera_capture_modes.{role}]\nwidth = 1920\nheight = 1080\nfps = 30\n',
                    encoding="utf-8",
                )
                config = mkIRLConfig()
                self.assertEqual(0, config.c_channel_2_camera.device_index)
                self.assertEqual(1, config.c_channel_3_camera.device_index)
                self.assertEqual(2, config.carousel_camera.device_index)
                self.assertEqual(1920, config.carousel_camera.width)
                self.assertFalse(hasattr(config, "feeder_camera"))
                self.assertFalse(hasattr(config, "classification_camera_top"))
                self.assertFalse(hasattr(config, "camera_layout"))
                self.assertEqual(
                    {"c_channel_2": 0, "c_channel_3": 1, "classification_channel": 2, "carousel": 2},
                    cameras.get_camera_config(),
                )

    def test_classification_channel_settings_accept_both_aliases_independent_of_source(self) -> None:
        from irl.config import mkIRLConfig

        for source_role in ("carousel", "classification_channel"):
            for settings_role in ("carousel", "classification_channel"):
                with self.subTest(source_role=source_role, settings_role=settings_role):
                    self.machine_params_path.write_text(
                        f'[cameras]\n{source_role} = 2\n'
                        f'[camera_capture_modes.{settings_role}]\nwidth = 1280\nheight = 720\nfps = 60\n'
                        f'[camera_picture_settings.{settings_role}]\nrotation = 90\n'
                        f'[camera_device_settings.{settings_role}]\nbrightness = 7\n',
                        encoding="utf-8",
                    )
                    camera = mkIRLConfig().carousel_camera
                    self.assertEqual(1280, camera.width)
                    self.assertEqual(90, camera.picture_settings.rotation)
                    self.assertEqual(7, camera.device_settings["brightness"])
                    self.assertEqual(90, camera_picture_settings.get_camera_picture_settings("carousel")["settings"]["rotation"])
                    self.assertEqual(90, camera_picture_settings.get_camera_picture_settings("classification_channel")["settings"]["rotation"])
                    with self.machine_params_path.open("a", encoding="utf-8") as file:
                        other_role = "carousel" if settings_role == "classification_channel" else "classification_channel"
                        file.write(f'[camera_picture_settings.{other_role}]\nrotation = 180\n')
                    expected = 90 if settings_role == "classification_channel" else 180
                    self.assertEqual(expected, mkIRLConfig().carousel_camera.picture_settings.rotation)

    def test_invalid_sources_resolve_identically_in_camera_config_and_runtime(self) -> None:
        from irl.config import mkIRLConfig

        for value in ('-1', '""', '"none"', '"-1"', 'false'):
            with self.subTest(value=value):
                self.machine_params_path.write_text(
                    f'[cameras]\nc_channel_2 = {value}\nc_channel_3 = {value}\nclassification_channel = {value}\n',
                    encoding="utf-8",
                )
                config = mkIRLConfig()
                self.assertIsNone(config.c_channel_2_camera)
                self.assertIsNone(config.c_channel_3_camera)
                self.assertIsNone(config.carousel_camera)
                self.assertTrue(all(value is None for value in cameras.get_camera_config().values()))

    def test_camera_assignment_preserves_classification_channel_alias(self) -> None:
        self.machine_params_path.write_text('[cameras]\ncarousel = 2\n', encoding="utf-8")
        with (
            patch.object(cameras.shared_state, "vision_manager", None),
            patch.object(cameras.shared_state, "gc_ref", None),
        ):
            for role, value in (("classification_channel", 3), ("carousel", 4), ("classification_channel", None)):
                with self.subTest(role=role, value=value):
                    response = cameras.assign_cameras(cameras.CameraAssignment(**{role: value}))
                    self.assertEqual(value, response["assignment"]["classification_channel"])
                    self.assertEqual(value, response["assignment"]["carousel"])
                    self.assertEqual(response["assignment"], cameras.get_camera_config())

    def test_camera_assignment_rejects_removed_roles_and_layout(self) -> None:
        app = FastAPI()
        app.include_router(cameras.router)
        with TestClient(app) as client:
            for field in ("feeder", "classification_top", "classification_bottom", "layout"):
                with self.subTest(field=field):
                    response = client.post("/api/cameras/assign", json={field: 0})
                    self.assertEqual(422, response.status_code)
            self.assertEqual(404, client.post("/api/cameras/layout", json={"layout": "default"}).status_code)

    def test_camera_readiness_requires_all_three_channel_sources(self) -> None:
        for role in ("c_channel_2", "c_channel_3", "classification_channel"):
            for value in (None, -1, "", "-1", "none"):
                with self.subTest(role=role, value=value):
                    assignments = {"c_channel_2": 0, "c_channel_3": 1, "classification_channel": 2}
                    assignments[role] = value
                    normalized = setup._camera_assignments_from_config({"cameras": assignments})
                    self.assertFalse(setup._camera_assignments_complete(normalized))
        for role in ("carousel", "classification_channel"):
            assignments = setup._camera_assignments_from_config({
                "cameras": {"c_channel_2": 0, "c_channel_3": 1, role: "http://camera/video"}
            })
            self.assertTrue(setup._camera_assignments_complete(assignments))

    def test_discovery_requires_classification_channel_stepper(self) -> None:
        for overrides, expected in (({}, "carousel"), ({"carousel": "distribution_aux_1"}, "distribution_aux_1")):
            with (
                self.subTest(overrides=overrides),
                patch.object(setup, "loadStepperBindingOverrides", return_value=overrides),
                patch.object(setup, "_enumerate_usb_devices", return_value=[]),
                patch.object(setup.shared_state, "gc_ref", SimpleNamespace(machine_id="test-machine")),
                patch.object(setup.shared_state, "getActiveIRL", return_value=None),
            ):
                discovery = setup._build_discovery_payload(
                    board_summaries=[{
                        "logical_steppers": ["chute_stepper", "c_channel_1_rotor", "c_channel_2_rotor", "c_channel_3_rotor"],
                        "servo_count": 0,
                    }],
                    mcu_ports=[],
                    source="scan",
                    issue_messages=[],
                )
                self.assertEqual([expected], discovery["missing_required_steppers"])
                with patch.object(setup, "_discover_control_board_summary", return_value=discovery):
                    summary = setup.get_setup_wizard_summary()
                self.assertFalse(summary["readiness"]["boards_detected"])

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
        self.assertTrue(by_name["c_channel_4"]["inverted"])

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
            summary_response = client.get("/api/setup-wizard")
            self.assertEqual(200, summary_response.status_code)
            summary = summary_response.json()
            self.assertEqual(set(cameras.CAMERA_SETUP_ROLES), set(summary["config"]["camera_assignments"]))
            self.assertNotIn("camera_layout_selected", summary["readiness"])
            self.assertNotIn("recommended_camera_layout", summary["discovery"])
            self.assertEqual(404, client.post("/api/setup-wizard/camera-layout", json={"layout": "split_feeder"}).status_code)

    def test_setup_is_needed_only_by_a_machine_never_set_up(self) -> None:
        cases = [
            (None, "", True),
            (None, "[cameras]\nfeeder = -1\nclassification_top = -1\nclassification_bottom = -1\n", True),
            ("Sorting Bench A", "", False),
            (None, "[cameras]\nc_channel_2 = 0\n", False),
            (None, '[cameras]\nlayout = "default"\nfeeder = "usb-cam"\n', True),
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
