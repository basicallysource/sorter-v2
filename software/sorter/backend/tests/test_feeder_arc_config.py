import math
import unittest

from subsystems.feeder.analysis import (
    channelArcCropPolygon,
    channelArcOuterPolygon,
    parseSavedChannelArcZones,
    sectionsForAngleRange,
    zoneSectionsForChannel,
)


def _polar_tuple(center: tuple[float, float], radius: float, angle_deg: float) -> tuple[int, int]:
    angle = math.radians(angle_deg)
    return (
        int(round(center[0] + radius * math.cos(angle))),
        int(round(center[1] + radius * math.sin(angle))),
    )


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
        self.assertEqual(410.0, zones.exit_outer_radius)
        self.assertEqual(44.0, zones.drop_start_angle)
        self.assertEqual(118.0, zones.drop_end_angle)
        self.assertIsNone(zones.wait_start_angle)
        self.assertIsNone(zones.wait_end_angle)
        self.assertEqual(314.0, zones.exit_start_angle)
        self.assertEqual(350.0, zones.exit_end_angle)

    def test_precise_zone_is_unioned_into_exit_sections(self) -> None:
        arc = {
            "classification_channel": {
                "center": [500, 400],
                "inner_radius": 120,
                "outer_radius": 260,
                "drop_zone": {"start_angle": 44, "end_angle": 118},
                "exit_zone": {"start_angle": 314, "end_angle": 350},
                "precise_zone": {"start_angle": 290, "end_angle": 314},
            }
        }
        angles = {"classification_channel": 0.0}
        zones = parseSavedChannelArcZones("classification_channel", angles, arc)
        assert zones is not None
        self.assertEqual(290.0, zones.precise_start_angle)
        self.assertEqual(314.0, zones.precise_end_angle)

        _drop, exit_sections = zoneSectionsForChannel(4, 0.0, zones)
        expected = sectionsForAngleRange(314, 350, 0.0) | sectionsForAngleRange(290, 314, 0.0)
        self.assertEqual(expected, exit_sections)

    def test_missing_precise_zone_leaves_exit_sections_unchanged(self) -> None:
        arc = {
            "classification_channel": {
                "center": [500, 400],
                "inner_radius": 120,
                "outer_radius": 260,
                "drop_zone": {"start_angle": 44, "end_angle": 118},
                "exit_zone": {"start_angle": 314, "end_angle": 350},
            }
        }
        zones = parseSavedChannelArcZones("classification_channel", {"classification_channel": 0.0}, arc)
        assert zones is not None
        self.assertIsNone(zones.precise_start_angle)
        _drop, exit_sections = zoneSectionsForChannel(4, 0.0, zones)
        self.assertEqual(sectionsForAngleRange(314, 350, 0.0), exit_sections)

    def test_zero_width_precise_zone_unions_to_nothing(self) -> None:
        arc = {
            "classification_channel": {
                "center": [500, 400],
                "inner_radius": 120,
                "outer_radius": 260,
                "drop_zone": {"start_angle": 44, "end_angle": 118},
                "exit_zone": {"start_angle": 314, "end_angle": 350},
                "precise_zone": {"start_angle": 314, "end_angle": 314},
            }
        }
        zones = parseSavedChannelArcZones("classification_channel", {"classification_channel": 0.0}, arc)
        assert zones is not None
        _drop, exit_sections = zoneSectionsForChannel(4, 0.0, zones)
        self.assertEqual(sectionsForAngleRange(314, 350, 0.0), exit_sections)

    def test_exit_zone_can_use_separate_outer_radius(self) -> None:
        zones = parseSavedChannelArcZones(
            "classification_channel",
            {"classification_channel": 0.0},
            {
                "classification_channel": {
                    "center": [500, 400],
                    "inner_radius": 120,
                    "outer_radius": 260,
                    "exit_outer_radius": 210,
                    "drop_zone": {"start_angle": 44, "end_angle": 118},
                    "exit_zone": {"start_angle": 314, "end_angle": 350},
                }
            },
        )

        self.assertIsNotNone(zones)
        assert zones is not None
        self.assertEqual(210.0, zones.exit_outer_radius)

        polygon = channelArcOuterPolygon(zones, segment_count=24)
        center = zones.center
        exit_mid_angle = math.radians(332.0)
        exit_mid = (
            center[0] + zones.exit_outer_radius * math.cos(exit_mid_angle),
            center[1] + zones.exit_outer_radius * math.sin(exit_mid_angle),
        )
        nearest_exit_point = min(
            polygon,
            key=lambda pt: math.hypot(float(pt[0]) - exit_mid[0], float(pt[1]) - exit_mid[1]),
        )
        self.assertLess(
            math.hypot(float(nearest_exit_point[0]) - center[0], float(nearest_exit_point[1]) - center[1]),
            zones.outer_radius - 20,
        )

        polygon_points = [tuple(int(v) for v in point) for point in polygon.tolist()]
        start_outer = _polar_tuple(center, zones.outer_radius, zones.exit_start_angle)
        start_exit = _polar_tuple(center, zones.exit_outer_radius, zones.exit_start_angle)
        end_exit = _polar_tuple(center, zones.exit_outer_radius, zones.exit_end_angle)
        end_outer = _polar_tuple(center, zones.outer_radius, zones.exit_end_angle)

        start_idx = polygon_points.index(start_outer)
        self.assertEqual(start_exit, polygon_points[start_idx + 1])

        end_idx = polygon_points.index(end_exit)
        self.assertEqual(end_outer, polygon_points[end_idx + 1])

    def test_chord_arc_config_uses_outer_angles_for_runtime_sections(self) -> None:
        zones = parseSavedChannelArcZones(
            "classification_channel",
            {"classification_channel": 0.0},
            {
                "classification_channel": {
                    "center": [500, 400],
                    "inner_radius": 120,
                    "outer_radius": 260,
                    "drop_zone": {
                        "start_angle": 44,
                        "start_inner_angle": 35,
                        "start_outer_angle": 44,
                        "end_angle": 118,
                        "end_inner_angle": 108,
                        "end_outer_angle": 118,
                    },
                    "exit_zone": {
                        "start_angle": 314,
                        "start_inner_angle": 300,
                        "start_outer_angle": 314,
                        "end_angle": 350,
                        "end_inner_angle": 342,
                        "end_outer_angle": 350,
                    },
                }
            },
        )

        self.assertIsNotNone(zones)
        assert zones is not None
        self.assertEqual(44.0, zones.drop_start_angle)
        self.assertEqual(118.0, zones.drop_end_angle)
        self.assertEqual(314.0, zones.exit_start_angle)
        self.assertEqual(350.0, zones.exit_end_angle)
        self.assertEqual(35.0, zones.drop_start_inner_angle)
        self.assertEqual(342.0, zones.exit_end_inner_angle)

    def test_crop_polygon_excludes_exit_end_to_drop_start_opening(self) -> None:
        zones = parseSavedChannelArcZones(
            "classification_channel",
            {"classification_channel": 0.0},
            {
                "classification_channel": {
                    "center": [500, 400],
                    "inner_radius": 120,
                    "outer_radius": 260,
                    "exit_outer_radius": 210,
                    "drop_zone": {
                        "start_angle": 44,
                        "start_inner_angle": 35,
                        "start_outer_angle": 44,
                        "end_angle": 118,
                        "end_inner_angle": 108,
                        "end_outer_angle": 118,
                    },
                    "exit_zone": {
                        "start_angle": 314,
                        "start_inner_angle": 300,
                        "start_outer_angle": 314,
                        "end_angle": 350,
                        "end_inner_angle": 342,
                        "end_outer_angle": 350,
                    },
                }
            },
        )

        self.assertIsNotNone(zones)
        assert zones is not None
        polygon_points = [tuple(int(v) for v in point) for point in channelArcCropPolygon(zones).tolist()]
        gap_mid_outer = _polar_tuple(zones.center, zones.outer_radius, 17)
        drop_start_outer = _polar_tuple(zones.center, zones.outer_radius, 44)
        drop_start_inner = _polar_tuple(zones.center, zones.inner_radius, 35)
        exit_end_outer = _polar_tuple(zones.center, zones.exit_outer_radius, 350)
        exit_end_inner = _polar_tuple(zones.center, zones.inner_radius, 342)
        exit_end_full_outer = _polar_tuple(zones.center, zones.outer_radius, 350)

        self.assertNotIn(gap_mid_outer, polygon_points)
        self.assertNotIn(exit_end_full_outer, polygon_points)
        self.assertIn(drop_start_outer, polygon_points)
        self.assertIn(drop_start_inner, polygon_points)
        self.assertIn(exit_end_outer, polygon_points)
        self.assertIn(exit_end_inner, polygon_points)


if __name__ == "__main__":
    unittest.main()
