import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tomllib

from irl.config import mkCameraConfig
from server.routers import cameras
from vision import camera_service
from vision.camera_modes import default_capture_mode


def _modes(fourcc: str, entries: list[tuple[int, int, int]]) -> list[dict]:
    return [{"width": w, "height": h, "fps": f, "fourcc": fourcc} for w, h, f in entries]


# What the two camera models on a kit machine report (v4l2-ctl --list-formats-ext).
FOUR_K_CAMERA = _modes("MJPG", [(1280, 720, 60), (1280, 720, 30), (1920, 1080, 60), (2560, 1440, 30), (3840, 2160, 30)]) + _modes(
    "YUYV", [(640, 360, 30), (1920, 1080, 3), (3840, 2160, 1)]
)
HD_CAMERA = _modes("YUYV", [(1280, 720, 10), (640, 480, 30)]) + _modes("MJPG", [(640, 480, 30), (960, 540, 30), (1280, 720, 30)])


class DefaultCaptureModeTests(unittest.TestCase):
    def test_a_4k_camera_runs_4k_mjpeg(self) -> None:
        self.assertEqual(
            {"width": 3840, "height": 2160, "fps": 30, "fourcc": "MJPG"}, default_capture_mode(FOUR_K_CAMERA)
        )

    def test_other_cameras_run_720p_mjpeg(self) -> None:
        self.assertEqual({"width": 1280, "height": 720, "fps": 30, "fourcc": "MJPG"}, default_capture_mode(HD_CAMERA))

    def test_a_small_camera_runs_its_largest_mjpeg_mode_under_720p(self) -> None:
        small = _modes("MJPG", [(640, 480, 30), (800, 600, 15)])
        self.assertEqual({"width": 800, "height": 600, "fps": 15, "fourcc": "MJPG"}, default_capture_mode(small))

    def test_no_mjpeg_means_no_default(self) -> None:
        self.assertIsNone(default_capture_mode(_modes("YUYV", [(1280, 720, 10)])))


class CameraServiceDefaultTests(unittest.TestCase):
    def test_an_unconfigured_usb_camera_gets_its_default(self) -> None:
        config = mkCameraConfig(device_index=2)
        with patch.object(camera_service, "list_v4l2_modes", return_value=FOUR_K_CAMERA):
            self.assertTrue(camera_service._apply_default_capture_mode(config))
        self.assertEqual((3840, 2160, 30, "MJPG"), (config.width, config.height, config.fps, config.fourcc))

    def test_a_saved_mode_is_left_alone(self) -> None:
        config = mkCameraConfig(device_index=2, width=1920, height=1080, fps=60)
        config.capture_mode_saved = True
        with patch.object(camera_service, "list_v4l2_modes", return_value=FOUR_K_CAMERA):
            self.assertFalse(camera_service._apply_default_capture_mode(config))
        self.assertEqual((1920, 1080, 60), (config.width, config.height, config.fps))


class CaptureModeRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("MACHINE_SPECIFIC_PARAMS_PATH")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self._tmpdir.name) / "machine.toml"
        os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = str(self.path)

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("MACHINE_SPECIFIC_PARAMS_PATH", None)
        else:
            os.environ["MACHINE_SPECIFIC_PARAMS_PATH"] = self._old
        self._tmpdir.cleanup()

    def _saved(self) -> dict:
        return tomllib.loads(self.path.read_text(encoding="utf-8"))

    def test_a_new_camera_on_a_role_drops_the_old_cameras_mode(self) -> None:
        self.path.write_text(
            '[cameras]\nlayout = "split_feeder"\nc_channel_2 = 0\nc_channel_3 = 4\n\n'
            "[camera_capture_modes.c_channel_2]\nwidth = 640\nheight = 480\nfps = 30\n\n"
            "[camera_capture_modes.c_channel_3]\nwidth = 960\nheight = 540\nfps = 30\n",
            encoding="utf-8",
        )
        with patch.object(cameras.shared_state, "vision_manager", None), patch.object(
            cameras.shared_state, "gc_ref", None
        ):
            cameras.assign_cameras(cameras.CameraAssignment(c_channel_2=2, c_channel_3=4))
        saved = self._saved()
        self.assertNotIn("c_channel_2", saved.get("camera_capture_modes", {}))
        self.assertEqual(960, saved["camera_capture_modes"]["c_channel_3"]["width"])

    def test_saving_a_resolution_picks_mjpeg_not_yuyv(self) -> None:
        self.path.write_text('[cameras]\nlayout = "split_feeder"\ncarousel = 2\n', encoding="utf-8")
        with patch.object(cameras, "_capture_modes_for_source", return_value=(list(reversed(FOUR_K_CAMERA)), "v4l2")), patch.object(
            cameras.shared_state, "camera_service", None
        ):
            response = cameras.save_camera_capture_mode(
                "carousel", cameras.CaptureModePayload(width=1920, height=1080)
            )
        self.assertEqual({"width": 1920, "height": 1080, "fps": 60, "fourcc": "MJPG"}, response["mode"])



class CameraListTests(unittest.TestCase):
    def test_linux_lists_cameras_from_their_formats_without_opening_them(self) -> None:
        by_index = {0: HD_CAMERA, 2: FOUR_K_CAMERA, 4: HD_CAMERA}
        with patch.object(cameras.platform, "system", return_value="Linux"), patch.object(
            cameras, "list_v4l2_modes", side_effect=lambda i: by_index.get(i, [])
        ), patch.object(cameras, "_active_camera_indices", return_value={}), patch.object(
            cameras, "_v4l2_camera_name", side_effect=lambda i: f"cam{i}"
        ), patch.object(cameras, "_probe_camera_index", side_effect=AssertionError("opened a camera")):
            listed = cameras._list_usb_cameras()
        self.assertEqual(
            [(0, 1280, 720), (2, 3840, 2160), (4, 1280, 720)],
            [(c["index"], c["width"], c["height"]) for c in listed],
        )

if __name__ == "__main__":
    unittest.main()
