from typing import Optional, TYPE_CHECKING
import time
import base64
import queue
import cv2
import numpy as np
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
from utils.event import known_object_to_event
from telemetry import Telemetry
from defs.known_object import ClassificationStatus
from classification import classify
from blob_manager import BLOB_DIR

if TYPE_CHECKING:
    from vision import VisionManager

SNAP_JPEG_QUALITY = 90
SETTLE_MS = 1500


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
        self.snapped = False
        self._entered_at: Optional[float] = None
        self._snap_dir = BLOB_DIR / gc.run_id
        self._snap_dir.mkdir(parents=True, exist_ok=True)

    def step(self) -> Optional[ClassificationState]:
        if self._entered_at is None:
            self._entered_at = time.time()
        if (time.time() - self._entered_at) * 1000 < SETTLE_MS:
            return None

        if not self.snapped:
            snap_start = time.time()
            self._capture_and_classify()
            snap_ms = (time.time() - snap_start) * 1000
            self.logger.info(f"Snapping: capture+classify took {snap_ms:.0f}ms")
            self.snapped = True

        return ClassificationState.IDLE

    def _save_image(self, name: str, image: np.ndarray) -> None:
        ts = int(time.time() * 1000)
        path = self._snap_dir / f"{ts}_{name}.jpg"
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, SNAP_JPEG_QUALITY])

    def _capture_and_classify(self) -> None:
        piece = self.carousel.get_piece_at_classification()
        if piece is None:
            self.logger.warn("Snapping: no piece at classification position")
            return

        top_frame, bottom_frame = self.vision.capture_fresh_classification_frames()
        with self.gc.profiler.timer("classification.get_crops_ms"):
            top_crop, bottom_crop = self.vision.get_classification_crops()

        if top_frame and top_frame.annotated is not None:
            self.telemetry.save_capture(
                "classification_chamber_top",
                top_frame.raw,
                top_frame.annotated,
                "capture",
                segmentation_map=top_frame.segmentation_map,
            )
        if bottom_frame and bottom_frame.annotated is not None:
            self.telemetry.save_capture(
                "classification_chamber_bottom",
                bottom_frame.raw,
                bottom_frame.annotated,
                "capture",
                segmentation_map=bottom_frame.segmentation_map,
            )

        if top_crop is None and bottom_crop is None:
            self.logger.warn(
                "Snapping: no object detected in classification frames, marking not_found"
            )
            piece.classification_status = ClassificationStatus.not_found
            piece.classified_at = time.time()
            piece.updated_at = time.time()
            self.event_queue.put(known_object_to_event(piece))
            return

        if top_crop is not None:
            self._save_image("top_crop", top_crop)
        if bottom_crop is not None:
            self._save_image("bottom_crop", bottom_crop)

        thumbnail_crop = top_crop if top_crop is not None else bottom_crop
        _, thumbnail_buffer = cv2.imencode(
            ".jpg", thumbnail_crop, [cv2.IMWRITE_JPEG_QUALITY, 80]
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

        piece.classification_status = ClassificationStatus.classifying
        piece.updated_at = time.time()
        self.event_queue.put(known_object_to_event(piece))

        self.carousel.mark_pending_classification(piece)

        def on_result(
            part_id: Optional[str], color_id: str, color_name: str, confidence: Optional[float] = None
        ) -> None:
            self.carousel.resolve_classification(piece.uuid, part_id, color_id, color_name, confidence)
            if part_id is None:
                self.logger.notice(f"Snapping: classified {piece.uuid[:8]} -> None color={color_name}")
            else:
                self.logger.info(f"Snapping: classified {piece.uuid[:8]} -> {part_id} color={color_name}")

        classify(self.gc, top_crop, bottom_crop, on_result)

    def cleanup(self) -> None:
        super().cleanup()
        self.snapped = False
        self._entered_at = None
