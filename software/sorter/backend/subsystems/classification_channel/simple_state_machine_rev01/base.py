from global_config import GlobalConfig
from irl.config import IRLConfig, IRLInterface
from piece_transport import ClassificationChannelTransport
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables

from .constants import LOG_TAG
from .context import SimpleStateMachineRev01Context
from .vision import Rev01Vision


class Rev01BaseState(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        irl_config: IRLConfig,
        gc: GlobalConfig,
        shared: SharedVariables,
        transport: ClassificationChannelTransport,
        vision,
        event_queue,
        context: SimpleStateMachineRev01Context,
    ):
        super().__init__(irl, gc)
        self.irl_config = irl_config
        self.shared = shared
        self.transport = transport
        self.event_queue = event_queue
        self.ctx = context
        self.cc_config = irl_config.classification_channel_config
        self.cv = Rev01Vision(vision, gc)

    def setClassificationReady(self, ready: bool, reason: str) -> None:
        setter = getattr(self.shared, "set_classification_gate", None)
        if callable(setter):
            setter(ready, reason=reason)
        else:
            self.shared.classification_ready = ready
        self.logger.info(f"{LOG_TAG} classification_ready -> {ready} ({reason})")

    def stopStepper(self) -> None:
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None or not hasattr(stepper, "move_at_speed"):
            return
        try:
            stepper.move_at_speed(0)
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} stepper stop failed: {exc}")

    def startRotation(self, speed_usteps_per_s: int) -> bool:
        stepper = getattr(self.irl, "carousel_stepper", None)
        if stepper is None:
            self.logger.error(f"{LOG_TAG} carousel_stepper missing — cannot rotate")
            return False
        try:
            stepper.set_speed_limits(16, max(16, speed_usteps_per_s))
        except Exception as exc:
            self.logger.warning(f"{LOG_TAG} set_speed_limits failed: {exc}")
        try:
            ok = bool(stepper.move_at_speed(int(speed_usteps_per_s)))
        except Exception as exc:
            self.logger.error(f"{LOG_TAG} move_at_speed failed: {exc}")
            return False
        if not ok:
            self.logger.error(f"{LOG_TAG} move_at_speed not acknowledged")
        return ok

    def anyBboxInExitZone(
        self, bboxes: list[tuple[int, int, int, int]]
    ) -> tuple[bool, list[float]]:
        center = self.cv.channelCenter()
        if center is None:
            return False, []
        angles = [self.cv.bboxAngleDeg(b, center) for b in bboxes]
        hit = any(
            self.cv.bboxInExitZone(
                b, center, self.cc_config.drop_angle_deg, self.cc_config.drop_tolerance_deg
            )
            for b in bboxes
        )
        return hit, angles
