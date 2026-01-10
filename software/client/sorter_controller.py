from defs.sorter_controller import SorterLifecycle
from irl.config import IRLInterface
from global_config import GlobalConfig
import time

SECOND_MOTOR_PULSE_MS = 1000
PAUSE_BETWEEN_PULSES_MS = 1000
THIRD_MOTOR_PULSE_MS = 1000


class SorterController:
    def __init__(self, irl: IRLInterface, gc: GlobalConfig):
        self.state = SorterLifecycle.INITIALIZING
        self.irl = irl
        self.gc = gc

    def start(self) -> None:
        self.state = SorterLifecycle.RUNNING

    def stop(self) -> None:
        self.state = SorterLifecycle.READY

    def step(self) -> None:
        logger = self.gc.logger

        logger.info("Starting second motor pulse")
        self.irl.second_v_channel_dc_motor.setSpeed(
            self.gc.default_motor_speeds.second_v_channel
        )
        time.sleep(SECOND_MOTOR_PULSE_MS / 1000.0)
        self.irl.second_v_channel_dc_motor.setSpeed(0)
        logger.info("Second motor pulse complete")

        time.sleep(PAUSE_BETWEEN_PULSES_MS / 1000.0)

        logger.info("Starting third motor pulse")
        self.irl.third_v_channel_dc_motor.setSpeed(
            self.gc.default_motor_speeds.third_v_channel
        )
        time.sleep(THIRD_MOTOR_PULSE_MS / 1000.0)
        self.irl.third_v_channel_dc_motor.setSpeed(0)
        logger.info("Third motor pulse complete")

        time.sleep(PAUSE_BETWEEN_PULSES_MS / 1000.0)
