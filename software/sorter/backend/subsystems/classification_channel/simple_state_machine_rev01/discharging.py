import time
from typing import Optional

from defs.known_object import PieceStage
from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


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
            self._stampDistributed()
            cfg = self.ctx.config
            if not self.startRotation(cfg.discharge_speed_usteps_per_s):
                self.logger.error(
                    f"{LOG_TAG} could not start discharge rotation — abort to IDLE"
                )
                return ClassificationChannelState.IDLE
            self._rotation_started = True
            self.logger.info(
                f"{LOG_TAG} DISCHARGING started (speed={cfg.discharge_speed_usteps_per_s} µsteps/s)"
            )

        if now - self.ctx.discharging_started_at > self.ctx.config.discharge_timeout_s:
            self.logger.error(
                f"{LOG_TAG} discharge timeout after {self.ctx.config.discharge_timeout_s}s — "
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

    def _stampDistributed(self) -> None:
        obj = self.ctx.known_object
        if obj is None:
            return
        obj.stage = PieceStage.distributed
        obj.distributed_at = time.time()
        obj.destination_bin = (0, 0, 0)
        self.emitKnownObject()

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        self._rotation_started = False
