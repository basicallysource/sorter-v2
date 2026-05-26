from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class Idle(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_ready_published: Optional[bool] = None
        self._presence_streak = 0
        self.logger.info(f"{LOG_TAG} IDLE state constructed")

    def step(self) -> Optional[ClassificationChannelState]:
        bboxes = self.cv.bboxesOnChannel()
        if bboxes:
            self._presence_streak += 1
            if self._last_ready_published is not False:
                self.setClassificationReady(False, f"{len(bboxes)} bbox(es) on channel")
                self._last_ready_published = False
            if self._presence_streak >= self.ctx.config.presence_streak_to_start:
                self._presence_streak = 0
                self.ctx.reset()
                self.logger.info(
                    f"{LOG_TAG} IDLE -> ROTATING_AND_CAPTURING "
                    f"(piece confirmed on channel, count={len(bboxes)})"
                )
                return ClassificationChannelState.REV01_ROTATING_AND_CAPTURING
            return None

        self._presence_streak = 0
        if self._last_ready_published is not True:
            self.setClassificationReady(True, "channel clear")
            self._last_ready_published = True
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self._last_ready_published = None
        self._presence_streak = 0
