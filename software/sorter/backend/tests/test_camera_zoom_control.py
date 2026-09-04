import unittest

from vision import camera


class ZoomControlTests(unittest.TestCase):
    def test_zoom_is_a_known_usb_control(self):
        keys = {spec["key"] for spec in camera._usb_camera_control_specs()}
        self.assertIn("zoom", keys)
        ctrl, fmt = camera._LINUX_V4L2CTL_CONTROL_MAP["zoom"]
        self.assertEqual("zoom_absolute", ctrl)
        self.assertEqual("26", fmt(26.4))


if __name__ == "__main__":
    unittest.main()
