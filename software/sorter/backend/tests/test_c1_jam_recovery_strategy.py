import unittest
from types import SimpleNamespace

from subsystems.feeder.strategies import C1JamRecoveryStrategy


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass


class _Profiler:
    def hit(self, *args, **kwargs) -> None:
        pass


class _RuntimeStats:
    def observePulse(self, *args, **kwargs) -> None:
        pass


class _Stepper:
    def __init__(self) -> None:
        self._name = "c1"
        self.moves: list[tuple[float, int]] = []

    def move_degrees_blocking(self, degrees: float, timeout_ms: int) -> bool:
        self.moves.append((degrees, timeout_ms))
        return True


class C1JamRecoveryStrategyTests(unittest.TestCase):
    def test_strategy_runs_shake_then_push_and_tracks_attempts(self) -> None:
        busy_until: dict[str, float] = {}
        strategy = C1JamRecoveryStrategy(
            stepper=_Stepper(),
            logger=_Logger(),
            profiler=_Profiler(),
            runtime_stats=_RuntimeStats(),
            feeder_config=SimpleNamespace(
                first_rotor_jam_backtrack_output_degrees=18.0,
                first_rotor_jam_max_output_degrees=30.0,
                first_rotor_jam_max_cycles=3,
                first_rotor_jam_retry_cooldown_s=0.1,
            ),
            busy_until=busy_until,
            gear_ratio=2.0,
            push_output_degrees=(15.0, 45.0, 90.0),
        )
        pulse_cfg = SimpleNamespace(delay_between_pulse_ms=250)

        self.assertTrue(strategy.run(pulse_cfg, now_mono=1.0))
        self.assertEqual("shake_l1", strategy.state_name)
        self.assertEqual(0, strategy.attempts)

        busy_until["c1"] = 0.0
        self.assertTrue(strategy.run(pulse_cfg, now_mono=2.0))
        self.assertEqual("push_l1", strategy.state_name)
        self.assertEqual(1, strategy.attempts)


if __name__ == "__main__":
    unittest.main()
