import unittest
from types import SimpleNamespace

from subsystems.bus import StationId, TickBus
from subsystems.shared_variables import SharedVariables


class StationFlagMigrationTests(unittest.TestCase):
    def test_precise_gate_and_piece_messages_publish_to_bus(self) -> None:
        bus = TickBus()
        shared = SharedVariables(
            gc=SimpleNamespace(use_channel_bus=True),
            bus=bus,
        )
        bus.begin_tick(now_mono=1.0)

        shared.set_classification_gate(True, reason=None)
        shared.publish_piece_request(
            source=StationId.CLASSIFICATION,
            target=StationId.C3,
            sent_at_mono=1.1,
        )
        shared.set_distribution_gate(False, reason="piece_in_flight")
        shared.publish_piece_delivered(
            source=StationId.CLASSIFICATION,
            target=StationId.DISTRIBUTION,
            delivered_at_mono=1.2,
        )

        recent_types = [item["type"] for item in bus.recent()]

        self.assertEqual(
            ["StationGate", "PieceRequest", "StationGate", "PieceDelivered"],
            recent_types,
        )
        self.assertFalse(shared.get_distribution_ready())
        self.assertTrue(shared.get_classification_ready())


if __name__ == "__main__":
    unittest.main()
