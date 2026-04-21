import unittest
from types import SimpleNamespace

from defs.known_object import ClassificationStatus
from irl.config import ClassificationChannelConfig
from subsystems.feeder.feeding import (
    _classification_channel_admission_blocked,
    _estimate_piece_count_for_channel,
)
from subsystems.classification_channel.zone_manager import ZoneManager


class FeederPieceCountTests(unittest.TestCase):
    def test_estimate_uses_detection_count_when_tracker_is_cold(self) -> None:
        detections = [
            SimpleNamespace(channel_id=2),
            SimpleNamespace(channel_id=2),
            SimpleNamespace(channel_id=3),
        ]

        count = _estimate_piece_count_for_channel(
            detections,
            channel_id=2,
            track_count=0,
        )

        self.assertEqual(2, count)

    def test_estimate_keeps_higher_track_count_when_it_is_more_stable(self) -> None:
        detections = [SimpleNamespace(channel_id=2)]

        count = _estimate_piece_count_for_channel(
            detections,
            channel_id=2,
            track_count=4,
        )

        self.assertEqual(4, count)

    def test_classification_channel_blocks_when_detection_already_sees_one_piece(self) -> None:
        detections = [SimpleNamespace(channel_id=4)]

        blocked = _classification_channel_admission_blocked(
            detections,
            track_count=0,
            transport_piece_count=0,
        )

        self.assertTrue(blocked)

    def test_classification_channel_blocks_when_transport_still_holds_piece(self) -> None:
        blocked = _classification_channel_admission_blocked(
            [],
            track_count=0,
            transport_piece_count=1,
        )

        self.assertTrue(blocked)

    def test_classification_channel_allows_admission_when_empty(self) -> None:
        blocked = _classification_channel_admission_blocked(
            [],
            track_count=0,
            transport_piece_count=0,
        )

        self.assertFalse(blocked)

    def test_dynamic_zone_manager_blocks_when_intake_arc_is_occupied(self) -> None:
        config = ClassificationChannelConfig()
        config.max_zones = 2
        zone_manager = ZoneManager(config)
        zone_manager.register_provisional_piece(
            piece_uuid="piece-1",
            track_global_id=3,
            classification_status=ClassificationStatus.pending,
            now_mono=0.0,
        )

        blocked = _classification_channel_admission_blocked(
            [],
            track_count=1,
            transport_piece_count=1,
            zone_manager=zone_manager,
            config=config,
        )

        self.assertTrue(blocked)

    def test_dynamic_zone_manager_ignores_raw_detection_ghosts_when_empty(self) -> None:
        config = ClassificationChannelConfig()
        config.max_zones = 2
        zone_manager = ZoneManager(config)

        blocked = _classification_channel_admission_blocked(
            [SimpleNamespace(channel_id=4), SimpleNamespace(channel_id=4)],
            track_count=2,
            transport_piece_count=0,
            zone_manager=zone_manager,
            config=config,
        )

        self.assertFalse(blocked)


if __name__ == "__main__":
    unittest.main()
