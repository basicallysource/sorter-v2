import time
from typing import Optional

from defs.known_object import ClassificationStatus, KnownObject, PieceStage
from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class RotatingAndCapturing(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rotation_started = False
        self._empty_streak = 0
        self._exit_seen = False

    def step(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()

        bboxes = self.cv.bboxesOnChannel()
        if not self._rotation_started and not bboxes:
            self._empty_streak += 1
            if self._empty_streak >= self.ctx.config.empty_streak_to_abort:
                self.stopStepper()
                self.logger.info(
                    f"{LOG_TAG} ROTATING_AND_CAPTURING -> IDLE "
                    f"(channel clear for {self._empty_streak} checks; nothing to rotate)"
                )
                return ClassificationChannelState.IDLE
            return None
        self._empty_streak = 0

        if not self._rotation_started:
            self.ctx.rotating_started_at = now
            self.ctx.last_capture_frame_ts = 0.0
            self.ctx.known_object = KnownObject(
                stage=PieceStage.created,
                classification_status=ClassificationStatus.pending,
                first_carousel_seen_ts=time.time(),
            )
            self.emitKnownObject()
            cfg = self.ctx.config
            if not self.startCaptureSweepMove(
                cfg.capture_sweep_output_deg,
                cfg.rotate_speed_usteps_per_s,
            ):
                self.logger.error(f"{LOG_TAG} could not start rotation — abort to IDLE")
                return ClassificationChannelState.IDLE
            self._rotation_started = True
            self.logger.info(
                f"{LOG_TAG} ROTATING_AND_CAPTURING started fixed sweep "
                f"(speed={cfg.rotate_speed_usteps_per_s} µsteps/s, "
                f"sweep={cfg.capture_sweep_output_deg:.1f} output°, "
                f"drop_angle={self.cc_config.drop_angle_deg:.1f}°)"
            )

        if now - self.ctx.rotating_started_at > self.ctx.config.rotate_timeout_s:
            self.logger.error(
                f"{LOG_TAG} rotation timeout after {self.ctx.config.rotate_timeout_s}s "
                f"(captures={len(self.ctx.captured_crops)}) — abort to DISCHARGING"
            )
            self.stopStepper()
            return ClassificationChannelState.REV01_DISCHARGING

        sample = self.cv.latestRawFrameSample()
        primary_bbox = self.cv.primaryBbox(bboxes)
        if sample is not None and primary_bbox is not None:
            frame, frame_ts = sample
            if frame_ts > self.ctx.last_capture_frame_ts:
                crop = self.cv.cropBbox(frame, primary_bbox, self.ctx.config.crop_padding_px)
                if crop is not None:
                    self.ctx.captured_crops.append(crop)
                    self.ctx.last_capture_frame_ts = frame_ts
                    elapsed = now - self.ctx.rotating_started_at
                    self.logger.info(
                        f"{LOG_TAG} capture #{len(self.ctx.captured_crops)} "
                        f"(t+{elapsed:.2f}s, ts={frame_ts:.3f}, "
                        f"bbox={primary_bbox}, shape={crop.shape})"
                    )
                    if self.ctx.known_object is not None:
                        encoded = self.encodeFrame(crop)
                        if encoded is not None:
                            self.ctx.known_object.latest_captured_crop = encoded
                            self.ctx.known_object.latest_captured_crop_ts = frame_ts
                            self.ctx.known_object.recognition_images.append(encoded)
                        self.emitKnownObject()

        in_exit, angles = self.anyBboxInExitZone(bboxes)
        if in_exit and not self._exit_seen:
            self._exit_seen = True
            self.logger.info(
                f"{LOG_TAG} observed exit-zone overlap during capture sweep "
                f"(bbox_angles={[round(a, 1) for a in angles]})"
            )

        stepper = getattr(self.irl, "carousel_stepper", None)
        if self._rotation_started and stepper is not None and bool(stepper.stopped):
            self.logger.info(
                f"{LOG_TAG} ROTATING_AND_CAPTURING -> CLASSIFYING "
                f"(sweep complete; captures={len(self.ctx.captured_crops)}, "
                f"exit_seen={self._exit_seen})"
            )
            return ClassificationChannelState.REV01_CLASSIFYING

        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        self._rotation_started = False
        self._empty_streak = 0
        self._exit_seen = False
