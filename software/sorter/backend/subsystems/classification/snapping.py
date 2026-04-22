from typing import Optional, TYPE_CHECKING
import time
import base64
import queue
import threading
import cv2
import numpy as np
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import ClassificationState
from .carousel import Carousel
from irl.config import IRLInterface
from global_config import GlobalConfig
from utils.event import knownObjectToEvent
from defs.known_object import ClassificationStatus
from classification import classify
from blob_manager import BLOB_DIR
from server.classification_training import getClassificationTrainingManager
from .bbox_projection import translate_bbox_to_crop, translate_bboxes_to_crop

if TYPE_CHECKING:
    from vision import VisionManager

SNAP_JPEG_QUALITY = 90
SETTLE_MS = 1500
CLASSIFICATION_TIMEOUT_S = 12.0


class Snapping(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        carousel: Carousel,
        vision: "VisionManager",
        event_queue: queue.Queue,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.carousel = carousel
        self.vision = vision
        self.event_queue = event_queue
        self.snapped = False
        self._entered_at: Optional[float] = None
        self._snap_dir = BLOB_DIR / gc.run_id
        self._snap_dir.mkdir(parents=True, exist_ok=True)
        self._occupancy_state: str | None = None

    def _setOccupancyState(self, state_name: str) -> None:
        if self._occupancy_state == state_name:
            return
        prev_state = self._occupancy_state
        self._occupancy_state = state_name
        self.gc.runtime_stats.observeStateTransition(
            "classification.occupancy",
            prev_state,
            state_name,
        )

    def step(self) -> Optional[ClassificationState]:
        if self._entered_at is None:
            self._entered_at = time.time()
            piece = self.carousel.getPieceAtClassification()
            if piece is not None and piece.carousel_snapping_started_at is None:
                piece.carousel_snapping_started_at = self._entered_at
        elapsed_ms = (time.time() - self._entered_at) * 1000
        self._setOccupancyState("snapping.wait_settle")
        if elapsed_ms < SETTLE_MS:
            return None

        if not self.snapped:
            self._setOccupancyState("snapping.capture_and_classify")
            snap_start = time.time()
            piece = self.carousel.getPieceAtClassification()
            self._captureAndClassify()
            if piece is not None and piece.carousel_snapping_completed_at is None:
                piece.carousel_snapping_completed_at = time.time()
            snap_ms = (time.time() - snap_start) * 1000
            self.logger.info(f"Snapping: capture+classify took {snap_ms:.0f}ms")
            self.snapped = True

        return ClassificationState.IDLE

    def _saveImage(self, name: str, image: np.ndarray) -> None:
        ts = int(time.time() * 1000)
        path = self._snap_dir / f"{ts}_{name}.jpg"
        cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, SNAP_JPEG_QUALITY])

    def _encodeImageBase64(self, image: np.ndarray | None) -> Optional[str]:
        if image is None:
            return None
        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        return base64.b64encode(buffer).decode("utf-8")

    def _captureAndClassify(self) -> None:
        piece = self.carousel.getPieceAtClassification()
        if piece is None:
            self.logger.warn("Snapping: no piece at classification position")
            return

        top_frame, bottom_frame = self.vision.captureFreshClassificationFrames()
        top_candidates = (
            self.vision.getClassificationDetectionCandidates("top", force=True, frame=top_frame)
            if top_frame is not None
            else []
        )
        bottom_candidates = (
            self.vision.getClassificationDetectionCandidates("bottom", force=True, frame=bottom_frame)
            if bottom_frame is not None
            else []
        )
        top_candidate_count = len(top_candidates)
        bottom_candidate_count = len(bottom_candidates)
        detection_bbox_count = max(top_candidate_count, bottom_candidate_count)
        detection_found = detection_bbox_count > 0
        sample_capture = self.vision.getClassificationSampleFromFrames(top_frame, bottom_frame)
        preferred_camera = "top" if sample_capture.get("top_zone") is not None else "bottom"
        preferred_frame = top_frame if preferred_camera == "top" else bottom_frame
        preferred_zone_bbox = (
            self.vision.getClassificationZoneBBox(preferred_camera, frame=preferred_frame)
            if preferred_frame is not None
            else None
        )
        preferred_detection_bbox = (
            self.vision.getClassificationCombinedBbox(preferred_camera, force=True, frame=preferred_frame)
            if preferred_frame is not None
            else None
        )
        preferred_candidate_bboxes = top_candidates if preferred_camera == "top" else bottom_candidates
        preferred_detection_bbox = translate_bbox_to_crop(preferred_detection_bbox, preferred_zone_bbox)
        preferred_candidate_bboxes = translate_bboxes_to_crop(
            preferred_candidate_bboxes,
            preferred_zone_bbox,
        )

        detection_algorithm = self.vision.getClassificationDetectionAlgorithm()
        detection_openrouter_model = (
            self.vision.getClassificationOpenRouterModel()
            if detection_algorithm == "gemini_sam"
            else None
        )
        sample_manager = getClassificationTrainingManager()

        if top_frame:
            top_img = (
                top_frame.annotated
                if top_frame.annotated is not None
                else top_frame.raw
            )
            piece.top_image = self._encodeImageBase64(top_img)
        if bottom_frame:
            bottom_img = (
                bottom_frame.annotated
                if bottom_frame.annotated is not None
                else bottom_frame.raw
            )
            piece.bottom_image = self._encodeImageBase64(bottom_img)

        if piece.thumbnail is None:
            piece.thumbnail = self._encodeImageBase64(
                sample_capture.get("top_zone") if sample_capture.get("top_zone") is not None else sample_capture.get("bottom_zone")
            )

        def saveLiveSample(detection_found: bool, detection_message: str | None) -> dict[str, object] | None:
            try:
                saved = sample_manager.saveLiveClassificationCapture(
                    piece_uuid=piece.uuid,
                    machine_id=self.gc.machine_id,
                    run_id=self.gc.run_id,
                    detection_found=detection_found,
                    detection_algorithm=detection_algorithm,
                    detection_openrouter_model=detection_openrouter_model,
                    detection_bbox=preferred_detection_bbox,
                    detection_candidate_bboxes=preferred_candidate_bboxes,
                    detection_bbox_count=detection_bbox_count,
                    top_detection_bbox_count=top_candidate_count,
                    bottom_detection_bbox_count=bottom_candidate_count,
                    detection_message=detection_message,
                    top_zone=sample_capture.get("top_zone"),
                    bottom_zone=sample_capture.get("bottom_zone"),
                    top_frame=sample_capture.get("top_frame"),
                    bottom_frame=sample_capture.get("bottom_frame"),
                )
                self.logger.info(
                    f"Snapping: saved sample {saved['sample_id']} for piece {piece.uuid[:8]}"
                )
                return saved
            except Exception as exc:
                self.logger.warning(f"Snapping: failed to save live sample: {exc}")
                return None

        if not detection_found:
            message = "No object detected in classification frames."
            saveLiveSample(False, message)
            self.logger.warn(
                "Snapping: no object detected in classification frames, marking not_found"
            )
            piece.classification_status = ClassificationStatus.not_found
            piece.classified_at = time.time()
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))
            return

        if detection_bbox_count > 1:
            message = (
                "Multiple candidate pieces detected in classification chamber; "
                "skipping Brickognize."
            )
            saveLiveSample(True, message)
            self.gc.runtime_stats.observeBlockedReason(
                "classification", "multiple_parts_detected"
            )
            self.logger.warn(
                "Snapping: multiple candidate pieces detected "
                f"(top={top_candidate_count}, bottom={bottom_candidate_count}); "
                "skipping Brickognize and marking piece multi_drop_fail"
            )
            piece.classification_status = ClassificationStatus.multi_drop_fail
            piece.classified_at = time.time()
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))
            return

        with self.gc.profiler.timer("classification.get_crops_ms"):
            top_crop, bottom_crop = self.vision.getClassificationCrops(
                top_frame=top_frame,
                bottom_frame=bottom_frame,
            )

        if top_crop is None and bottom_crop is None:
            message = (
                "Single candidate piece was detected, but crop extraction returned no image."
            )
            saveLiveSample(True, message)
            self.logger.warn(
                "Snapping: detection found a candidate, but crop extraction produced no crop; "
                "marking not_found"
            )
            piece.classification_status = ClassificationStatus.not_found
            piece.classified_at = time.time()
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))
            return

        if top_crop is not None:
            self._saveImage("top_crop", top_crop)
        if bottom_crop is not None:
            self._saveImage("bottom_crop", bottom_crop)

        top_crop_b64 = self._encodeImageBase64(top_crop)
        bottom_crop_b64 = self._encodeImageBase64(bottom_crop)

        piece.thumbnail = top_crop_b64 if top_crop_b64 is not None else bottom_crop_b64

        piece.classification_status = ClassificationStatus.classifying
        piece.updated_at = time.time()
        self.event_queue.put(knownObjectToEvent(piece))

        self.carousel.markPendingClassification(piece)
        saved_live_sample = saveLiveSample(
            True,
            "Single candidate piece detected; sent crop to Brickognize.",
        )

        def onResult(
            part_id: Optional[str],
            color_id: str,
            color_name: str,
            confidence: Optional[float] = None,
            brickognize_preview_url: Optional[str] = None,
            brickognize_source_view: Optional[str] = None,
            brickognize_result: Optional[dict[str, object]] = None,
        ) -> None:
            next_thumbnail = piece.thumbnail
            if brickognize_source_view == "bottom" and bottom_crop_b64 is not None:
                next_thumbnail = bottom_crop_b64
            elif brickognize_source_view == "top" and top_crop_b64 is not None:
                next_thumbnail = top_crop_b64
            best_item = (
                brickognize_result.get("best_item")
                if isinstance(brickognize_result, dict)
                else None
            )
            part_name = (
                best_item.get("name") if isinstance(best_item, dict) else None
            )
            part_category = (
                best_item.get("category") if isinstance(best_item, dict) else None
            )
            resolved = self.carousel.resolveClassification(
                piece.uuid,
                part_id,
                color_id,
                color_name,
                confidence,
                part_name=part_name,
                part_category=part_category,
            )
            if not resolved:
                self.logger.warning(
                    "Snapping: ignoring late Brickognize result for "
                    f"{piece.uuid[:8]} after fallback resolution"
                )
                return
            piece.thumbnail = next_thumbnail
            piece.brickognize_preview_url = brickognize_preview_url
            piece.brickognize_source_view = brickognize_source_view
            saved_session_id = (
                saved_live_sample.get("session_id")
                if isinstance(saved_live_sample, dict)
                and isinstance(saved_live_sample.get("session_id"), str)
                else None
            )
            saved_sample_id = (
                saved_live_sample.get("sample_id")
                if isinstance(saved_live_sample, dict)
                and isinstance(saved_live_sample.get("sample_id"), str)
                else None
            )
            if saved_session_id and saved_sample_id:
                try:
                    sample_manager.attachLiveClassificationResult(
                        saved_session_id,
                        saved_sample_id,
                        status="classified" if part_id else "unknown",
                        part_id=part_id,
                        color_id=color_id,
                        color_name=color_name,
                        confidence=confidence,
                        preview_url=brickognize_preview_url,
                        source_view=brickognize_source_view,
                        top_crop=top_crop,
                        bottom_crop=bottom_crop,
                        result_payload=brickognize_result,
                    )
                except Exception as exc:
                    self.logger.warning(
                        f"Snapping: failed to attach classification result to sample {saved_sample_id}: {exc}"
                    )
            self.logger.info(f"Snapping: classified {piece.uuid[:8]} -> {part_id} color={color_name}")

        def onTimeout() -> None:
            time.sleep(CLASSIFICATION_TIMEOUT_S)
            resolved = self.carousel.resolveClassification(
                piece.uuid,
                None,
                "any_color",
                "Any Color",
                None,
            )
            if not resolved:
                return

            self.gc.runtime_stats.observeBlockedReason(
                "classification",
                "brickognize_timeout",
            )
            self.logger.warning(
                "Snapping: Brickognize timed out for "
                f"{piece.uuid[:8]} after {CLASSIFICATION_TIMEOUT_S:.1f}s; "
                "marking unknown so distribution can continue"
            )
            saved_session_id = (
                saved_live_sample.get("session_id")
                if isinstance(saved_live_sample, dict)
                and isinstance(saved_live_sample.get("session_id"), str)
                else None
            )
            saved_sample_id = (
                saved_live_sample.get("sample_id")
                if isinstance(saved_live_sample, dict)
                and isinstance(saved_live_sample.get("sample_id"), str)
                else None
            )
            if saved_session_id and saved_sample_id:
                try:
                    sample_manager.attachLiveClassificationResult(
                        saved_session_id,
                        saved_sample_id,
                        status="unknown",
                        part_id=None,
                        color_id="any_color",
                        color_name="Any Color",
                        confidence=None,
                        preview_url=None,
                        source_view=None,
                        top_crop=top_crop,
                        bottom_crop=bottom_crop,
                        result_payload={
                            "provider": "brickognize",
                            "error": (
                                "Timed out while waiting for Brickognize classification "
                                f"after {CLASSIFICATION_TIMEOUT_S:.1f}s."
                            ),
                        },
                    )
                except Exception as exc:
                    self.logger.warning(
                        "Snapping: failed to attach timeout classification result "
                        f"to sample {saved_sample_id}: {exc}"
                    )

        threading.Thread(target=onTimeout, daemon=True).start()
        classify(self.gc, top_crop, bottom_crop, onResult)

    def cleanup(self) -> None:
        super().cleanup()
        self.snapped = False
        self._entered_at = None
