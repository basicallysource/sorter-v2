import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from runtime_variables import RuntimeVariables
from .states import FeederState
from .frame_analysis import getNextFeederState, TREAT_1_AND_2_AS_ONE
from irl.config import IRLInterface
from global_config import GlobalConfig
from vision.vision_manager import VisionManager


class V2Loading(BaseState):
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
        return getNextFeederState(masks_by_class, self.gc, FeederState.V2_LOADING)

    def cleanup(self) -> None:
        super().cleanup()
        self.irl.second_v_channel_dc_motor.backstop(self.rv.get("v2_pulse_speed"))
        if TREAT_1_AND_2_AS_ONE:
            self.irl.first_v_channel_dc_motor.backstop(self.rv.get("v1_pulse_speed"))

    def _executionLoop(self) -> None:
        v2_motor = self.irl.second_v_channel_dc_motor
        v1_motor = self.irl.first_v_channel_dc_motor

        while not self._stop_event.is_set():
            v2_pulse_ms = self.rv.get("v2_pulse_length_ms")
            v2_speed = self.rv.get("v2_pulse_speed")
            pause_ms = self.rv.get("pause_ms")

            if TREAT_1_AND_2_AS_ONE:
                v1_pulse_ms = self.rv.get("v1_pulse_length_ms")
                v1_speed = self.rv.get("v1_pulse_speed")

                # run both motors
                v2_motor.setSpeed(v2_speed)
                v1_motor.setSpeed(v1_speed)
                max_pulse = max(v1_pulse_ms, v2_pulse_ms)
                time.sleep(max_pulse / 1000.0)
                v2_motor.backstop(v2_speed)
                v1_motor.backstop(v1_speed)
            else:
                # run only v2
                v2_motor.setSpeed(v2_speed)
                time.sleep(v2_pulse_ms / 1000.0)
                v2_motor.backstop(v2_speed)

            time.sleep(pause_ms / 1000.0)
