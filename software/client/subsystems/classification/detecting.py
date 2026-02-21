from typing import Optional, TYPE_CHECKING
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
from defs.consts import FEEDER_OBJECT_CLASS_ID

if TYPE_CHECKING:
    from vision import VisionManager

OBJECT_DETECTION_CONFIDENCE_THRESHOLD = 0.5


class Detecting(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        carousel: Carousel,
        vision: "VisionManager",
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.carousel = carousel
        self.vision = vision

    def step(self) -> Optional[ClassificationState]:
        masks_by_class = self.vision.getFeederMasksByClass()
        object_detected_masks = masks_by_class.get(FEEDER_OBJECT_CLASS_ID, [])

        # filter objects by confidence threshold
        high_confidence_objects = [
            dm
            for dm in object_detected_masks
            if dm.confidence >= OBJECT_DETECTION_CONFIDENCE_THRESHOLD
        ]

        if not high_confidence_objects:
            return None

        # check if any high-confidence object is on a carousel platform
        for obj_dm in high_confidence_objects:
            if self.vision.isObjectOnCarouselPlatform(obj_dm.mask):
                self.logger.info(
                    f"Detecting: object on carousel platform (confidence={obj_dm.confidence:.2f})"
                )
                self.shared.classification_ready = False
                self.carousel.addPieceAtFeeder()
                return ClassificationState.ROTATING

        return None

    def cleanup(self) -> None:
        super().cleanup()
