from subsystems import (
    SharedVariables,
    FeederStateMachine,
    ClassificationStateMachine,
    DistributionStateMachine,
    mkDefaultLayout,
    layoutMatchesCategories,
    applyCategories,
)
from irl.config import IRLInterface
from global_config import GlobalConfig
from vision import VisionManager
from sorting_profile import BrickLinkCategories
from blob_manager import getBinCategories


class Coordinator:
    def __init__(self, irl: IRLInterface, gc: GlobalConfig, vision: VisionManager):
        self.irl = irl
        self.gc = gc
        self.logger = gc.logger
        self.vision = vision
        self.shared = SharedVariables()
        self.sorting_profile = BrickLinkCategories()
        self.distribution_layout = mkDefaultLayout()

        saved_categories = getBinCategories()
        if saved_categories is not None:
            if layoutMatchesCategories(self.distribution_layout, saved_categories):
                applyCategories(self.distribution_layout, saved_categories)
                self.logger.info("Loaded bin categories from storage")
            else:
                self.logger.warn("Saved bin categories don't match layout, ignoring")

        self.distribution = DistributionStateMachine(
            irl, gc, self.shared, self.sorting_profile, self.distribution_layout
        )
        self.classification = ClassificationStateMachine(irl, gc, self.shared, vision)
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
