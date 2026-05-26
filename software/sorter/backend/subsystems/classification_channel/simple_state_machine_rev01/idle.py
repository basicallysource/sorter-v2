import time
from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class Idle(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._presence_streak = 0
        self._stuck_since: Optional[float] = None
        self._stuck_warned = False
        self.logger.info(f"{LOG_TAG} IDLE state constructed")

    def step(self) -> Optional[ClassificationChannelState]:
        bboxes = self.cv.bboxesOnChannel()
        if not bboxes:
            self._presence_streak = 0
            self._stuck_since = None
            self._stuck_warned = False
            self.setClassificationReady(True, "channel clear")
            return None

        actionable = self.bboxesOutsideExitZone(bboxes)
        if not actionable:
            now = time.monotonic()
            if self._stuck_since is None:
                self._stuck_since = now
            elapsed = now - self._stuck_since
            timeout = self.ctx.config.stuck_in_exit_zone_timeout_s
            if not self._stuck_warned and elapsed > timeout:
                self.logger.warning(
                    f"{LOG_TAG} piece appears stuck in exit zone for "
                    f"{elapsed:.1f}s (> {timeout:.1f}s) — needs better handling"
                )
                self._stuck_warned = True
            self._presence_streak = 0
            self.setClassificationReady(False, f"{len(bboxes)} piece(s) in exit zone")
            return None

        self._stuck_since = None
        self._stuck_warned = False
        self._presence_streak += 1
        self.setClassificationReady(False, f"{len(actionable)} bbox(es) on channel")
        if self._presence_streak >= self.ctx.config.presence_streak_to_start:
            self._presence_streak = 0
            self.ctx.reset()
            self.logger.info(
                f"{LOG_TAG} IDLE -> ROTATING_AND_CAPTURING "
                f"(piece confirmed on channel, count={len(actionable)})"
            )
            return ClassificationChannelState.REV01_ROTATING_AND_CAPTURING
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self._presence_streak = 0
        self._stuck_since = None
        self._stuck_warned = False
