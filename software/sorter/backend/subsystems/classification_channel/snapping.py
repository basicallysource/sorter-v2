from typing import Optional
import base64
import queue
import threading
import time

import cv2
import numpy as np

from blob_manager import BLOB_DIR
from classification import classify
from classification.brickognize import (
    ANY_COLOR,
    ANY_COLOR_NAME,
    _classifyImages,
    _pickBestColor,
    _pickBestItem,
)
from defs.known_object import ClassificationStatus
from global_config import GlobalConfig
from irl.config import IRLInterface
from piece_transport import ClassificationChannelTransport
from server.classification_training import getClassificationTrainingManager
from states.base_state import BaseState
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables
from telemetry import Telemetry
from utils.event import knownObjectToEvent

SNAP_JPEG_QUALITY = 90
SETTLE_MS = 1200
CLASSIFICATION_TIMEOUT_S = 12.0


class Snapping(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
        vision,
        event_queue: queue.Queue,
        telemetry: Telemetry,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.transport = transport
        self.vision = vision
        self.event_queue = event_queue
        self.telemetry = telemetry
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

    def step(self) -> Optional[ClassificationChannelState]:
        piece = self.transport.getPieceAtClassification()
        if piece is None:
            return ClassificationChannelState.DETECTING

        if piece.classification_status in (
            ClassificationStatus.classified,
            ClassificationStatus.unknown,
            ClassificationStatus.not_found,
            ClassificationStatus.multi_drop_fail,
        ):
            return ClassificationChannelState.EJECTING

        if self._entered_at is None:
            self._entered_at = time.time()
            if piece.carousel_snapping_started_at is None:
                piece.carousel_snapping_started_at = self._entered_at

        elapsed_ms = (time.time() - self._entered_at) * 1000
        self._setOccupancyState("classification_channel.wait_settle")
        if elapsed_ms < SETTLE_MS:
            return None

        if not self.snapped:
            self._setOccupancyState("classification_channel.capture_and_classify")
            self._captureAndClassify()
            piece = self.transport.getPieceAtClassification()
            if piece is not None and piece.carousel_snapping_completed_at is None:
                piece.carousel_snapping_completed_at = time.time()
            self.snapped = True

        return ClassificationChannelState.EJECTING

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

    def _decodeImageBase64(self, payload: object) -> np.ndarray | None:
        if not isinstance(payload, str) or not payload:
            return None
        try:
            raw = base64.b64decode(payload)
        except Exception:
            return None
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    def _collectTrackedImages(self, piece) -> list[np.ndarray]:
        track_id = getattr(piece, "tracked_global_id", None)
        if not isinstance(track_id, int):
            return []
        detail = self.vision.getFeederTrackHistoryDetail(track_id)
        if not isinstance(detail, dict):
            return []
        images: list[tuple[float, np.ndarray]] = []
        for segment in detail.get("segments", []):
            if not isinstance(segment, dict):
                continue
            if segment.get("source_role") not in {"c_channel_3", "carousel"}:
                continue
            for snap in segment.get("sector_snapshots", []):
                if not isinstance(snap, dict):
                    continue
                image = self._decodeImageBase64(snap.get("piece_jpeg_b64"))
                if image is None:
                    continue
                captured_ts = snap.get("captured_ts")
                images.append(
                    (
                        float(captured_ts) if isinstance(captured_ts, (int, float)) else 0.0,
                        image,
                    )
                )
        images.sort(key=lambda item: item[0])
        return [image for _ts, image in images[:8]]

    def _classifyTrackedImagesAsync(self, images: list[np.ndarray], onResult) -> None:
        def _run() -> None:
            try:
                result = _classifyImages(images)
                best_item, best_view = _pickBestItem(result, None)
                best_color = _pickBestColor(result, None)
                color_id = best_color["id"] if best_color else ANY_COLOR
                color_name = best_color["name"] if best_color else ANY_COLOR_NAME
                preview_url = best_item.get("img_url") if best_item else None
                onResult(
                    best_item["id"] if best_item else None,
                    color_id,
                    color_name,
                    best_item.get("score") if best_item else None,
                    preview_url,
                    "tracked_multi" if best_item else None,
                    {
                        "provider": "brickognize",
                        "tracked_image_count": len(images),
                        "best_item": best_item,
                        "best_view": best_view,
                        "best_color": best_color,
                        "items": result.get("items", []),
                    },
                )
            except Exception as exc:
                self.logger.error(f"ClassificationChannel: tracked Brickognize failed: {exc}")
                onResult(
                    None,
                    ANY_COLOR,
                    ANY_COLOR_NAME,
                    None,
                    None,
                    None,
                    {
                        "provider": "brickognize",
                        "tracked_image_count": len(images),
                        "error": str(exc),
                    },
                )

        threading.Thread(target=_run, daemon=True).start()

    def _captureAndClassify(self) -> None:
        piece = self.transport.getPieceAtClassification()
        if piece is None:
            self.logger.warn("ClassificationChannel: no piece at classification position")
            return

        frame = self.vision.captureFreshClassificationChannelFrame()
        candidates = self.vision.getClassificationChannelDetectionCandidates(
            force=True,
            frame=frame,
        )
        detection_bbox_count = len(candidates)
        detection_found = detection_bbox_count > 0
        detection_bbox = self.vision.getClassificationChannelCombinedBbox(
            force=True,
            frame=frame,
        )
        sample_capture = self.vision.getClassificationChannelSampleFromFrame(frame)
        channel_crop = self.vision.getClassificationChannelCrop(force=True, frame=frame)

        if frame is not None:
            annotated = frame.annotated if frame.annotated is not None else frame.raw
            self.telemetry.saveCapture(
                "classification_channel",
                frame.raw,
                annotated,
                "capture",
                segmentation_map=frame.segmentation_map,
            )

        detection_algorithm = self.vision.getCarouselDetectionAlgorithm()
        detection_openrouter_model = (
            self.vision.getCarouselOpenRouterModel()
            if detection_algorithm == "gemini_sam"
            else None
        )
        sample_manager = getClassificationTrainingManager()

        zone_image = sample_capture.get("zone")
        frame_image = sample_capture.get("frame")
        preferred_preview = zone_image if zone_image is not None else frame_image
        preview_b64 = self._encodeImageBase64(preferred_preview)
        piece.top_image = preview_b64
        piece.bottom_image = None

        def saveLiveSample(
            detection_found_value: bool,
            detection_message: str | None,
        ) -> dict[str, object] | None:
            try:
                return sample_manager.saveLiveClassificationCapture(
                    piece_uuid=piece.uuid,
                    machine_id=self.gc.machine_id,
                    run_id=self.gc.run_id,
                    source_role="classification_channel",
                    preferred_camera="top",
                    detection_found=detection_found_value,
                    detection_algorithm=detection_algorithm,
                    detection_openrouter_model=detection_openrouter_model,
                    detection_bbox=list(detection_bbox) if detection_bbox is not None else None,
                    detection_candidate_bboxes=[list(candidate) for candidate in candidates],
                    detection_bbox_count=detection_bbox_count,
                    top_detection_bbox_count=detection_bbox_count,
                    bottom_detection_bbox_count=0,
                    detection_message=detection_message,
                    top_zone=zone_image,
                    bottom_zone=None,
                    top_frame=frame_image,
                    bottom_frame=None,
                )
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: failed to save live sample: {exc}"
                )
                return None

        if not detection_found:
            message = "No object detected in the classification channel frame."
            saveLiveSample(False, message)
            self.logger.warn(
                "ClassificationChannel: no object detected, marking piece not_found"
            )
            if piece.thumbnail is None:
                piece.thumbnail = preview_b64
            piece.classification_status = ClassificationStatus.not_found
            piece.classified_at = time.time()
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))
            return

        if detection_bbox_count > 1:
            message = (
                "Multiple candidate pieces detected in the classification channel; "
                "skipping Brickognize."
            )
            saveLiveSample(True, message)
            self.gc.runtime_stats.observeBlockedReason(
                "classification", "multiple_parts_detected"
            )
            self.logger.warn(
                "ClassificationChannel: multiple candidate pieces detected; "
                "marking piece multi_drop_fail"
            )
            if piece.thumbnail is None:
                piece.thumbnail = preview_b64
            piece.classification_status = ClassificationStatus.multi_drop_fail
            piece.classified_at = time.time()
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))
            return

        if channel_crop is None:
            message = (
                "Single candidate piece was detected, but crop extraction returned no image."
            )
            saveLiveSample(True, message)
            self.logger.warn(
                "ClassificationChannel: crop extraction failed; marking piece not_found"
            )
            if piece.thumbnail is None:
                piece.thumbnail = preview_b64
            piece.classification_status = ClassificationStatus.not_found
            piece.classified_at = time.time()
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))
            return

        self._saveImage("classification_channel_crop", channel_crop)
        crop_b64 = self._encodeImageBase64(channel_crop)
        piece.thumbnail = crop_b64
        piece.classification_status = ClassificationStatus.classifying
        piece.updated_at = time.time()
        self.event_queue.put(knownObjectToEvent(piece))

        self.transport.markPendingClassification(piece)
        tracked_images = self._collectTrackedImages(piece)
        saved_live_sample = saveLiveSample(
            True,
            (
                f"Collected {len(tracked_images)} tracked crop(s) across C-Channel 3 and "
                "classification channel; sent multi-image query to Brickognize."
                if tracked_images
                else "Single candidate piece detected in classification channel; sent crop to Brickognize."
            ),
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
            resolved = self.transport.resolveClassification(
                piece.uuid,
                part_id,
                color_id,
                color_name,
                confidence,
            )
            if not resolved:
                self.logger.warning(
                    "ClassificationChannel: ignoring late Brickognize result for "
                    f"{piece.uuid[:8]}"
                )
                return

            piece.thumbnail = crop_b64
            piece.brickognize_preview_url = brickognize_preview_url
            piece.brickognize_source_view = (
                "tracked_multi" if tracked_images else "channel"
            )
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))

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
                        source_view="tracked_multi" if tracked_images else "channel",
                        top_crop=channel_crop,
                        bottom_crop=None,
                        result_payload=brickognize_result,
                    )
                except Exception as exc:
                    self.logger.warning(
                        "ClassificationChannel: failed to attach classification result "
                        f"to sample {saved_sample_id}: {exc}"
                    )

            self.logger.info(
                "ClassificationChannel: classified %s -> %s color=%s via %s"
                % (
                    piece.uuid[:8],
                    part_id,
                    color_name,
                    brickognize_source_view or ("tracked_multi" if tracked_images else "channel"),
                )
            )

        def onTimeout() -> None:
            time.sleep(CLASSIFICATION_TIMEOUT_S)
            resolved = self.transport.resolveClassification(
                piece.uuid,
                None,
                "any_color",
                "Any Color",
                None,
            )
            if not resolved:
                return

            piece.brickognize_source_view = (
                "tracked_multi" if tracked_images else "channel"
            )
            piece.updated_at = time.time()
            self.event_queue.put(knownObjectToEvent(piece))
            self.gc.runtime_stats.observeBlockedReason(
                "classification",
                "brickognize_timeout",
            )
            self.logger.warning(
                "ClassificationChannel: Brickognize timed out for "
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
                        source_view="tracked_multi" if tracked_images else "channel",
                        top_crop=channel_crop,
                        bottom_crop=None,
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
                        "ClassificationChannel: failed to attach timeout classification "
                        f"result to sample {saved_sample_id}: {exc}"
                    )

        threading.Thread(target=onTimeout, daemon=True).start()
        if tracked_images:
            self._classifyTrackedImagesAsync(tracked_images, onResult)
        else:
            classify(self.gc, channel_crop, None, onResult)

    def cleanup(self) -> None:
        super().cleanup()
        self.snapped = False
        self._entered_at = None
