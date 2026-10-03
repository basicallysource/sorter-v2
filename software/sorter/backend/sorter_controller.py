from defs.sorter_controller import SorterLifecycle
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from coordinator import Coordinator
from vision import VisionManager
import queue


def _broadcastSorterState(state_value: str) -> None:
    try:
        from server import shared_state
    except Exception:
        return
    shared_state.publishSorterState(state_value)


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
        _broadcastSorterState(self.state.value)

    def resume(self) -> None:
        self.irl.enableSteppers()
        self.state = SorterLifecycle.RUNNING
        self.gc.runtime_stats.setLifecycleState(self.state.value)
        self.gc.run_recorder.markRunning()
        self.gc.lifetime_stats.markRunning()
        _broadcastSorterState(self.state.value)

    def pause(self) -> None:
        self.coordinator.cleanup()
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
