from typing import Optional, TYPE_CHECKING
import os
import tempfile
import time
import cv2
import numpy as np
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
from defs.consts import FEEDER_OBJECT_CLASS_ID

if TYPE_CHECKING:
    from vision import VisionManager

OBJECT_DETECTION_CONFIDENCE_THRESHOLD = 0.3
BRICKOGNIZE_TEMP_DIR_NAME = "brickognize_crops"
DETECTING_TRIGGER_DIR_NAME = "detecting_triggers"


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
                piece = self.carousel.addPieceAtFeeder()
                self._saveTriggerCrop(piece.uuid, obj_dm.mask)
                return ClassificationState.ROTATING

        return None

    def cleanup(self) -> None:
        super().cleanup()

    def _saveTriggerCrop(self, piece_uuid: str, mask: np.ndarray) -> None:
        feeder_frame = self.vision.feeder_frame
        if feeder_frame is None:
            return

        coords = np.argwhere(mask)
        if len(coords) == 0:
            return

        y1 = int(np.min(coords[:, 0]))
        y2 = int(np.max(coords[:, 0])) + 1
        x1 = int(np.min(coords[:, 1]))
        x2 = int(np.max(coords[:, 1])) + 1

        frame_h, frame_w = feeder_frame.raw.shape[:2]
        x1 = max(0, min(x1, frame_w - 1))
        x2 = max(0, min(x2, frame_w))
        y1 = max(0, min(y1, frame_h - 1))
        y2 = max(0, min(y2, frame_h))
        if x2 <= x1 or y2 <= y1:
            return

        crop = feeder_frame.raw[y1:y2, x1:x2]
        if crop.size == 0:
            return

        temp_dir = os.path.join(
            tempfile.gettempdir(),
            BRICKOGNIZE_TEMP_DIR_NAME,
            DETECTING_TRIGGER_DIR_NAME,
        )
        os.makedirs(temp_dir, exist_ok=True)
        file_name = f"trigger_{piece_uuid}_{time.time_ns()}.jpg"
        file_path = os.path.join(temp_dir, file_name)
        cv2.imwrite(file_path, crop)
        print(f"saved detecting trigger crop {file_name} to {file_path}")
