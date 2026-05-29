import time
from typing import Optional

from subsystems.classification_channel.states import ClassificationChannelState
from subsystems.common.jitter_recovery import JitterParams, JitterPhase, JitterSequence

from .base import Rev01BaseState
from .constants import LOG_TAG


class VerifyingDischarge(Rev01BaseState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._entered_at: Optional[float] = None
        self._seq: Optional[JitterSequence] = None

    def step(self) -> Optional[ClassificationChannelState]:
        self.setClassificationReady(False, "verifying_discharge")
        cfg = self.ctx.config
        now = time.monotonic()

        if self._entered_at is None:
            self._entered_at = now

        seq = self._getOrBuildSeq(cfg)

        # Settle window before the first vision re-check. We only honor this
        # when no jitter sequence has been started yet — once we're mid-jitter
        # the sequence drives its own timing.
        if seq is None or not seq.is_active:
            if (now - self._entered_at) * 1000.0 < cfg.verify_discharge_wait_ms:
                return None

        in_exit = self._pieceStillInExitZone()

        # Happy path: nothing in the exit zone after the settle wait.
        if seq is None or not seq.is_active:
            if not in_exit:
                self.logger.info(
                    f"{LOG_TAG} VERIFYING_DISCHARGE -> IDLE (exit zone clear after "
                    f"{cfg.verify_discharge_wait_ms}ms settle)"
                )
                self.stampDistributed()
                return ClassificationChannelState.IDLE

            # Stuck. Kick off the jitter sequence (may fail to build if the
            # stepper isn't available — bail to IDLE with a warning so we
            # don't wedge forever).
            if seq is None:
                self.logger.warning(
                    f"{LOG_TAG} VERIFYING_DISCHARGE: jitter sequence unavailable — "
                    f"giving up, returning to IDLE"
                )
                self.stampDistributed()
                return ClassificationChannelState.IDLE
            self.logger.info(
                f"{LOG_TAG} VERIFYING_DISCHARGE: piece still in exit zone — "
                f"starting jitter recovery (up to {cfg.verify_discharge_max_jitter_attempts} attempts)"
            )
            seq.start()

        phase = seq.tick(still_stuck=in_exit, now=now)

        if phase == JitterPhase.CLEARED:
            self.logger.info(
                f"{LOG_TAG} VERIFYING_DISCHARGE -> IDLE (jitter cleared the piece)"
            )
            self.stampDistributed()
            return ClassificationChannelState.IDLE

        if phase == JitterPhase.EXHAUSTED:
            self.logger.warning(
                f"{LOG_TAG} VERIFYING_DISCHARGE: piece still in exit zone after "
                f"{cfg.verify_discharge_max_jitter_attempts} jitter attempts — "
                f"giving up, returning to IDLE"
            )
            self.stampDistributed()
            return ClassificationChannelState.IDLE

        return None

    def _pieceStillInExitZone(self) -> bool:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is not None:
            return bool(perception_service.read_state(4).in_exit)
        bboxes = self.cv.bboxesOnChannel()
        in_exit, _ = self.anyBboxInExitZone(bboxes)
        return in_exit

    def _getOrBuildSeq(self, cfg) -> Optional[JitterSequence]:
        if self._seq is not None:
            return self._seq
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None:
            return None
        self._seq = JitterSequence(
            stepper,
            JitterParams(
                amplitude_motor_deg=cfg.jitter_amplitude_motor_deg,
                cycles=int(cfg.jitter_cycles),
                speed_usteps_per_s=int(cfg.jitter_speed_usteps_per_s),
                accel_usteps_per_s2=int(cfg.jitter_accel_usteps_per_s2),
                pause_ms=int(cfg.jitter_pause_ms),
                max_attempts=int(cfg.verify_discharge_max_jitter_attempts),
            ),
            label=f"{LOG_TAG} verify-discharge",
            logger=self.logger,
        )
        return self._seq

    def cleanup(self) -> None:
        super().cleanup()
        if self._seq is not None:
            self._seq.reset()
        self._entered_at = None
