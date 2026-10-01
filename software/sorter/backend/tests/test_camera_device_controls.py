import unittest
from types import SimpleNamespace
from unittest.mock import patch

from irl.config import mkCameraConfig
from server.routers import camera_device_settings
from vision.camera import (
    CaptureThread,
    _bool_from_capture_value,
    _capture_failure_backoff_s,
    _is_macos_camera_index_available,
    _try_v4l2ctl_describe,
    _try_v4l2ctl_get_number,
    probe_camera_device_controls,
)


class CameraDeviceControlsTests(unittest.TestCase):
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
        with patch("vision.camera._describe_macos_uvc_controls", return_value=([], {})):
            with patch("vision.camera._open_capture_source", side_effect=AssertionError("should not open")):
                described_controls, current_settings = probe_camera_device_controls(
                    1,
                    {"brightness": 21.0},
                    allow_open_capture=False,
                )

        self.assertEqual([], described_controls)
        self.assertEqual({"brightness": 21.0}, current_settings)

    def test_capture_thread_describe_uses_safe_probe_when_capture_not_ready(self) -> None:
        capture = CaptureThread("c_channel_2", mkCameraConfig(device_index=1))

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
                "c_channel_2": 1,
            },
            "camera_device_settings": {
                "c_channel_2": {"brightness": 9.0},
            },
        }

        with patch.object(camera_device_settings.shared_state, "camera_service", service):
            with patch.object(camera_device_settings.machine_toml, "read", return_value=raw_config):
                response = camera_device_settings.get_camera_device_settings("c_channel_2")

        self.assertTrue(response["ok"])
        self.assertEqual("usb-opencv", response["provider"])
        self.assertTrue(response["supported"])
        self.assertEqual(17.0, response["settings"]["brightness"])
        self.assertEqual("brightness", response["controls"][0]["key"])

    def test_route_returns_saved_usb_settings_when_camera_service_unavailable(self) -> None:
        raw_config = {
            "cameras": {
                "c_channel_2": 1,
            },
            "camera_device_settings": {
                "c_channel_2": {"brightness": 9.0},
            },
        }

        with patch.object(camera_device_settings.shared_state, "camera_service", None):
            with patch.object(camera_device_settings.machine_toml, "read", return_value=raw_config):
                response = camera_device_settings.get_camera_device_settings("c_channel_2")

        self.assertTrue(response["ok"])
        self.assertFalse(response["supported"])
        self.assertEqual(9.0, response["settings"]["brightness"])

    def test_preview_route_applies_usb_settings_via_camera_service(self) -> None:
        service = SimpleNamespace(
            set_device_settings_for_role=lambda role, settings, persist=False: {"brightness": 23.0}
        )
        raw_config = {
            "cameras": {
                "c_channel_2": 1,
            },
        }

        with patch.object(camera_device_settings.shared_state, "camera_service", service):
            with patch.object(camera_device_settings.machine_toml, "read", return_value=raw_config):
                response = camera_device_settings.preview_camera_device_settings("c_channel_2", {"brightness": 30})

        self.assertTrue(response["ok"])
        self.assertTrue(response["applied_live"])
        self.assertEqual(23.0, response["settings"]["brightness"])

    def test_reset_defaults_clears_usb_settings_and_applies_auto(self) -> None:
        applied_calls = []
        cleared_roles = []
        raw_config = {
            "cameras": {
                "c_channel_2": 1,
            },
            "camera_device_settings": {
                "c_channel_2": {"exposure": 123.0, "auto_exposure": False},
            },
        }

        def set_device_settings_for_role(role, settings, persist=False):
            applied_calls.append((role, settings, persist))
            return dict(settings)

        service = SimpleNamespace(
            inspect_device_controls_for_role=lambda role, source, saved_settings: (
                [
                    {"key": "auto_exposure", "kind": "boolean"},
                    {"key": "auto_white_balance", "kind": "boolean"},
                    {"key": "exposure", "kind": "number"},
                ],
                {"auto_exposure": False, "exposure": 123.0},
            ),
            set_device_settings_for_role=set_device_settings_for_role,
            clear_persisted_device_settings_for_role=lambda role: cleared_roles.append(role),
        )

        with patch.object(camera_device_settings.shared_state, "camera_service", service):
            with patch.object(camera_device_settings.machine_toml, "read", return_value=raw_config):
                with patch.object(camera_device_settings.machine_toml, "_write") as write_config:
                    response = camera_device_settings.reset_camera_device_settings_to_defaults("c_channel_2")

        self.assertTrue(response["ok"])
        self.assertEqual({"auto_exposure": True, "auto_white_balance": True}, response["settings"])
        self.assertEqual(
            [("c_channel_2", {"auto_exposure": True, "auto_white_balance": True}, False)],
            applied_calls,
        )
        self.assertEqual(["c_channel_2"], cleared_roles)
        self.assertNotIn("c_channel_2", raw_config["camera_device_settings"])
        write_config.assert_called_once()

    def test_c4_device_preview_save_and_reset_share_one_alias(self) -> None:
        raw_config = {
            "cameras": {"carousel": 1},
            "camera_device_settings": {"carousel": {"brightness": 2.0}},
        }
        service = SimpleNamespace(
            set_device_settings_for_role=lambda role, settings, persist=False: dict(settings),
            inspect_device_controls_for_role=lambda role, source, settings: (
                [{"key": "auto_exposure", "kind": "boolean"}], {}
            ),
            clear_persisted_device_settings_for_role=lambda role: None,
        )
        with (
            patch.object(camera_device_settings.shared_state, "camera_service", service),
            patch.object(camera_device_settings.machine_toml, "read", return_value=raw_config),
            patch.object(camera_device_settings.machine_toml, "_write"),
        ):
            camera_device_settings.preview_camera_device_settings("classification_channel", {"brightness": 3})
            camera_device_settings.preview_camera_device_settings("carousel", {"brightness": 4})
            camera_device_settings.save_camera_device_settings("carousel", {"brightness": 5})
            self.assertEqual(
                {"classification_channel": {"brightness": 5.0}},
                raw_config["camera_device_settings"],
            )
            camera_device_settings.reset_camera_device_settings_to_defaults("carousel")
            self.assertEqual({}, raw_config["camera_device_settings"])

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


if __name__ == "__main__":
    unittest.main()
