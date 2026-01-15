import time
from typing import Optional
from .base_state import BaseState
from .shared_variables import SharedVariables
from defs.sorting_state import SortingState
from irl.config import IRLInterface
from global_config import GlobalConfig

SECOND_MOTOR_PULSE_MS = 1000
PAUSE_BETWEEN_PULSES_MS = 1000
THIRD_MOTOR_PULSE_MS = 1000


class Feeding(BaseState):
    def __init__(self, irl: IRLInterface, gc: GlobalConfig, shared: SharedVariables):
        super().__init__(irl, gc)
        self.shared = shared
        self.sequence_complete = False

    def step(self) -> Optional[SortingState]:
        self._ensureExecutionThreadStarted()
        if self.sequence_complete:
            return SortingState.IDLE
        return None

    def cleanup(self) -> None:
        super().cleanup()
        self.sequence_complete = False

    def _executionLoop(self) -> None:
        self.logger.info("Starting second motor pulse")
        self.irl.second_v_channel_dc_motor.setSpeed(
            self.gc.default_motor_speeds.second_v_channel
        )
        time.sleep(SECOND_MOTOR_PULSE_MS / 1000.0)

        if self._stop_event.is_set():
            self.irl.second_v_channel_dc_motor.setSpeed(0)
            return

        self.irl.second_v_channel_dc_motor.setSpeed(0)
        self.logger.info("Second motor pulse complete")

        time.sleep(PAUSE_BETWEEN_PULSES_MS / 1000.0)

        if self._stop_event.is_set():
            return

        self.logger.info("Starting third motor pulse")
        self.irl.third_v_channel_dc_motor.setSpeed(
            self.gc.default_motor_speeds.third_v_channel
        )
        time.sleep(THIRD_MOTOR_PULSE_MS / 1000.0)

        if self._stop_event.is_set():
            self.irl.third_v_channel_dc_motor.setSpeed(0)
            return

        self.irl.third_v_channel_dc_motor.setSpeed(0)
        self.logger.info("Third motor pulse complete")

        time.sleep(PAUSE_BETWEEN_PULSES_MS / 1000.0)

        self.sequence_complete = True
