import unittest

from defs.known_object import ClassificationStatus
from irl.config import ClassificationChannelConfig
from subsystems.classification_channel.zone_manager import (
    TrackAngularExtent,
    ZoneManager,
)


class ZoneManagerTests(unittest.TestCase):
    def test_register_and_track_zone_updates_size_class(self) -> None:
        manager = ZoneManager(ClassificationChannelConfig())
        manager.register_provisional_piece(
            piece_uuid="piece-1",
            track_global_id=7,
            classification_status=ClassificationStatus.pending,
            now_mono=0.0,
        )

        for now_mono in (1.0, 2.0, 3.0):
            zones = manager.update_from_tracks(
                track_extents=[
                    TrackAngularExtent(
                        global_id=7,
                        center_deg=32.0,
                        half_width_deg=5.5,
                        last_seen_ts=now_mono,
                        hit_count=5,
                    )
                ],
                pieces_by_track_id={7: ("piece-1", ClassificationStatus.pending)},
                now_mono=now_mono,
            )

        self.assertEqual(1, len(zones))
        self.assertEqual("S", zones[0].size_class)
        self.assertFalse(zones[0].hard_collision)

    def test_hard_collision_marks_both_zones(self) -> None:
        manager = ZoneManager(ClassificationChannelConfig())
        manager.register_provisional_piece(
            piece_uuid="a",
            track_global_id=1,
            classification_status=ClassificationStatus.pending,
            now_mono=0.0,
        )
        manager.register_provisional_piece(
            piece_uuid="b",
            track_global_id=2,
            classification_status=ClassificationStatus.pending,
            now_mono=0.0,
        )

        zones = manager.update_from_tracks(
            track_extents=[
                TrackAngularExtent(1, 180.0, 8.0, 1.0, 4),
                TrackAngularExtent(2, 192.0, 8.0, 1.0, 4),
            ],
            pieces_by_track_id={
                1: ("a", ClassificationStatus.pending),
                2: ("b", ClassificationStatus.pending),
            },
            now_mono=1.0,
        )

        self.assertEqual(1, len(manager.hard_collisions()))
        self.assertTrue(all(zone.hard_collision for zone in zones))

    def test_arc_clear_respects_intake_guard(self) -> None:
        config = ClassificationChannelConfig()
        manager = ZoneManager(config)
        manager.register_provisional_piece(
            piece_uuid="piece-1",
            track_global_id=4,
            classification_status=ClassificationStatus.pending,
            now_mono=0.0,
        )

        self.assertFalse(
            manager.is_arc_clear(
                center_deg=config.intake_angle_deg,
                body_half_width_deg=config.intake_body_half_width_deg,
                hard_guard_deg=config.intake_guard_deg,
            )
        )

    def test_center_window_is_less_conservative_than_body_window(self) -> None:
        manager = ZoneManager(ClassificationChannelConfig())
        manager.register_provisional_piece(
            piece_uuid="piece-1",
            track_global_id=4,
            classification_status=ClassificationStatus.pending,
            now_mono=0.0,
        )

        manager.update_from_tracks(
            track_extents=[
                TrackAngularExtent(
                    global_id=4,
                    center_deg=42.0,
                    half_width_deg=8.0,
                    last_seen_ts=1.0,
                    hit_count=5,
                )
            ],
            pieces_by_track_id={4: ("piece-1", ClassificationStatus.pending)},
            now_mono=1.0,
        )

        self.assertEqual([], manager.pieces_centered_in_window(center_deg=30.0, tolerance_deg=6.0))
        self.assertEqual(
            ["piece-1"],
            manager.pieces_in_body_window(center_deg=30.0, tolerance_deg=6.0),
        )


if __name__ == "__main__":
    unittest.main()
