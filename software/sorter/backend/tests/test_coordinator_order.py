import queue
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from coordinator import Coordinator
from runtime_stats import RuntimeStatsCollector


class _NullTimer:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _Profiler:
    def hit(self, *args, **kwargs) -> None:
        pass

    def mark(self, *args, **kwargs) -> None:
        pass

    def timer(self, *args, **kwargs):
        return _NullTimer()


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass


class _FakeRuntime:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def create_transport(self, *, gc, event_queue):
        _ = gc, event_queue
        return SimpleNamespace()

    def create_distribution(self, **kwargs):
        _ = kwargs
        return SimpleNamespace(step=lambda: self._calls.append("distribution"), cleanup=lambda: None)

    def create_classification(self, **kwargs):
        _ = kwargs
        return SimpleNamespace(step=lambda: self._calls.append("classification"), cleanup=lambda: None)

    def create_feeder(self, **kwargs):
        _ = kwargs
        return SimpleNamespace(step=lambda: self._calls.append("feeder"), cleanup=lambda: None)


class CoordinatorOrderTests(unittest.TestCase):
    def test_step_runs_downstream_first(self) -> None:
        calls: list[str] = []
        fake_runtime = _FakeRuntime(calls)
        gc = SimpleNamespace(
            logger=_Logger(),
            profiler=_Profiler(),
            runtime_stats=RuntimeStatsCollector(),
            set_progress_tracker=None,
        )
        sorting_profile = SimpleNamespace(
            is_set_based=False,
            set_inventories=None,
            reload=lambda: None,
        )
        machine_setup = SimpleNamespace(
            key="classification_channel",
            manual_feed_mode=False,
            runtime_supported=True,
        )

        with patch("coordinator.build_machine_runtime", return_value=fake_runtime), patch(
            "coordinator.mkSortingProfile", return_value=sorting_profile
        ), patch(
            "coordinator.get_machine_setup_definition", return_value=machine_setup
        ):
            coordinator = Coordinator(
                irl=SimpleNamespace(distribution_layout=SimpleNamespace()),
                irl_config=SimpleNamespace(machine_setup=machine_setup, feeding_mode="auto_channels"),
                gc=gc,
                vision=SimpleNamespace(),
                event_queue=queue.Queue(),
                rv=SimpleNamespace(),
                telemetry=SimpleNamespace(),
            )

        coordinator.step()

        self.assertEqual(["distribution", "classification", "feeder"], calls)


if __name__ == "__main__":
    unittest.main()
