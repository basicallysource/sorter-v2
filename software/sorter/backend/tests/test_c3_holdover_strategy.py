import unittest

from subsystems.feeder.analysis import ChannelAction
from subsystems.feeder.strategies import C3HoldoverStrategy


class C3HoldoverStrategyTests(unittest.TestCase):
    def test_recent_precise_pulse_holds_next_normal_as_precise(self) -> None:
        strategy = C3HoldoverStrategy(holdover_ms=2000)

        first = strategy.apply(ChannelAction.PULSE_PRECISE, now_mono=1.0)
        second = strategy.apply(ChannelAction.PULSE_NORMAL, now_mono=2.0)
        third = strategy.apply(ChannelAction.PULSE_NORMAL, now_mono=4.5)

        self.assertEqual(ChannelAction.PULSE_PRECISE, first)
        self.assertEqual(ChannelAction.PULSE_PRECISE, second)
        self.assertEqual(ChannelAction.PULSE_NORMAL, third)


if __name__ == "__main__":
    unittest.main()
