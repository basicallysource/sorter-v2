import time
from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import DISCHARGE_SPEED_USTEPS_PER_S, DISCHARGE_TIMEOUT_S, LOG_TAG


class Discharging(Rev01BaseState):
    """Keep rotating until the channel reads clear — the piece has fallen off
    C4 into the distributor chute. No bin targeting in rev01."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rotation_started = False

    def step(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()

        if not self._rotation_started:
            self.ctx.discharging_started_at = now
            if not self.startRotation(DISCHARGE_SPEED_USTEPS_PER_S):
                self.logger.error(
                    f"{LOG_TAG} could not start discharge rotation — abort to IDLE"
                )
                return ClassificationChannelState.IDLE
            self._rotation_started = True
            self.logger.info(
                f"{LOG_TAG} DISCHARGING started (speed={DISCHARGE_SPEED_USTEPS_PER_S} µsteps/s)"
            )

        if now - self.ctx.discharging_started_at > DISCHARGE_TIMEOUT_S:
            self.logger.error(
                f"{LOG_TAG} discharge timeout after {DISCHARGE_TIMEOUT_S}s — "
                f"forcing return to IDLE"
            )
            self.stopStepper()
            return ClassificationChannelState.IDLE

        if not self.cv.bboxesOnChannel():
            self.stopStepper()
            elapsed = now - self.ctx.discharging_started_at
            self.logger.info(
                f"{LOG_TAG} DISCHARGING -> IDLE (channel clear after {elapsed:.2f}s)"
            )
            return ClassificationChannelState.IDLE

        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        self._rotation_started = False
