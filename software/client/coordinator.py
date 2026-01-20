from subsystems import (
    SharedVariables,
    FeederStateMachine,
    ClassificationStateMachine,
    DistributionStateMachine,
)
from irl.config import IRLInterface
from global_config import GlobalConfig
from vision import VisionManager


class Coordinator:
    def __init__(self, irl: IRLInterface, gc: GlobalConfig, vision: VisionManager):
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.vision = vision
        self.shared = SharedVariables()

        self.distribution = DistributionStateMachine(irl, gc, self.shared)
        self.classification = ClassificationStateMachine(irl, gc, self.shared)
        self.feeder = FeederStateMachine(irl, gc, self.shared)

    def step(self) -> None:
        self.feeder.step()
        self.classification.step()
        self.distribution.step()

    def cleanup(self) -> None:
        self.feeder.cleanup()
        self.classification.cleanup()
        self.distribution.cleanup()

    def triggerStart(self) -> None:
        self.feeder.triggerStart()
