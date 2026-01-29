import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from irl.config import IRLInterface
from global_config import GlobalConfig


class Feeding(BaseState):
    def __init__(self, irl: IRLInterface, gc: GlobalConfig, shared: SharedVariables):
        super().__init__(irl, gc)
        self.shared = shared

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        if not self.shared.classification_ready:
            return FeederState.IDLE
        return None

    def _executionLoop(self) -> None:
        fc = self.gc.feeder_config
        while not self._stop_event.is_set():
            self.irl.first_c_channel_rotor_stepper.moveSteps(
                -fc.steps_per_pulse, fc.normal_delay_us
            )
            time.sleep(3)
            self.irl.second_c_channel_rotor_stepper.moveSteps(
                -fc.steps_per_pulse, fc.normal_delay_us
            )
            time.sleep(3)
            self.irl.third_c_channel_rotor_stepper.moveSteps(
                -fc.steps_per_pulse, fc.normal_delay_us
            )
            time.sleep(3)
            if fc.delay_between_pulse_ms > 0:
                time.sleep(fc.delay_between_pulse_ms / 1000.0)

    def cleanup(self) -> None:
        super().cleanup()
