from defs.sorter_controller import SorterLifecycle
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from coordinator import Coordinator
from vision import VisionManager
import queue
import time


def _broadcastSorterState(state_value: str) -> None:
    try:
        from server import shared_state
    except Exception:
        return
    shared_state.publishSorterState(state_value)


def _loadTraining() -> None:
    import training_runs

    training_runs.loadSoon()


class SorterController:
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        vision: VisionManager,
        event_queue: queue.Queue,
    ):
        self.state = SorterLifecycle.INITIALIZING
        self.irl = irl
        self.gc = gc
        self.vision = vision
        self.event_queue = event_queue
        self.coordinator = Coordinator(
            irl, irl_config, gc, vision, event_queue
        )
        _broadcastSorterState(self.state.value)

    def start(self) -> None:
        self.state = SorterLifecycle.PAUSED
        self.gc.runtime_stats.setLifecycleState(self.state.value)
        _loadTraining()
        _broadcastSorterState(self.state.value)

    def resume(self) -> None:
        self._running_since = time.monotonic()
        try:
            import incidents

            incidents.clear(self.gc, "nothing_fed")
            # Resuming is the operator's word that the bucket was seen to.
            incidents.clear(self.gc, "potentially_bucket_empty", resolved_by="operator")
        except Exception:
            pass
        self.irl.enableSteppers()
        self.state = SorterLifecycle.RUNNING
        self.gc.runtime_stats.setLifecycleState(self.state.value)
        self.gc.run_recorder.markRunning()
        self.gc.lifetime_stats.markRunning()
        _broadcastSorterState(self.state.value)

    def pause(self) -> None:
        self.coordinator.pause()
        self.state = SorterLifecycle.PAUSED
        self.gc.runtime_stats.setLifecycleState(self.state.value)
        self.gc.run_recorder.markPaused()
        self.gc.lifetime_stats.markStopped()
        _broadcastSorterState(self.state.value)

    def stop(self) -> None:
        self.coordinator.cleanup()
        self.state = SorterLifecycle.READY
        self.gc.runtime_stats.setLifecycleState(self.state.value)
        self.gc.run_recorder.markPaused()
        self.gc.lifetime_stats.markStopped()
        _broadcastSorterState(self.state.value)

    def reloadSortingProfile(self) -> None:
        self.coordinator.reload_sorting_profile()

    def step(self) -> None:
        if self.state == SorterLifecycle.RUNNING:
            self.coordinator.step()
            self._watchFeed()

    def _watchFeed(self) -> None:
        """Pause once no piece has come off C1 for the feeder's
        pause_after_no_feed_min: the hopper is empty or C1 is stuck."""
        now = time.monotonic()
        if now - getattr(self, "_feed_checked", 0.0) < 5.0:
            return
        self._feed_checked = now
        try:
            from subsystems.feeder.pulse_perception.config import configFromDict
            from toml_config import getPulsePerceptionConfig

            limit_min = float(configFromDict(getPulsePerceptionConfig()).pause_after_no_feed_min)
        except Exception:
            return
        if limit_min <= 0:
            return
        shared = getattr(self.coordinator, "shared", None)
        fed = getattr(shared, "c1_fed_at", None) if shared is not None else None
        last = max(fed or 0.0, getattr(self, "_running_since", now))
        if now - last < limit_min * 60.0:
            return
        minutes = f"{limit_min:g}"
        self.gc.logger.warning(f"Nothing has come off C1 in {minutes} minutes: pausing")
        try:
            import incidents

            incidents.report(self.gc, "nothing_fed", subject="C1", minutes=minutes)
        except Exception:
            pass
        self.pause()
