import math
import unittest

import numpy as np

from vision.overlays.classification_zones import ClassificationChannelZoneOverlay


class ClassificationChannelZoneOverlayTests(unittest.TestCase):
    def _sample_point(
        self,
        center: tuple[int, int],
        radius: float,
        angle_deg: float,
    ) -> tuple[int, int]:
        angle_rad = math.radians(angle_deg)
        return (
            int(round(center[0] + radius * math.cos(angle_rad))),
            int(round(center[1] + radius * math.sin(angle_rad))),
        )

    def test_overlay_renders_zone_as_annulus_sector(self) -> None:
        center = (120, 120)
        payload = {
            "geometry": {
                "center_x": center[0],
                "center_y": center[1],
                "r_inner": 40,
                "r_outer": 100,
            },
            "intake_angle_deg": 300.0,
            "drop_angle_deg": 180.0,
            "drop_tolerance_deg": 10.0,
            "point_of_no_return_deg": 18.0,
            "zones": [
                {
                    "piece_uuid": "piece-1",
                    "center_deg": 30.0,
                    "size_class": "M",
                    "body_half_width_deg": 12.0,
                    "soft_guard_deg": 14.0,
                    "hard_guard_deg": 18.0,
                    "classification_status": "pending",
                    "stale": False,
                    "hard_collision": False,
                }
            ],
        }
        overlay = ClassificationChannelZoneOverlay(lambda: payload)
        frame = np.zeros((240, 240, 3), dtype=np.uint8)

        annotated = overlay.annotate(frame)

        body_point = self._sample_point(center, 72.0, 30.0)
        hole_point = center
        self.assertGreater(int(annotated[body_point[1], body_point[0]].sum()), 0)
        self.assertEqual(0, int(annotated[hole_point[1], hole_point[0]].sum()))

    def test_overlay_handles_wraparound_sector(self) -> None:
        center = (100, 100)
        payload = {
            "geometry": {
                "center_x": center[0],
                "center_y": center[1],
                "r_inner": 30,
                "r_outer": 80,
            },
            "zones": [
                {
                    "piece_uuid": "piece-2",
                    "center_deg": 355.0,
                    "size_class": "S",
                    "body_half_width_deg": 8.0,
                    "soft_guard_deg": 10.0,
                    "hard_guard_deg": 14.0,
                    "classification_status": "classified",
                    "stale": False,
                    "hard_collision": False,
                }
            ],
        }
        overlay = ClassificationChannelZoneOverlay(lambda: payload)
        frame = np.zeros((220, 220, 3), dtype=np.uint8)

        annotated = overlay.annotate(frame)

        near_zero_deg = self._sample_point(center, 58.0, 2.0)
        self.assertGreater(int(annotated[near_zero_deg[1], near_zero_deg[0]].sum()), 0)


if __name__ == "__main__":
    unittest.main()
