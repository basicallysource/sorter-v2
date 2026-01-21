from typing import Optional, TYPE_CHECKING
import os
import time
import cv2
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
import classification

if TYPE_CHECKING:
    from vision import VisionManager

SNAP_DIR = "/tmp/sorter_snaps"
SNAP_DELAY_MS = 2000


class Snapping(BaseState):
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
        self.start_time: Optional[float] = None
        self.snapped = False

    def step(self) -> Optional[ClassificationState]:
        if self.start_time is None:
            self.start_time = time.time()
            self.logger.info("Snapping: waiting for camera settle")
            return None

        elapsed_ms = (time.time() - self.start_time) * 1000
        if elapsed_ms < SNAP_DELAY_MS:
            return None

        if not self.snapped:
            self._captureAndClassify()
            self.snapped = True

        self.shared.classification_ready = True
        return ClassificationState.IDLE

    def _captureAndClassify(self) -> None:
        piece = self.carousel.getPieceAtClassification()
        if piece is None:
            self.logger.warn("Snapping: no piece at classification position")
            return

        top_frame, bottom_frame = self.vision.captureFreshClassificationFrames()
        top_crop, bottom_crop = self.vision.getClassificationCrops()
        if top_crop is None or bottom_crop is None:
            self.logger.warn("Snapping: no object detected in classification frames")
            return

        os.makedirs(SNAP_DIR, exist_ok=True)
        if top_frame:
            cv2.imwrite(
                os.path.join(SNAP_DIR, f"{piece.uuid}_top_full.jpg"), top_frame.raw
            )
        if bottom_frame:
            cv2.imwrite(
                os.path.join(SNAP_DIR, f"{piece.uuid}_bottom_full.jpg"),
                bottom_frame.raw,
            )
        cv2.imwrite(os.path.join(SNAP_DIR, f"{piece.uuid}_top_crop.jpg"), top_crop)
        cv2.imwrite(
            os.path.join(SNAP_DIR, f"{piece.uuid}_bottom_crop.jpg"), bottom_crop
        )
        self.logger.info(f"Snapping: saved {piece.uuid[:8]} to {SNAP_DIR}")

        self.carousel.markPendingClassification(piece)

        def onResult(part_id: Optional[str]) -> None:
            self.carousel.resolveClassification(piece.uuid, part_id or "unknown")
            self.logger.info(f"Snapping: classified {piece.uuid[:8]} -> {part_id}")

        classification.classify(self.gc, top_crop, bottom_crop, onResult)

    def cleanup(self) -> None:
        super().cleanup()
        self.start_time = None
        self.snapped = False
