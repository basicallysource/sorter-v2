"""Tests for the system-wide color correction kill switch.

The switch is a hardcoded constant rather than config, so these lock in that it
actually gates the pipeline in both directions — off means an enabled profile is
a no-op, on means the same profile still corrects.
"""

import unittest
from unittest import mock

import numpy as np

from irl.config import mkCameraColorProfile
from vision import camera as camera_module

# Deliberately far from identity so a single applied pass is unmistakable.
_WRECKING_PROFILE = mkCameraColorProfile(
    enabled=True,
    matrix=[[0.2, 0.9, 0.1], [0.4, 0.3, 0.7], [0.8, 0.1, 0.5]],
    bias=[0.3, -0.2, 0.4],
)


class ColorCorrectionKillSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.frame = np.full((8, 8, 3), 120, dtype=np.uint8)

    def test_disabled_switch_passes_frame_through_untouched(self) -> None:
        with mock.patch.object(camera_module, "COLOR_CORRECTION_ENABLED", False):
            result = camera_module.apply_camera_color_profile(self.frame, _WRECKING_PROFILE)

        self.assertTrue(np.array_equal(result, self.frame))
        # Same object, not a copy — the disabled path must cost nothing per frame.
        self.assertIs(result, self.frame)

    def test_enabled_switch_still_applies_an_enabled_profile(self) -> None:
        with mock.patch.object(camera_module, "COLOR_CORRECTION_ENABLED", True):
            result = camera_module.apply_camera_color_profile(self.frame, _WRECKING_PROFILE)

        self.assertFalse(np.array_equal(result, self.frame))

    def test_enabled_switch_leaves_a_disabled_profile_alone(self) -> None:
        disabled_profile = mkCameraColorProfile(enabled=False, matrix=_WRECKING_PROFILE.matrix)
        with mock.patch.object(camera_module, "COLOR_CORRECTION_ENABLED", True):
            result = camera_module.apply_camera_color_profile(self.frame, disabled_profile)

        self.assertTrue(np.array_equal(result, self.frame))


if __name__ == "__main__":
    unittest.main()
