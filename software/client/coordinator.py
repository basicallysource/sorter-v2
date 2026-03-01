from subsystems import (
    SharedVariables,
    FeederStateMachine,
    ClassificationStateMachine,
    DistributionStateMachine,
)
from subsystems.classification.carousel import Carousel
from irl.config import IRLInterface, IRLConfig
from global_config import GlobalConfig
from runtime_variables import RuntimeVariables
from vision import VisionManager
from sorting_profile import mkSortingProfile
from telemetry import Telemetry
import queue


class Coordinator:
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
        self.irl = irl
        self.irl_config = irl_config
        self.gc = gc
        self.logger = gc.logger
        self.vision = vision
        self.event_queue = event_queue
        self.shared = SharedVariables()
        self.sorting_profile = mkSortingProfile(gc)
        self.distribution_layout = irl.distribution_layout

        self.carousel = Carousel(gc.logger, event_queue)
        self.shared.carousel = self.carousel

        self.distribution = DistributionStateMachine(
            irl,
            gc,
            self.shared,
            self.sorting_profile,
            self.distribution_layout,
            event_queue,
        )
        self.classification = ClassificationStateMachine(
            irl, gc, self.shared, vision, event_queue, telemetry, self.carousel
        )
        self.feeder = FeederStateMachine(irl, irl_config, gc, self.shared, vision)

    def step(self) -> None:
        prof = self.gc.profiler
        prof.hit("coordinator.step.calls")
        prof.mark("coordinator.step.interval_ms")

        with prof.timer("coordinator.step.total_ms"):
            with prof.timer("coordinator.step.feeder_ms"):
                self.feeder.step()
            with prof.timer("coordinator.step.classification_ms"):
                self.classification.step()
            with prof.timer("coordinator.step.distribution_ms"):
                self.distribution.step()

    def cleanup(self) -> None:
        self.feeder.cleanup()
        self.classification.cleanup()
        self.distribution.cleanup()
