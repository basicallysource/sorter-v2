import unittest
from types import SimpleNamespace
from unittest.mock import patch

from irl.config import mkCameraConfig, parseCameraDeviceSettings
from server import shared_state
from server.routers import cameras
from vision.camera import (
    CaptureThread,
    _apply_linux_v4l2_device_settings,
    _bool_from_capture_value,
    _capture_failure_backoff_s,
    _is_linux_video_device_available,
    _is_macos_camera_index_available,
    _resolve_linux_video_index,
    _try_v4l2ctl_describe,
    _try_v4l2ctl_get_number,
    probe_camera_device_controls,
)


class CameraDeviceControlsTests(unittest.TestCase):
    def setUp(self) -> None:
        shared_state.camera_device_preview_overrides.clear()

    def test_macos_probe_reports_live_settings_without_applying_saved_values(self) -> None:
        controls = [{"key": "brightness", "kind": "number"}]
        live_settings = {"brightness": 12.0}

        with patch("vision.camera._describe_macos_uvc_controls", return_value=(controls, live_settings)):
            with patch("vision.camera._apply_macos_uvc_controls", side_effect=AssertionError("should not apply")):
                described_controls, current_settings = probe_camera_device_controls(
                    1,
                    {"brightness": 99.0},
                )

        self.assertEqual(controls, described_controls)
        self.assertEqual(live_settings, current_settings)

    def test_probe_can_skip_secondary_capture_open(self) -> None:
        with patch("vision.camera.platform.system", return_value="Darwin"):
            with patch("vision.camera._describe_macos_uvc_controls", return_value=([], {})):
                with patch("vision.camera._open_capture_source", side_effect=AssertionError("should not open")):
                    described_controls, current_settings = probe_camera_device_controls(
                        1,
                        {"brightness": 21.0},
                        allow_open_capture=False,
                    )

        self.assertEqual([], described_controls)
        self.assertEqual({"brightness": 21.0}, current_settings)

    def test_linux_video_device_presence_checks_dev_node(self) -> None:
        with patch("vision.camera.platform.system", return_value="Linux"):
            with patch("vision.camera.Path.exists", return_value=False):
                self.assertFalse(_is_linux_video_device_available(7))
            with patch("vision.camera.Path.exists", return_value=True):
                self.assertTrue(_is_linux_video_device_available(5))

    def test_linux_video_device_presence_ignores_non_linux_and_urls(self) -> None:
        with patch("vision.camera.platform.system", return_value="Darwin"):
            self.assertTrue(_is_linux_video_device_available(7))
        with patch("vision.camera.platform.system", return_value="Linux"):
            self.assertTrue(_is_linux_video_device_available("rtsp://camera"))
            self.assertTrue(_is_linux_video_device_available(None))

    def test_linux_video_source_resolver_maps_legacy_even_slots_to_index0_nodes(self) -> None:
        with patch("vision.camera.Path.exists", return_value=False):
            with patch("vision.camera._linux_index0_video_indices", return_value=[1, 5, 7]):
                self.assertEqual(1, _resolve_linux_video_index(0))
                self.assertEqual(5, _resolve_linux_video_index(2))
                self.assertEqual(7, _resolve_linux_video_index(4))
                self.assertIsNone(_resolve_linux_video_index(6))

    def test_linux_video_source_resolver_prefers_index0_for_legacy_even_slots(self) -> None:
        with patch("vision.camera.Path.exists", return_value=True):
            with patch("vision.camera._linux_index0_video_indices", return_value=[0, 3, 6]):
                self.assertEqual(0, _resolve_linux_video_index(0))
                self.assertEqual(3, _resolve_linux_video_index(2))
                self.assertEqual(6, _resolve_linux_video_index(4))

    def test_capture_thread_describe_uses_safe_probe_when_capture_not_ready(self) -> None:
        capture = CaptureThread("classification_top", mkCameraConfig(device_index=1))

        with patch("vision.camera.probe_camera_device_controls", return_value=([], {"brightness": 8.0})) as probe:
            described_controls, current_settings = capture.describeDeviceControls()

        probe.assert_called_once_with(1, {}, allow_open_capture=False)
        self.assertEqual([], described_controls)
        self.assertEqual({"brightness": 8.0}, current_settings)

    def test_route_prefers_camera_service_for_live_usb_controls(self) -> None:
        service = SimpleNamespace(
            inspect_device_controls_for_role=lambda role, source, saved_settings: (
                [{"key": "brightness", "kind": "number"}],
                {"brightness": 17.0},
            )
        )
        raw_config = {
            "cameras": {
                "classification_top": 1,
            },
            "camera_device_settings": {
                "classification_top": {"brightness": 9.0},
            },
        }

        with patch.object(cameras.shared_state, "camera_service", service):
            with patch("server.routers.cameras._read_machine_params_config", return_value=(None, raw_config)):
                response = cameras.get_camera_device_settings("classification_top")

        self.assertTrue(response["ok"])
        self.assertEqual("usb-opencv", response["provider"])
        self.assertTrue(response["supported"])
        self.assertEqual(17.0, response["settings"]["brightness"])
        self.assertEqual("brightness", response["controls"][0]["key"])

    def test_route_returns_saved_usb_settings_when_camera_service_unavailable(self) -> None:
        raw_config = {
            "cameras": {
                "classification_top": 1,
            },
            "camera_device_settings": {
                "classification_top": {"brightness": 9.0},
            },
        }

        with patch.object(cameras.shared_state, "camera_service", None):
            with patch("server.routers.cameras._read_machine_params_config", return_value=(None, raw_config)):
                response = cameras.get_camera_device_settings("classification_top")

        self.assertTrue(response["ok"])
        self.assertFalse(response["supported"])
        self.assertEqual(9.0, response["settings"]["brightness"])

    def test_preview_route_applies_usb_settings_via_camera_service(self) -> None:
        service = SimpleNamespace(
            set_device_settings_for_role=lambda role, settings, persist=False: {"brightness": 23.0}
        )
        raw_config = {
            "cameras": {
                "classification_top": 1,
            },
        }

        with patch.object(cameras.shared_state, "camera_service", service):
            with patch("server.routers.cameras._read_machine_params_config", return_value=(None, raw_config)):
                response = cameras.preview_camera_device_settings("classification_top", {"brightness": 30})

        self.assertTrue(response["ok"])
        self.assertTrue(response["applied_live"])
        self.assertEqual(23.0, response["settings"]["brightness"])

    def test_reset_defaults_clears_usb_settings_and_applies_driver_defaults(self) -> None:
        applied_calls = []
        cleared_roles = []
        raw_config = {
            "cameras": {
                "classification_top": 1,
            },
            "camera_device_settings": {
                "classification_top": {"exposure": 123.0, "auto_exposure": False},
            },
        }

        def set_device_settings_for_role(role, settings, persist=False):
            applied_calls.append((role, settings, persist))
            return dict(settings)

        service = SimpleNamespace(
            inspect_device_controls_for_role=lambda role, source, saved_settings: (
                [
                    {"key": "auto_exposure", "kind": "menu", "default": 3.0},
                    {"key": "auto_white_balance", "kind": "boolean", "default": True},
                    {"key": "brightness", "kind": "number", "default": 0.0},
                    {"key": "privacy", "kind": "boolean", "default": False, "readonly": True},
                    {"key": "focus_reset", "kind": "button", "default": 1.0},
                ],
                {"auto_exposure": False, "exposure": 123.0},
            ),
            set_device_settings_for_role=set_device_settings_for_role,
            clear_persisted_device_settings_for_role=lambda role: cleared_roles.append(role),
        )

        with patch.object(cameras.shared_state, "camera_service", service):
            with patch("server.routers.cameras._read_machine_params_config", return_value=("machine.toml", raw_config)):
                with patch("server.routers.cameras._write_machine_params_config") as write_config:
                    response = cameras.reset_camera_device_settings_to_defaults("classification_top")

        self.assertTrue(response["ok"])
        self.assertEqual({"auto_exposure": 3.0, "auto_white_balance": True, "brightness": 0.0}, response["settings"])
        self.assertEqual(
            [
                (
                    "classification_top",
                    {"auto_exposure": 3.0, "auto_white_balance": True, "brightness": 0.0},
                    False,
                )
            ],
            applied_calls,
        )
        self.assertEqual(["classification_top"], cleared_roles)
        self.assertNotIn("classification_top", raw_config["camera_device_settings"])
        write_config.assert_called_once()

    def test_capture_mode_save_prefers_mjpg_when_pixel_format_omitted(self) -> None:
        raw_config = {
            "cameras": {
                "classification_top": 1,
            },
        }

        modes = [
            {"width": 1280, "height": 720, "fps": 30, "fourcc": "YUYV"},
            {"width": 1280, "height": 720, "fps": 30, "fourcc": "MJPG"},
        ]

        with patch("server.routers.cameras._read_machine_params_config", return_value=("machine.toml", raw_config)):
            with patch("server.routers.cameras._capture_modes_for_source", return_value=(modes, "v4l2")):
                with patch("server.routers.cameras._write_machine_params_config") as write_config:
                    response = cameras.save_camera_capture_mode(
                        "classification_top",
                        cameras.CaptureModePayload(width=1280, height=720, fps=30),
                    )

        self.assertTrue(response["ok"])
        self.assertEqual("MJPG", raw_config["camera_capture_modes"]["classification_top"]["fourcc"])
        write_config.assert_called_once()

    def test_capture_mode_save_accepts_high_res_classification_mode(self) -> None:
        raw_config = {
            "cameras": {
                "classification_top": 1,
            },
        }
        modes = [
            {"width": 1280, "height": 720, "fps": 30, "fourcc": "MJPG"},
            {"width": 3840, "height": 2160, "fps": 30, "fourcc": "MJPG"},
        ]

        with patch("server.routers.cameras._read_machine_params_config", return_value=("machine.toml", raw_config)):
            with patch("server.routers.cameras._capture_modes_for_source", return_value=(modes, "v4l2")):
                with patch("server.routers.cameras._write_machine_params_config") as write_config:
                    response = cameras.save_camera_capture_mode(
                        "classification_top",
                        cameras.CaptureModePayload(width=3840, height=2160, fps=30),
                    )

        self.assertTrue(response["ok"])
        self.assertEqual(
            {"width": 3840, "height": 2160, "fps": 30, "fourcc": "MJPG"},
            raw_config["camera_capture_modes"]["classification_top"],
        )
        write_config.assert_called_once()

    def test_capture_mode_for_role_preserves_saved_high_res_mode(self) -> None:
        raw_config = {
            "camera_capture_modes": {
                "classification_top": {"width": 3840, "height": 2160, "fps": 30, "fourcc": "MJPG"}
            }
        }

        mode = cameras._capture_mode_for_role(raw_config, "classification_top", 1)

        self.assertEqual({"width": 3840, "height": 2160, "fps": 30, "fourcc": "MJPG"}, mode)

    def test_capture_failure_backoff_caps(self) -> None:
        self.assertEqual(0.0, _capture_failure_backoff_s(0))
        self.assertEqual(0.25, _capture_failure_backoff_s(1))
        self.assertEqual(0.5, _capture_failure_backoff_s(2))
        self.assertEqual(4.0, _capture_failure_backoff_s(99))

    def test_macos_camera_index_availability_uses_registry(self) -> None:
        cameras_list = [SimpleNamespace(index=0), SimpleNamespace(index=3)]
        with patch("vision.camera.platform.system", return_value="Darwin"):
            with patch("vision.camera._refresh_macos_cameras", return_value=cameras_list):
                self.assertTrue(_is_macos_camera_index_available(3))
                self.assertFalse(_is_macos_camera_index_available(2))

    def test_linux_auto_exposure_v4l2_enum_readback(self) -> None:
        with patch("vision.camera.platform.system", return_value="Linux"):
            self.assertFalse(_bool_from_capture_value("auto_exposure", 1.0))
            self.assertTrue(_bool_from_capture_value("auto_exposure", 3.0))
            self.assertFalse(_bool_from_capture_value("auto_exposure", 0.25))
            self.assertTrue(_bool_from_capture_value("auto_exposure", 0.75))

    def test_linux_v4l2_numeric_readback(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="exposure_time_absolute: 200\n")
        with patch("vision.camera.subprocess.run", return_value=completed):
            self.assertEqual(200.0, _try_v4l2ctl_get_number(4, "exposure"))

    def test_linux_v4l2_describe_parses_numeric_ranges(self) -> None:
        stdout = """
User Controls

                     brightness 0x00980900 (int)    : min=-64 max=64 step=1 default=0 value=0
      white_balance_temperature 0x0098091a (int)    : min=2800 max=6500 step=10 default=4600 value=2800 flags=inactive

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3 (Aperture Priority Mode)
         exposure_time_absolute 0x009a0902 (int)    : min=0 max=10000 step=1 default=166 value=200 flags=inactive
"""
        completed = SimpleNamespace(returncode=0, stdout=stdout)
        with patch("vision.camera.subprocess.run", return_value=completed):
            described = _try_v4l2ctl_describe(4)

        self.assertEqual(-64.0, described["brightness"]["min"])
        self.assertEqual(64.0, described["brightness"]["max"])
        self.assertEqual(1.0, described["brightness"]["step"])
        self.assertEqual(200.0, described["exposure"]["value"])
        self.assertTrue(bool(described["exposure"]["inactive"]))
        self.assertTrue(bool(described["white_balance_temperature"]["inactive"]))
        self.assertEqual("menu", described["auto_exposure"]["kind"])
        self.assertEqual(3.0, described["auto_exposure"]["value"])

    def test_linux_v4l2_describe_parses_menus_unknown_controls_and_flags(self) -> None:
        stdout = """
User Controls

              power_line_frequency 0x00980918 (menu)   : min=0 max=2 default=1 value=2
                                0: Disabled
                                1: 50 Hz
                                2: 60 Hz

Image Processing Controls

                   vendor_magic 0x0a340001 (int)    : min=0 max=10 step=1 default=4 value=7 flags=read-only
"""
        completed = SimpleNamespace(returncode=0, stdout=stdout)
        with patch("vision.camera.subprocess.run", return_value=completed):
            described = _try_v4l2ctl_describe(4)

        self.assertEqual("menu", described["power_line_frequency"]["kind"])
        self.assertEqual(
            [
                {"value": 0.0, "label": "Disabled"},
                {"value": 1.0, "label": "50 Hz"},
                {"value": 2.0, "label": "60 Hz"},
            ],
            described["power_line_frequency"]["options"],
        )
        self.assertEqual("vendor_magic", described["vendor_magic"]["key"])
        self.assertEqual("Vendor Magic", described["vendor_magic"]["label"])
        self.assertEqual("Image Processing Controls", described["vendor_magic"]["category"])
        self.assertTrue(described["vendor_magic"]["readonly"])
        self.assertTrue(described["vendor_magic"]["disabled"])

    def test_linux_v4l2_apply_sets_unknown_controls_and_skips_readonly_inactive(self) -> None:
        before = """
User Controls

                     vendor_magic 0x0a340001 (int)    : min=0 max=10 step=1 default=4 value=4
                    read_only_gain 0x0a340002 (int)    : min=0 max=10 step=1 default=1 value=1 flags=read-only

Camera Controls

                  auto_exposure 0x009a0901 (menu)   : min=0 max=3 default=3 value=3
         exposure_time_absolute 0x009a0902 (int)    : min=0 max=10000 step=1 default=166 value=200 flags=inactive
"""
        after = before.replace("value=4", "value=7", 1)
        calls: list[list[str]] = []
        applied = False

        def fake_run(args, **kwargs):
            nonlocal applied
            calls.append(list(args))
            if "-L" in args:
                return SimpleNamespace(returncode=0, stdout=after if applied else before)
            if "-c" in args:
                applied = True
                return SimpleNamespace(returncode=0, stdout="")
            return SimpleNamespace(returncode=1, stdout="")

        with patch("vision.camera.subprocess.run", side_effect=fake_run):
            result = _apply_linux_v4l2_device_settings(
                {
                    "auto_exposure": True,
                    "exposure": 500.0,
                    "read_only_gain": 5.0,
                    "vendor_magic": 7.0,
                },
                4,
            )

        set_args = next(call for call in calls if "-c" in call)
        self.assertIn("auto_exposure=3", set_args)
        self.assertIn("vendor_magic=7", set_args)
        self.assertNotIn("exposure_time_absolute=500", set_args)
        self.assertNotIn("read_only_gain=5", set_args)
        self.assertEqual(7.0, result["vendor_magic"])

    def test_camera_device_settings_parser_keeps_dynamic_safe_keys(self) -> None:
        self.assertEqual(
            {"vendor_magic": 7.0, "privacy": True},
            parseCameraDeviceSettings(
                {
                    "vendor_magic": 7,
                    "privacy": True,
                    "bad-key": 4,
                }
            ),
        )
        self.assertEqual(
            {"auto_exposure": 3.0},
            parseCameraDeviceSettings({"auto_exposure": 3, "exposure": 200}),
        )
        self.assertEqual(
            {"auto_exposure": 1.0, "exposure": 200.0},
            parseCameraDeviceSettings({"auto_exposure": 1, "exposure": 200}),
        )


if __name__ == "__main__":
    unittest.main()
