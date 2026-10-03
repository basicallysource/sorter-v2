import queue
import unittest
from types import SimpleNamespace
from contextlib import ExitStack
from unittest.mock import patch

from coordinator import Coordinator
from runtime_stats import RuntimeStatsCollector


class _Logger:
    def info(self, *args, **kwargs) -> None:
        pass

    def warning(self, *args, **kwargs) -> None:
        pass


def _patched_subsystems(calls: list[str]) -> ExitStack:
    def fake(name: str):
        return lambda *args, **kwargs: SimpleNamespace(
            step=lambda: calls.append(name), cleanup=lambda: None
        )

    stack = ExitStack()
    stack.enter_context(patch("coordinator.ClassificationChannelTransport", SimpleNamespace))
    stack.enter_context(
        patch("subsystems.distribution.state_machine.DistributionStateMachine", fake("distribution"))
    )
    stack.enter_context(
        patch(
            "subsystems.classification_channel.state_machine.ClassificationChannelStateMachine",
            fake("classification"),
        )
    )
    stack.enter_context(patch("subsystems.feeder.pulse_perception.flow.PulsePerceptionFeeding", fake("feeder")))
    return stack


class CoordinatorOrderTests(unittest.TestCase):
    def test_step_runs_downstream_first(self) -> None:
        calls: list[str] = []
        gc = SimpleNamespace(
            logger=_Logger(),
            runtime_stats=RuntimeStatsCollector(),
            set_progress_tracker=None,
        )
        sorting_profile = SimpleNamespace(
            is_set_based=False,
            setKitProgress=lambda tracker: None,
            set_inventories=None,
            reload=lambda: None,
        )

        with _patched_subsystems(calls), patch(
            "coordinator.mkSortingProfile", return_value=sorting_profile
        ):
            coordinator = Coordinator(
                irl=SimpleNamespace(distribution_layout=SimpleNamespace()),
                irl_config=SimpleNamespace(classification_channel_config=SimpleNamespace()),
                gc=gc,
                vision=SimpleNamespace(),
                event_queue=queue.Queue(),
            )

        coordinator.step()

        self.assertEqual(["distribution", "classification", "feeder"], calls)

    def test_c4_stall_incident_holds_feeder_and_distribution(self) -> None:
        calls: list[str] = []
        runtime_stats = RuntimeStatsCollector()
        runtime_stats.setActiveIncident(
            {
                "kind": "exit_stuck",
                "source_kind": "c4_stall_watchdog",
                "channel": "c4",
                "status": "waiting_for_operator",
            }
        )
        gc = SimpleNamespace(
            logger=_Logger(),
            runtime_stats=runtime_stats,
            set_progress_tracker=None,
        )
        sorting_profile = SimpleNamespace(
            is_set_based=False,
            setKitProgress=lambda tracker: None,
            set_inventories=None,
            reload=lambda: None,
        )

        with _patched_subsystems(calls), patch(
            "coordinator.mkSortingProfile", return_value=sorting_profile
        ):
            coordinator = Coordinator(
                irl=SimpleNamespace(distribution_layout=SimpleNamespace()),
                irl_config=SimpleNamespace(classification_channel_config=SimpleNamespace()),
                gc=gc,
                vision=SimpleNamespace(),
                event_queue=queue.Queue(),
            )

        coordinator.step()

        self.assertEqual(["classification"], calls)
        self.assertFalse(coordinator.shared.classification_ready)
        self.assertFalse(coordinator.shared.distribution_ready)

    def test_non_exit_incident_holds_all_subsystems(self) -> None:
        calls: list[str] = []
        runtime_stats = RuntimeStatsCollector()
        runtime_stats.setActiveIncident(
            {
                "kind": "distribution_no_bin_available",
                "status": "waiting_for_operator",
            }
        )
        gc = SimpleNamespace(
            logger=_Logger(),
            runtime_stats=runtime_stats,
            set_progress_tracker=None,
        )
        sorting_profile = SimpleNamespace(
            is_set_based=False,
            setKitProgress=lambda tracker: None,
            set_inventories=None,
            reload=lambda: None,
        )

        with _patched_subsystems(calls), patch(
            "coordinator.mkSortingProfile", return_value=sorting_profile
        ):
            coordinator = Coordinator(
                irl=SimpleNamespace(distribution_layout=SimpleNamespace()),
                irl_config=SimpleNamespace(classification_channel_config=SimpleNamespace()),
                gc=gc,
                vision=SimpleNamespace(),
                event_queue=queue.Queue(),
            )

        coordinator.step()

        self.assertEqual([], calls)
        self.assertFalse(coordinator.shared.classification_ready)
        self.assertFalse(coordinator.shared.distribution_ready)


if __name__ == "__main__":
    unittest.main()
