import unittest
from types import SimpleNamespace

from subsystems.bus import ChuteMotion, StationGate, StationId, TickBus
from subsystems.shared_variables import SharedVariables


class SharedVariablesBusShimTests(unittest.TestCase):
    def test_flag_updates_publish_bus_facts_when_enabled(self) -> None:
        bus = TickBus()
        shared = SharedVariables(
            gc=SimpleNamespace(use_channel_bus=True),
            bus=bus,
        )
        bus.begin_tick(now_mono=1.0)

        shared.classification_ready = True
        shared.distribution_ready = False
        shared.chute_move_in_progress = True

        messages = bus.events()

        self.assertEqual(3, len(messages))
        self.assertIsInstance(messages[0], StationGate)
        self.assertEqual(StationId.CLASSIFICATION, messages[0].station)
        self.assertTrue(messages[0].open)
        self.assertIsNone(messages[0].reason)
        self.assertIsInstance(messages[1], StationGate)
        self.assertEqual(StationId.DISTRIBUTION, messages[1].station)
        self.assertFalse(messages[1].open)
        self.assertEqual("compat_flag_false", messages[1].reason)
        self.assertIsInstance(messages[2], ChuteMotion)
        self.assertTrue(messages[2].in_progress)
        self.assertIsNone(messages[2].target_bin)

    def test_flag_updates_do_not_publish_when_disabled(self) -> None:
        bus = TickBus()
        shared = SharedVariables(
            gc=SimpleNamespace(use_channel_bus=False),
            bus=bus,
        )
        bus.begin_tick(now_mono=1.0)

        shared.classification_ready = True
        shared.distribution_ready = False
        shared.chute_move_in_progress = True

        self.assertEqual(tuple(), bus.events())


if __name__ == "__main__":
    unittest.main()
