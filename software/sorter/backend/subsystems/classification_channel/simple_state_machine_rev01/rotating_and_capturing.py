import time
from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import (
    CAPTURE_CADENCE_S,
    EMPTY_STREAK_TO_ABORT,
    LOG_TAG,
    MAX_CAPTURES,
    ROTATE_SPEED_USTEPS_PER_S,
    ROTATE_TIMEOUT_S,
)


class RotatingAndCapturing(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rotation_started = False
        self._empty_streak = 0

    def step(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()

        bboxes = self.cv.bboxesOnChannel()
        if not bboxes:
            self._empty_streak += 1
            if self._empty_streak >= EMPTY_STREAK_TO_ABORT:
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
            self.ctx.last_capture_at = 0.0
            if not self.startRotation(ROTATE_SPEED_USTEPS_PER_S):
                self.logger.error(f"{LOG_TAG} could not start rotation — abort to IDLE")
                return ClassificationChannelState.IDLE
            self._rotation_started = True
            self.logger.info(
                f"{LOG_TAG} ROTATING_AND_CAPTURING started "
                f"(speed={ROTATE_SPEED_USTEPS_PER_S} µsteps/s, "
                f"drop_angle={self.cc_config.drop_angle_deg:.1f}°, "
                f"drop_tol={self.cc_config.drop_tolerance_deg:.1f}°)"
            )

        if now - self.ctx.rotating_started_at > ROTATE_TIMEOUT_S:
            self.logger.error(
                f"{LOG_TAG} rotation timeout after {ROTATE_TIMEOUT_S}s "
                f"(captures={len(self.ctx.captured_frames)}) — abort to DISCHARGING"
            )
            self.stopStepper()
            return ClassificationChannelState.REV01_DISCHARGING

        if (
            len(self.ctx.captured_frames) < MAX_CAPTURES
            and (now - self.ctx.last_capture_at) >= CAPTURE_CADENCE_S
        ):
            frame = self.cv.latestRawFrame()
            if frame is not None:
                self.ctx.captured_frames.append(frame.copy())
                self.ctx.last_capture_at = now
                elapsed = now - self.ctx.rotating_started_at
                self.logger.info(
                    f"{LOG_TAG} capture #{len(self.ctx.captured_frames)} "
                    f"(t+{elapsed:.2f}s, shape={frame.shape})"
                )

        in_exit, angles = self.anyBboxInExitZone(bboxes)
        if in_exit:
            self.stopStepper()
            self.logger.info(
                f"{LOG_TAG} ROTATING_AND_CAPTURING -> CLASSIFYING "
                f"(bbox in exit zone; bbox_angles={[round(a, 1) for a in angles]}, "
                f"captures={len(self.ctx.captured_frames)})"
            )
            return ClassificationChannelState.REV01_CLASSIFYING

        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        self._rotation_started = False
        self._empty_streak = 0
