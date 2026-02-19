from typing import Optional, TYPE_CHECKING
import os
import time
import base64
import queue
import cv2
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel, CLASSIFICATION_POSITION
from irl.config import IRLInterface
from global_config import GlobalConfig
from defs.events import KnownObjectEvent, KnownObjectData, KnownObjectStatus
from telemetry import Telemetry
from classification import classify

if TYPE_CHECKING:
    from vision import VisionManager

# spencer todo: add back when there is constant run id per run, save in that blob dir
# SNAP_DIR = "/tmp/sorter_snaps"
SNAP_DELAY_MS = 2000


class Snapping(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        carousel: Carousel,
        vision: "VisionManager",
        event_queue: queue.Queue,
        telemetry: Telemetry,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.carousel = carousel
        self.vision = vision
        self.event_queue = event_queue
        self.telemetry = telemetry
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

    def _emitObjectEvent(self, obj) -> None:
        event = KnownObjectEvent(
            tag="known_object",
            data=KnownObjectData(
                uuid=obj.uuid,
                created_at=obj.created_at,
                updated_at=obj.updated_at,
                status=KnownObjectStatus(obj.status),
                part_id=obj.part_id,
                category_id=obj.category_id,
                confidence=obj.confidence,
                destination_bin=obj.destination_bin,
                thumbnail=obj.thumbnail,
                top_image=obj.top_image,
                bottom_image=obj.bottom_image,
            ),
        )
        self.event_queue.put(event)

    def _captureAndClassify(self) -> None:
        piece = self.carousel.getPieceAtClassification()
        if piece is None:
            self.logger.warn("Snapping: no piece at classification position")
            return

        top_frame, bottom_frame = self.vision.captureFreshClassificationFrames()
        top_crop, bottom_crop = self.vision.getClassificationCrops()

        if top_frame and top_frame.annotated is not None:
            self.telemetry.saveCapture(
                "classification_chamber_top",
                top_frame.raw,
                top_frame.annotated,
                "capture",
                segmentation_map=top_frame.segmentation_map,
            )
        if bottom_frame and bottom_frame.annotated is not None:
            self.telemetry.saveCapture(
                "classification_chamber_bottom",
                bottom_frame.raw,
                bottom_frame.annotated,
                "capture",
                segmentation_map=bottom_frame.segmentation_map,
            )

        if top_crop is None or bottom_crop is None:
            self.logger.warn(
                "Snapping: no object detected in classification frames, marking not_found"
            )
            piece.status = "not_found"
            piece.updated_at = time.time()
            self._emitObjectEvent(piece)
            return

        # spencer todo: add back when there is constant run id per run, save in that blob dir
        # cv2.imwrite(os.path.join(SNAP_DIR, f"{piece.uuid}_top_crop.jpg"), top_crop)
        # cv2.imwrite(
        #     os.path.join(SNAP_DIR, f"{piece.uuid}_bottom_crop.jpg"), bottom_crop
        # )
        # self.logger.info(f"Snapping: saved {piece.uuid[:8]} to {SNAP_DIR}")

        _, thumbnail_buffer = cv2.imencode(
            ".jpg", top_crop, [cv2.IMWRITE_JPEG_QUALITY, 80]
        )
        piece.thumbnail = base64.b64encode(thumbnail_buffer).decode("utf-8")

        if top_frame:
            top_img = (
                top_frame.annotated
                if top_frame.annotated is not None
                else top_frame.raw
            )
            _, top_buffer = cv2.imencode(
                ".jpg", top_img, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            piece.top_image = base64.b64encode(top_buffer).decode("utf-8")
        if bottom_frame:
            bottom_img = (
                bottom_frame.annotated
                if bottom_frame.annotated is not None
                else bottom_frame.raw
            )
            _, bottom_buffer = cv2.imencode(
                ".jpg", bottom_img, [cv2.IMWRITE_JPEG_QUALITY, 80]
            )
            piece.bottom_image = base64.b64encode(bottom_buffer).decode("utf-8")

        piece.status = "classifying"
        piece.updated_at = time.time()
        self._emitObjectEvent(piece)

        self.carousel.markPendingClassification(piece)

        def onResult(
            part_id: Optional[str], confidence: Optional[float] = None
        ) -> None:
            self.carousel.resolveClassification(piece.uuid, part_id, confidence)
            self.logger.info(f"Snapping: classified {piece.uuid[:8]} -> {part_id}")

        classify(self.gc, top_crop, bottom_crop, onResult)

    def cleanup(self) -> None:
        super().cleanup()
        self.start_time = None
        self.snapped = False
