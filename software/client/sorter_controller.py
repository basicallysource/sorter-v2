from defs.sorter_controller import SorterLifecycle
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from runtime_variables import RuntimeVariables
from coordinator import Coordinator
from vision import VisionManager
from telemetry import Telemetry
import queue


class SorterController:
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        vision: VisionManager,
        event_queue: queue.Queue,
        rv: RuntimeVariables,
        telemetry: Telemetry,
    ):
        self.state = SorterLifecycle.INITIALIZING
        self.irl = irl
        self.gc = gc
        self.vision = vision
        self.event_queue = event_queue
        self.coordinator = Coordinator(
            irl, irl_config, gc, vision, event_queue, rv, telemetry
        )

    def start(self) -> None:
        self.state = SorterLifecycle.PAUSED

    def resume(self) -> None:
        self.state = SorterLifecycle.RUNNING

    def pause(self) -> None:
        self.coordinator.cleanup()
        self.state = SorterLifecycle.PAUSED

    def stop(self) -> None:
        self.coordinator.cleanup()
        self.state = SorterLifecycle.READY

    def step(self) -> None:
        if self.state == SorterLifecycle.RUNNING:
            self.coordinator.step()
