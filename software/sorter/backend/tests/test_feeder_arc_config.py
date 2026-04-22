import unittest

from subsystems.feeder.analysis import parseSavedChannelArcZones


class FeederArcConfigTests(unittest.TestCase):
    def test_classification_channel_arc_config_allows_missing_wait_zone(self) -> None:
        zones = parseSavedChannelArcZones(
            "classification_channel",
            {"classification_channel": 12.0},
            {
                "classification_channel": {
                    "center": [960, 540],
                    "inner_radius": 220,
                    "outer_radius": 410,
                    "drop_zone": {"start_angle": 44, "end_angle": 118},
                    "exit_zone": {"start_angle": 314, "end_angle": 350},
                }
            },
        )

        self.assertIsNotNone(zones)
        assert zones is not None
        self.assertEqual((960.0, 540.0), zones.center)
        self.assertEqual(220.0, zones.inner_radius)
        self.assertEqual(410.0, zones.outer_radius)
        self.assertEqual(44.0, zones.drop_start_angle)
        self.assertEqual(118.0, zones.drop_end_angle)
        self.assertIsNone(zones.wait_start_angle)
        self.assertIsNone(zones.wait_end_angle)
        self.assertEqual(314.0, zones.exit_start_angle)
        self.assertEqual(350.0, zones.exit_end_angle)


if __name__ == "__main__":
    unittest.main()
