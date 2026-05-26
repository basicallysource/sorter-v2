import time
from typing import Optional

from defs.known_object import PieceStage
from subsystems.classification_channel.states import ClassificationChannelState

from .base import Rev01BaseState
from .constants import LOG_TAG


class Discharging(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._kickoff_started = False

    def step(self) -> Optional[ClassificationChannelState]:
        now = time.monotonic()
        self.setClassificationReady(False, "discharging")

        if not self._kickoff_started:
            self.ctx.discharging_started_at = now
            cfg = self.ctx.config
            if not self.startOutputMove(
                cfg.kick_off_output_deg,
                cfg.discharge_speed_usteps_per_s,
            ):
                self.logger.error(
                    f"{LOG_TAG} could not start kick-off move — abort to IDLE"
                )
                return ClassificationChannelState.IDLE
            self._kickoff_started = True
            self.logger.info(
                f"{LOG_TAG} DISCHARGING kick-off started "
                f"(output={cfg.kick_off_output_deg:.1f}°, "
                f"speed={cfg.discharge_speed_usteps_per_s} µsteps/s)"
            )

        if now - self.ctx.discharging_started_at > self.ctx.config.discharge_timeout_s:
            self.logger.error(
                f"{LOG_TAG} discharge timeout after {self.ctx.config.discharge_timeout_s}s — "
                f"forcing return to IDLE"
            )
            self.stopStepper()
            return ClassificationChannelState.IDLE

        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is not None and not bool(stepper.stopped):
            return None

        self._stampDistributed()
        elapsed = now - self.ctx.discharging_started_at
        self.logger.info(
            f"{LOG_TAG} DISCHARGING -> IDLE (kick-off complete after {elapsed:.2f}s)"
        )
        return ClassificationChannelState.IDLE

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
        self._kickoff_started = False
