import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from runtime_variables import RuntimeVariables
from .states import FeederState
from .frame_analysis import getNextFeederState
from irl.config import IRLInterface
from global_config import GlobalConfig
from vision.vision_manager import VisionManager


class V3DispensingSlow(BaseState):
    def __init__(
        self,
        irl: IRLInterface,
        gc: GlobalConfig,
        shared: SharedVariables,
        vision: VisionManager,
        rv: RuntimeVariables,
    ):
        super().__init__(irl, gc)
        self.shared = shared
        self.vision = vision
        self.rv = rv

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        if not self.shared.classification_ready:
            return FeederState.IDLE

        masks_by_class = self.vision.getFeederMasksByClass()
        return getNextFeederState(
            masks_by_class, self.gc, FeederState.V3_DISPENSING_SLOW
        )

    def cleanup(self) -> None:
        super().cleanup()
        self.irl.third_v_channel_dc_motor.backstop(self.rv.get("slow_v3_pulse_speed"))

    def _executionLoop(self) -> None:
        motor = self.irl.third_v_channel_dc_motor

        while not self._stop_event.is_set():
            pulse_ms = self.rv.get("slow_v3_pulse_length_ms")
            pause_ms = self.rv.get("pause_ms")
            speed = self.rv.get("slow_v3_pulse_speed")
            motor.setSpeed(speed)
            time.sleep(pulse_ms / 1000.0)
            motor.backstop(speed)
            time.sleep(pause_ms / 1000.0)
