import unittest
from types import SimpleNamespace

from subsystems.feeder.feeding import (
    _classification_channel_admission_blocked,
    _estimate_piece_count_for_channel,
)


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


if __name__ == "__main__":
    unittest.main()
