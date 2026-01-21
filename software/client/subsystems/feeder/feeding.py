import time
from typing import Optional
from states.base_state import BaseState
from subsystems.shared_variables import SharedVariables
from .states import FeederState
from irl.config import IRLInterface
from global_config import GlobalConfig

SECOND_MOTOR_PULSE_MS = 1000
PAUSE_BETWEEN_PULSES_MS = 1000
THIRD_MOTOR_PULSE_MS = 1000


class Feeding(BaseState):
    def __init__(self, irl: IRLInterface, gc: GlobalConfig, shared: SharedVariables):
        super().__init__(irl, gc)
        self.shared = shared

    def step(self) -> Optional[FeederState]:
        self._ensureExecutionThreadStarted()

        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.piece_ready = False
        self.irl.second_v_channel_dc_motor.setSpeed(0)
        self.irl.third_v_channel_dc_motor.setSpeed(0)

    def _executionLoop(self) -> None:
        return
        self.logger.info("Feeder: starting second motor pulse")
        self.irl.second_v_channel_dc_motor.setSpeed(
            self.gc.default_motor_speeds.second_v_channel
        )
        time.sleep(SECOND_MOTOR_PULSE_MS / 1000.0)

        if self._stop_event.is_set():
            self.irl.second_v_channel_dc_motor.setSpeed(0)
            return

        self.irl.second_v_channel_dc_motor.setSpeed(0)
        self.logger.info("Feeder: second motor pulse complete")

        time.sleep(PAUSE_BETWEEN_PULSES_MS / 1000.0)

        if self._stop_event.is_set():
            return

        self.logger.info("Feeder: starting third motor pulse")
        self.irl.third_v_channel_dc_motor.setSpeed(
            self.gc.default_motor_speeds.third_v_channel
        )
        time.sleep(THIRD_MOTOR_PULSE_MS / 1000.0)

        if self._stop_event.is_set():
            self.irl.third_v_channel_dc_motor.setSpeed(0)
            return

        self.irl.third_v_channel_dc_motor.setSpeed(0)
        self.logger.info("Feeder: third motor pulse complete, piece ready")
