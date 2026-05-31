import time
from typing import Optional

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
            output_deg = float(cfg.kick_off_output_deg)
            self._logDischargePlan(output_deg)
            if not self.startOutputMove(
                output_deg,
                cfg.discharge_speed_usteps_per_s,
            ):
                self.logger.error(
                    f"{LOG_TAG} could not start discharge move — abort to IDLE"
                )
                return ClassificationChannelState.IDLE
            self._kickoff_started = True
            self.logger.info(
                f"{LOG_TAG} DISCHARGING move-to-exit started "
                f"(output={output_deg:.1f}°, "
                f"speed={cfg.discharge_speed_usteps_per_s} µsteps/s)"
            )

        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is not None and not bool(stepper.stopped):
            return None

        if self._stepper_done_at is None:
            self._stepper_done_at = time.monotonic()
            # The piece has just been flung out of the C-channel into the chute,
            # which distribution already aimed at the target bin during
            # POSITIONING. Promote it from the positioning slot to the drop slot
            # and drop the gate — distribution's Ready state is holding on the
            # gate and advances to Sending (commit + record) when it goes False.
            self._releaseToDistribution()

        pause_s = self.ctx.config.post_discharge_pause_ms / 1000.0
        if time.monotonic() - self._stepper_done_at < pause_s:
            return None

        elapsed = time.monotonic() - self.ctx.discharging_started_at
        self.logger.info(
            f"{LOG_TAG} DISCHARGING -> VERIFYING_DISCHARGE (move complete after {elapsed:.2f}s)"
        )
        return ClassificationChannelState.REV01_VERIFYING_DISCHARGE

    def _releaseToDistribution(self) -> None:
        obj = self.ctx.known_object
        # advanceTransport (non-dynamic) shifts wait -> exit, so the piece
        # distribution positioned for now occupies the drop slot it reads from.
        self.transport.advanceTransport()
        self.shared.set_distribution_gate(False, reason="rev01_discharged")
        if obj is not None:
            self.logger.info(
                f"{LOG_TAG} DISCHARGING: released piece {obj.uuid[:8]} to distribution"
            )

    def _logDischargePlan(self, output_deg: float) -> None:
        perception_service = getattr(self.gc, "perception_service", None)
        if perception_service is not None:
            raw = perception_service.read_bboxes_and_frame(4)
            bboxes = [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in raw[0]] if raw else []
            center = perception_service.channel_center(4)
        else:
            bboxes = self.cv.bboxesOnChannel()
            center = self.cv.channelCenter()
        primary = self.cv.primaryBbox(bboxes)
        if primary is None:
            self.logger.info(
                f"{LOG_TAG} discharge plan: fixed_output={output_deg:.1f}° "
                f"(no bbox visible)"
            )
            return
        if center is None:
            self.logger.info(
                f"{LOG_TAG} discharge plan: fixed_output={output_deg:.1f}° "
                f"(no carousel center geometry)"
            )
            return
        piece_angle = self.cv.bboxAngleDeg(primary, center)
        target_angle = (
            float(self.cc_config.drop_angle_deg) + float(self.cc_config.drop_tolerance_deg)
        ) % 360.0
        computed_output_deg = max(2.0, min((target_angle - piece_angle) % 360.0, 270.0))
        self.logger.info(
            f"{LOG_TAG} discharge plan: fixed_output={output_deg:.1f}° "
            f"computed_output={computed_output_deg:.1f}° "
            f"piece_angle={piece_angle:.1f}° target_angle={target_angle:.1f}° "
            f"drop_angle={float(self.cc_config.drop_angle_deg):.1f}° "
            f"drop_tolerance={float(self.cc_config.drop_tolerance_deg):.1f}° "
            f"bbox={primary} center=({float(center[0]):.1f},{float(center[1]):.1f})"
        )

    def cleanup(self) -> None:
        super().cleanup()
        self.stopStepper()
        self._kickoff_started = False
        self._stepper_done_at = None
