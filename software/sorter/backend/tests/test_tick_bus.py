import unittest

from runtime_stats import RuntimeStatsCollector
from subsystems.bus import (
    ChuteMotion,
    PieceDelivered,
    PieceRequest,
    StationGate,
    StationId,
    TickBus,
)


class TickBusTests(unittest.TestCase):
    def test_begin_tick_clears_only_per_tick_events(self) -> None:
        bus = TickBus(recent_limit=5)
        bus.begin_tick(now_mono=10.0)
        bus.publish(
            PieceRequest(
                source=StationId.CLASSIFICATION,
                target=StationId.C3,
                sent_at_mono=10.1,
            )
        )
        bus.publish(
            StationGate(
                station=StationId.DISTRIBUTION,
                open=True,
                reason=None,
                updated_at_mono=10.2,
            )
        )

        self.assertEqual(2, len(bus.events()))
        self.assertTrue(bus.is_station_open(StationId.DISTRIBUTION))

        bus.begin_tick(now_mono=11.0)

        self.assertEqual(tuple(), bus.events())
        self.assertTrue(bus.is_station_open(StationId.DISTRIBUTION))
        self.assertEqual(2, len(bus.recent()))

    def test_recent_messages_and_publish_counts_are_serializable(self) -> None:
        bus = TickBus(recent_limit=2)
        bus.begin_tick(now_mono=20.0)
        bus.publish(
            StationGate(
                station=StationId.CLASSIFICATION,
                open=False,
                reason="piece_in_hood",
                updated_at_mono=20.1,
            )
        )
        bus.publish(
            ChuteMotion(
                in_progress=True,
                target_bin={"layer": 1, "bin": 2},
                updated_at_mono=20.2,
            )
        )
        bus.publish(
            PieceDelivered(
                source=StationId.C3,
                target=StationId.CLASSIFICATION,
                delivered_at_mono=20.3,
            )
        )

        recent = bus.recent()
        self.assertEqual(2, len(recent))
        self.assertEqual("ChuteMotion", recent[0]["type"])
        self.assertEqual("PieceDelivered", recent[1]["type"])
        self.assertEqual(
            {"ChuteMotion": 1, "PieceDelivered": 1, "StationGate": 1},
            bus.publish_counts(),
        )

    def test_runtime_stats_snapshot_includes_bus_data(self) -> None:
        collector = RuntimeStatsCollector()
        bus = TickBus(recent_limit=3)
        collector.setBusProvider(bus)

        bus.begin_tick(now_mono=30.0)
        bus.publish(
            PieceRequest(
                source=StationId.CLASSIFICATION,
                target=StationId.C3,
                sent_at_mono=30.1,
            )
        )

        snapshot = collector.snapshot()

        self.assertEqual("PieceRequest", snapshot["bus_recent"][0]["type"])
        self.assertEqual(1, snapshot["bus_publish_counts"]["PieceRequest"])


if __name__ == "__main__":
    unittest.main()
