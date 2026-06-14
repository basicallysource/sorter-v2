import time
from typing import Optional

from defs.known_object import (
    ClassificationStatus,
    KnownObject,
    PieceStage,
    RecognitionImage,
)
from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class Capturing(Rev01BaseState):
    """Photograph the piece AT REST — no carousel move.

    A piece lands on the channel and sits still while we crop the primary bbox
    from a short burst of frames. The moment the burst ends we spawn the
    Brickognize request so classification runs concurrently with the subsequent
    reverse move to the precise zone (MOVING_TO_PRECISE), and the result is
    collected later in AWAITING_DISTRIBUTION. The old forward 180° sweep is gone.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._empty_streak = 0
        self._exit_seen = False
        self._classify_spawned = False

    def step(self) -> Optional[ClassificationChannelState]:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is not None:
            return self._step_perception(perception_service)
        return self._step_legacy()

    # ---- active perception path ----

    def _step_perception(self, perception_service) -> Optional[ClassificationChannelState]:
        now = time.monotonic()
        self.setClassificationReady(False, "capturing")

        raw = perception_service.read_bboxes_and_frame(4)
        if raw is None:
            bboxes: list = []
            frame_bgr = None
            frame_ts = 0.0
        else:
            raw_bboxes, perc_frame = raw
            bboxes = [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in raw_bboxes]
            frame_bgr = perc_frame.bgr
            frame_ts = float(perc_frame.timestamp)

        if self.ctx.capturing_started_at == 0.0:
            if not bboxes:
                self._empty_streak += 1
                if self._empty_streak >= self.ctx.config.empty_streak_to_abort:
                    self.logger.info(
                        f"{LOG_TAG} CAPTURING -> IDLE "
                        f"(channel clear for {self._empty_streak} checks; nothing to capture)"
                    )
                    return ClassificationChannelState.IDLE
                return None
            self._empty_streak = 0
            self.ctx.capturing_started_at = now
            self.ctx.last_capture_frame_ts = 0.0
            self.ctx.known_object = KnownObject(
                stage=PieceStage.created,
                classification_status=ClassificationStatus.pending,
                first_carousel_seen_ts=time.time(),
            )
            self.emitKnownObject()
            self.logger.info(f"{LOG_TAG} CAPTURING started (at rest, no carousel move)")

        self._captureCrop(now, frame_bgr, frame_ts, bboxes)

        c4_state = perception_service.read_state(4)
        if self.ctx.observeMultiFeed(
            int(c4_state.n_pieces), float(c4_state.ts), self.ctx.config.multi_feed_confirm_reads
        ):
            self.logger.info(
                f"{LOG_TAG} multi-feed: {c4_state.n_pieces} pieces on channel during "
                f"capture — routing to MISC, will clear all on discharge"
            )
        if c4_state.in_exit and not self._exit_seen:
            self._exit_seen = True

        return self._maybeFinishCapture(now)

    # ---- legacy (non-perception) fallback ----

    def _step_legacy(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()
        self.setClassificationReady(False, "capturing")

        bboxes, bbox_frame = self.cv.bboxesAndFrameOnChannel()
        frame_bgr = bbox_frame.raw if bbox_frame is not None else None
        frame_ts = float(bbox_frame.timestamp) if bbox_frame is not None else 0.0

        if self.ctx.capturing_started_at == 0.0:
            if not bboxes:
                self._empty_streak += 1
                if self._empty_streak >= self.ctx.config.empty_streak_to_abort:
                    self.logger.info(f"{LOG_TAG} CAPTURING -> IDLE (nothing to capture)")
                    return ClassificationChannelState.IDLE
                return None
            self._empty_streak = 0
            self.ctx.capturing_started_at = now
            self.ctx.last_capture_frame_ts = 0.0
            self.ctx.known_object = KnownObject(
                stage=PieceStage.created,
                classification_status=ClassificationStatus.pending,
                first_carousel_seen_ts=time.time(),
            )
            self.emitKnownObject()

        self._captureCrop(now, frame_bgr, frame_ts, bboxes)
        legacy_ts = frame_ts if frame_ts else now
        self.ctx.observeMultiFeed(
            len(bboxes), legacy_ts, self.ctx.config.multi_feed_confirm_reads
        )
        return self._maybeFinishCapture(now)

    # ---- shared ----

    def _captureCrop(self, now: float, frame_bgr, frame_ts: float, bboxes: list) -> None:
        if frame_bgr is None or not bboxes:
            return
        if frame_ts <= self.ctx.last_capture_frame_ts:
            return
        primary_bbox = self.cv.primaryBbox(bboxes)
        if primary_bbox is None:
            return
        crop = self.cv.cropBbox(frame_bgr, primary_bbox, self.ctx.config.crop_padding_px)
        if crop is None:
            return
        self.ctx.captured_crops.append(crop)
        self.ctx.captured_crop_timestamps.append(frame_ts)
        self.ctx.last_capture_frame_ts = frame_ts
        elapsed = now - self.ctx.capturing_started_at
        self.logger.info(
            f"{LOG_TAG} capture #{len(self.ctx.captured_crops)} "
            f"(t+{elapsed:.2f}s, ts={frame_ts:.3f}, bbox={primary_bbox}, shape={crop.shape})"
        )
        if self.ctx.known_object is not None:
            encoded = self.encodeFrame(crop)
            if encoded is not None:
                self.ctx.known_object.latest_captured_crop = encoded
                self.ctx.known_object.latest_captured_crop_ts = frame_ts
                self.ctx.known_object.recognition_image_set.append(
                    RecognitionImage(
                        image=encoded,
                        source="c4_burst",
                        used=False,
                        ts=frame_ts,
                        channel=4,
                        created_at=frame_ts,
                    )
                )
            self.emitKnownObject()

    def _maybeFinishCapture(self, now: float) -> Optional[ClassificationChannelState]:
        if self.ctx.capturing_started_at == 0.0:
            return None
        elapsed_ms = (now - self.ctx.capturing_started_at) * 1000.0
        n = len(self.ctx.captured_crops)
        done = n >= self.ctx.config.max_captures or elapsed_ms >= self.ctx.config.capture_at_rest_ms
        if not done:
            return None

        self.ctx.classify_started_at = now
        all_captures = list(self.ctx.captured_crops)
        # Burst selection + upstream-match injection happen on the classify
        # thread (selectRecognitionCrops needs the upstream count to know how
        # many burst slots are left), so we hand it the full burst here.
        if all_captures:
            self.logger.info(
                f"{LOG_TAG} CAPTURING -> MOVING_TO_PRECISE "
                f"(captured {n}, classifying off-thread; exit_seen={self._exit_seen})"
            )
            self.spawnClassifyThread(all_captures)
        else:
            self.logger.warning(
                f"{LOG_TAG} CAPTURING -> MOVING_TO_PRECISE with zero captures — "
                f"skipping Brickognize, will route unknown"
            )
            self.ctx.classification_error = "no_captures"
        self._classify_spawned = True
        return ClassificationChannelState.REV01_MOVING_TO_PRECISE

    def cleanup(self) -> None:
        super().cleanup()
        self._empty_streak = 0
        self._exit_seen = False
        self._classify_spawned = False
