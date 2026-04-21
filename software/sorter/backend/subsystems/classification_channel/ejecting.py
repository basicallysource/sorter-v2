from typing import Optional
import base64
import threading
import time

import cv2
import numpy as np

from classification.brickognize import (
    ANY_COLOR,
    ANY_COLOR_NAME,
    _classifyImages,
    _pickBestColor,
    _pickBestItem,
)
from defs.known_object import ClassificationStatus
from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from role_aliases import is_auxiliary_classification_role
from states.base_state import BaseState
from subsystems.bus import StationId
from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.shared_variables import SharedVariables
from utils.event import knownObjectToEvent

PRE_EJECT_DELAY_MS = 200
CLASSIFICATION_TIMEOUT_S = 12.0
MIN_RECOGNIZE_CROPS = 3


class Ejecting(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
        vision=None,
        event_queue=None,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.transport = transport
        self.vision = vision
        self.event_queue = event_queue
        self.entered_at: Optional[float] = None
        self.start_time: Optional[float] = None
        self.command_sent = False
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
        classification_piece = self.transport.getPieceAtClassification()
        wait_piece = self.transport.getPieceAtWaitZone()

        if classification_piece is None and wait_piece is None:
            return ClassificationChannelState.DETECTING

        # Wait piece must be resolved before we can drop it into distribution.
        if wait_piece is not None:
            if wait_piece.classification_status in (
                ClassificationStatus.pending,
                ClassificationStatus.classifying,
            ):
                self._setOccupancyState("classification_channel.wait_classification_result")
                self.gc.runtime_stats.observeBlockedReason(
                    "classification", "waiting_classification_result"
                )
                return None
            if not self.shared.distribution_ready:
                self._setOccupancyState("classification_channel.wait_distribution_ready")
                self.gc.runtime_stats.observeBlockedReason(
                    "classification", "waiting_distribution_ready"
                )
                return None

        now = time.time()
        if self.entered_at is None:
            self.entered_at = now

        if self.start_time is None:
            elapsed_since_entry_ms = (now - self.entered_at) * 1000
            self._setOccupancyState("classification_channel.pre_eject_delay")
            if elapsed_since_entry_ms < PRE_EJECT_DELAY_MS:
                return None

            cfg = self.irl_config.feeder_config.classification_channel_eject
            pulse_degrees = self.irl.carousel_stepper.degrees_for_microsteps(
                cfg.steps_per_pulse
            )
            # Apply the configured per-pulse speed — the stepper's init-time
            # limit is just a conservative default; each subsystem is
            # expected to raise it to its pulse-specific value (feeder
            # channels do the same via set_speed_limits before move).
            try:
                self.irl.carousel_stepper.set_speed_limits(
                    16, int(cfg.microsteps_per_second)
                )
            except Exception as exc:
                self.logger.warning(
                    f"ClassificationChannel: could not apply eject speed: {exc}"
                )
            if not self.irl.carousel_stepper.move_degrees(pulse_degrees):
                self.gc.runtime_stats.observeBlockedReason(
                    "classification", "classification_channel_eject_rejected"
                )
                return None

            self.start_time = now
            self.command_sent = True
            moving_piece = classification_piece or wait_piece
            if moving_piece is not None and moving_piece.carousel_rotate_started_at is None:
                moving_piece.carousel_rotate_started_at = now

            if wait_piece is not None and classification_piece is not None:
                self.logger.info(
                    "ClassificationChannel: dropping piece %s and parking piece %s with %.1f degrees"
                    % (
                        wait_piece.uuid[:8],
                        classification_piece.uuid[:8],
                        pulse_degrees,
                    )
                )
            elif wait_piece is not None:
                self.logger.info(
                    "ClassificationChannel: dropping parked piece %s with %.1f degrees"
                    % (wait_piece.uuid[:8], pulse_degrees)
                )
            elif classification_piece is not None:
                self.logger.info(
                    "ClassificationChannel: parking piece %s into wait zone with %.1f degrees"
                    % (classification_piece.uuid[:8], pulse_degrees)
                )

        if not self.irl.carousel_stepper.stopped:
            self._setOccupancyState("classification_channel.wait_transport_motion_complete")
            return None

        result = self.transport.advanceTransport()
        dropped_piece = result.piece_for_distribution_drop
        if dropped_piece is not None:
            if dropped_piece.carousel_rotated_at is None:
                dropped_piece.carousel_rotated_at = time.time()
            self.logger.info(
                "ClassificationChannel: piece %s dropped into distributor path"
                % dropped_piece.uuid[:8]
            )
            self.shared.set_distribution_gate(False, reason="piece_in_flight")
            self.shared.publish_piece_delivered(
                source=StationId.CLASSIFICATION,
                target=StationId.DISTRIBUTION,
                delivered_at_mono=time.monotonic(),
            )

        # Piece that just arrived in the wait zone (moved out of the hood)
        # — kick off Brickognize against the tracker crops collected during
        # its pass through the classification chamber.
        new_wait_piece = self.transport.getPieceAtWaitZone()
        if (
            new_wait_piece is not None
            and new_wait_piece.classification_status == ClassificationStatus.pending
        ):
            self._fireRecognize(new_wait_piece)

        return ClassificationChannelState.DETECTING

    def cleanup(self) -> None:
        super().cleanup()
        self.entered_at = None
        self.start_time = None
        self.command_sent = False

    # ------------------------------------------------------------------
    # Recognize helpers
    # ------------------------------------------------------------------

    def _fireRecognize(self, piece) -> None:
        crops = self._collectTrackedImages(piece)
        if len(crops) < MIN_RECOGNIZE_CROPS:
            self.logger.warning(
                "ClassificationChannel: only %d tracker crop(s) for piece %s — "
                "marking unknown and continuing"
                % (len(crops), piece.uuid[:8])
            )
            piece.classification_status = ClassificationStatus.unknown
            piece.color_id = ANY_COLOR
            piece.color_name = ANY_COLOR_NAME
            piece.classified_at = time.time()
            piece.updated_at = time.time()
            if self.event_queue is not None:
                self.event_queue.put(knownObjectToEvent(piece))
            return

        # Thumbnail: pick the sharpest of the tracker crops so the UI has
        # something to show while Brickognize is running.
        sharpest = self._pickSharpestCrop(crops)
        if sharpest is not None:
            piece.thumbnail = self._encodeImageBase64(sharpest)

        piece.classification_status = ClassificationStatus.classifying
        piece.updated_at = time.time()
        if self.event_queue is not None:
            self.event_queue.put(knownObjectToEvent(piece))

        self.transport.markPendingClassification(piece)
        self._classifyImagesAsync(piece, crops)
        self.logger.info(
            "ClassificationChannel: fired Brickognize for piece %s with %d tracker crops"
            % (piece.uuid[:8], len(crops))
        )

    def _collectTrackedImages(self, piece) -> list[np.ndarray]:
        track_id = getattr(piece, "tracked_global_id", None)
        if not isinstance(track_id, int) or self.vision is None:
            return []
        detail = self.vision.getFeederTrackHistoryDetail(track_id)
        if not isinstance(detail, dict):
            return []
        images: list[tuple[float, np.ndarray]] = []
        for segment in detail.get("segments", []):
            if not isinstance(segment, dict):
                continue
            source_role = segment.get("source_role")
            if source_role != "c_channel_3" and not is_auxiliary_classification_role(
                source_role
            ):
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

    def _classifyImagesAsync(self, piece, images: list[np.ndarray]) -> None:
        piece_uuid = piece.uuid
        event_queue = self.event_queue
        logger = self.logger
        transport = self.transport
        gc = self.gc

        def _run() -> None:
            try:
                result = _classifyImages(images)
                best_item, best_view = _pickBestItem(result, None)
                best_color = _pickBestColor(result, None)
                part_id = best_item["id"] if best_item else None
                color_id = best_color["id"] if best_color else ANY_COLOR
                color_name = best_color["name"] if best_color else ANY_COLOR_NAME
                confidence = best_item.get("score") if best_item else None
                preview_url = best_item.get("img_url") if best_item else None
                part_name = best_item.get("name") if best_item else None
                part_category = best_item.get("category") if best_item else None
            except Exception as exc:
                logger.error(
                    f"ClassificationChannel: Brickognize call failed: {exc}"
                )
                part_id = None
                color_id = ANY_COLOR
                color_name = ANY_COLOR_NAME
                confidence = None
                preview_url = None
                best_view = None
                part_name = None
                part_category = None

            resolved = transport.resolveClassification(
                piece_uuid,
                part_id,
                color_id,
                color_name,
                confidence,
                part_name=part_name,
                part_category=part_category,
            )
            if not resolved:
                logger.warning(
                    "ClassificationChannel: ignoring late Brickognize result for "
                    f"{piece_uuid[:8]}"
                )
                return
            piece.brickognize_preview_url = preview_url
            piece.brickognize_source_view = best_view or "tracked_multi"
            piece.updated_at = time.time()
            if event_queue is not None:
                event_queue.put(knownObjectToEvent(piece))
            logger.info(
                "ClassificationChannel: classified %s -> %s color=%s"
                % (piece_uuid[:8], part_id, color_name)
            )

        def _timeoutGuard() -> None:
            time.sleep(CLASSIFICATION_TIMEOUT_S)
            resolved = transport.resolveClassification(
                piece_uuid,
                None,
                ANY_COLOR,
                ANY_COLOR_NAME,
                None,
            )
            if not resolved:
                return
            piece.updated_at = time.time()
            if event_queue is not None:
                event_queue.put(knownObjectToEvent(piece))
            gc.runtime_stats.observeBlockedReason(
                "classification", "brickognize_timeout"
            )
            logger.warning(
                "ClassificationChannel: Brickognize timed out for "
                f"{piece_uuid[:8]} after {CLASSIFICATION_TIMEOUT_S:.1f}s; "
                "marking unknown so distribution can continue"
            )

        threading.Thread(target=_run, daemon=True).start()
        threading.Thread(target=_timeoutGuard, daemon=True).start()

    # ------------------------------------------------------------------
    # Image utils
    # ------------------------------------------------------------------

    @staticmethod
    def _decodeImageBase64(payload: object) -> np.ndarray | None:
        if not isinstance(payload, str) or not payload:
            return None
        try:
            raw = base64.b64decode(payload)
        except Exception:
            return None
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)

    @staticmethod
    def _encodeImageBase64(image: np.ndarray | None) -> Optional[str]:
        if image is None:
            return None
        ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return None
        return base64.b64encode(buffer).decode("utf-8")

    @staticmethod
    def _pickSharpestCrop(crops: list[np.ndarray]) -> np.ndarray | None:
        best_score = -1.0
        best_crop: np.ndarray | None = None
        for crop in crops:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
            score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            if score > best_score:
                best_score = score
                best_crop = crop
        return best_crop
