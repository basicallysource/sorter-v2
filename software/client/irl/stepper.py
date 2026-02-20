from typing import TYPE_CHECKING
from global_config import GlobalConfig
from blob_manager import getStepperPosition, setStepperPosition

if TYPE_CHECKING:
    from .mcu import MCU

STEPS_PER_REV = 200
DEFAULT_MICROSTEPPING = 8  # 1600 steps/rev total
BASE_DELAY_US = 400
DEFAULT_ACCEL_START_DELAY_MULTIPLIER = 2
DEFAULT_ACCEL_STEPS = 24


class Stepper:
    def __init__(
        self,
        gc: GlobalConfig,
        mcu: "MCU",
        step_pin: int,
        dir_pin: int,
        enable_pin: int,
        name: str,
        steps_per_rev: int = STEPS_PER_REV,
        microstepping: int = DEFAULT_MICROSTEPPING,
        default_delay_us: int = BASE_DELAY_US,
        default_accel_start_delay_us: int | None = None,
        default_accel_steps: int = DEFAULT_ACCEL_STEPS,
        default_decel_steps: int | None = None,
    ):
        self.gc = gc
        self.mcu = mcu
        self.step_pin = step_pin
        self.dir_pin = dir_pin
        self.enable_pin = enable_pin
        self.name = name
        self.steps_per_rev = steps_per_rev
        self.microstepping = microstepping
        self.default_delay_us = default_delay_us
        self.default_accel_start_delay_us = (
            default_delay_us * DEFAULT_ACCEL_START_DELAY_MULTIPLIER
            if default_accel_start_delay_us is None
            else default_accel_start_delay_us
        )
        self.default_accel_steps = default_accel_steps
        self.default_decel_steps = (
            default_accel_steps if default_decel_steps is None else default_decel_steps
        )
        self.total_steps_per_rev = steps_per_rev * microstepping
        self.current_position_steps = getStepperPosition(name)

        logger = gc.logger
        logger.info(
            f"Initialized Stepper '{name}' with step={step_pin}, dir={dir_pin}, enable={enable_pin}, position={self.current_position_steps}"
        )

        mcu.command("P", step_pin, 1)
        mcu.command("P", dir_pin, 1)
        mcu.command("P", enable_pin, 1)
        mcu.command("D", enable_pin, 0)

    def rotate(
        self,
        deg: float,
        delay_us: int | None = None,
        accel_start_delay_us: int | None = None,
        accel_steps: int | None = None,
        decel_steps: int | None = None,
    ) -> None:
        if delay_us is None:
            delay_us = self.default_delay_us
        if accel_start_delay_us is None:
            accel_start_delay_us = self.default_accel_start_delay_us
        if accel_steps is None:
            accel_steps = self.default_accel_steps
        if decel_steps is None:
            decel_steps = self.default_decel_steps
        steps = int((deg / 360.0) * self.total_steps_per_rev)
        queue_size = self.mcu.command_queue.qsize()
        worker_alive = self.mcu.worker_thread.is_alive()
        self.gc.logger.info(
            f"Stepper '{self.name}' rotating {deg}° ({steps} steps, delay={delay_us}us, accel_start={accel_start_delay_us}us, accel_steps={accel_steps}, decel_steps={decel_steps}, pre_queue={queue_size}, worker_alive={worker_alive})"
        )
        self.mcu.command(
            "T",
            self.step_pin,
            self.dir_pin,
            steps,
            delay_us,
            accel_start_delay_us,
            accel_steps,
            decel_steps,
        )
        self.current_position_steps += steps
        setStepperPosition(self.name, self.current_position_steps)

    def moveSteps(
        self,
        steps: int,
        delay_us: int | None = None,
        accel_start_delay_us: int | None = None,
        accel_steps: int | None = None,
        decel_steps: int | None = None,
    ) -> None:
        if delay_us is None:
            delay_us = self.default_delay_us
        if accel_start_delay_us is None:
            accel_start_delay_us = self.default_accel_start_delay_us
        if accel_steps is None:
            accel_steps = self.default_accel_steps
        if decel_steps is None:
            decel_steps = self.default_decel_steps
        self.mcu.command(
            "T",
            self.step_pin,
            self.dir_pin,
            steps,
            delay_us,
            accel_start_delay_us,
            accel_steps,
            decel_steps,
        )
        self.current_position_steps += steps
        setStepperPosition(self.name, self.current_position_steps)

    def disable(self) -> None:
        self.mcu.command("D", self.enable_pin, 1)
