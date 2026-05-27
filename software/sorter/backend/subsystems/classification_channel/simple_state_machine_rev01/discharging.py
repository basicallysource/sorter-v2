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
        self._stepper_done_at: Optional[float] = None

    def step(self) -> Optional[ClassificationChannelState]:
        self.setClassificationReady(False, "discharging")

        if not self._kickoff_started:
            self.ctx.discharging_started_at = time.monotonic()
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

        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is not None and not bool(stepper.stopped):
            return None

        if self._stepper_done_at is None:
            self._stepper_done_at = time.monotonic()

        pause_s = self.ctx.config.post_discharge_pause_ms / 1000.0
        if time.monotonic() - self._stepper_done_at < pause_s:
            return None

        self._stampDistributed()
        elapsed = time.monotonic() - self.ctx.discharging_started_at
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
        self._stepper_done_at = None
