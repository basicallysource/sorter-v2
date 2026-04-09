import unittest

import cv2
import numpy as np

from vision.mog2_channel_detector import BOOTSTRAP_FRAMES, Mog2ChannelDetector


class Mog2ChannelDetectorTests(unittest.TestCase):
    def test_static_frame_does_not_report_full_channel_motion_during_bootstrap(self) -> None:
        shape = (120, 120)
        polygon = np.array([[20, 20], [100, 20], [100, 100], [20, 100]], dtype=np.int32)
        mask = np.zeros(shape, dtype=np.uint8)
        cv2.fillPoly(mask, [polygon], 255)
        detector = Mog2ChannelDetector(
            channel_polygons={"second_channel": polygon},
            channel_masks={"second_channel": mask},
            channel_angles={"second": 0.0},
            channel_inner_polygons=None,
            channel_zone_sections={"second": {"drop": set(), "exit": set()}},
            is_channel_rotating=lambda _name: False,
        )

        frame = np.zeros((shape[0], shape[1], 3), dtype=np.uint8)
        for _ in range(BOOTSTRAP_FRAMES + 3):
            detections = detector.detect(frame)

        self.assertEqual([], detections)

        changed = frame.copy()
        changed[40:70, 40:70] = 255
        detections = detector.detect(changed)
        self.assertGreaterEqual(len(detections), 1)


if __name__ == "__main__":
    unittest.main()
