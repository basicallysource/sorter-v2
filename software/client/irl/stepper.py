import time
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
BLOCKING_MOVE_RETRY_COUNT = 10
# if this works, just do this to the arudu firmware generally
RETRY_DELAY_MS = 250


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
        if self.name == "chute":
            queue_size = self.mcu.command_queue.qsize()
            worker_alive = self.mcu.worker_thread.is_alive()
            next_position_steps = self.current_position_steps + steps
            self.gc.logger.info(
                f"Stepper '{self.name}' moveSteps steps={steps} delay={delay_us}us accel_start={accel_start_delay_us}us accel_steps={accel_steps} decel_steps={decel_steps} pos={self.current_position_steps}->{next_position_steps} pre_queue={queue_size} worker_alive={worker_alive}"
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

    def rotateBlocking(
        self,
        deg: float,
        timeout_ms: int,
        delay_us: int | None = None,
        accel_start_delay_us: int | None = None,
        accel_steps: int | None = None,
        decel_steps: int | None = None,
    ) -> str:
        steps = int((deg / 360.0) * self.total_steps_per_rev)
        return self.moveStepsBlocking(
            steps,
            timeout_ms,
            delay_us=delay_us,
            accel_start_delay_us=accel_start_delay_us,
            accel_steps=accel_steps,
            decel_steps=decel_steps,
        )

    def moveStepsBlocking(
        self,
        steps: int,
        timeout_ms: int,
        delay_us: int | None = None,
        accel_start_delay_us: int | None = None,
        accel_steps: int | None = None,
        decel_steps: int | None = None,
    ) -> str:
        if delay_us is None:
            delay_us = self.default_delay_us
        if accel_start_delay_us is None:
            accel_start_delay_us = self.default_accel_start_delay_us
        if accel_steps is None:
            accel_steps = self.default_accel_steps
        if decel_steps is None:
            decel_steps = self.default_decel_steps
        if steps == 0:
            if self.name == "chute":
                self.gc.logger.info(
                    f"Stepper '{self.name}' moveStepsBlocking steps=0 fast-path (no MCU command)"
                )
            return "SKIP,T,steps=0"
        if self.name == "chute":
            queue_size = self.mcu.command_queue.qsize()
            worker_alive = self.mcu.worker_thread.is_alive()
            next_position_steps = self.current_position_steps + steps
            self.gc.logger.info(
                f"Stepper '{self.name}' moveStepsBlocking steps={steps} timeout_ms={timeout_ms} delay={delay_us}us accel_start={accel_start_delay_us}us accel_steps={accel_steps} decel_steps={decel_steps} pos={self.current_position_steps}->{next_position_steps} pre_queue={queue_size} worker_alive={worker_alive}"
            )
        line = ""
        last_error: RuntimeError | None = None
        total_attempts = BLOCKING_MOVE_RETRY_COUNT + 1
        for attempt_index in range(total_attempts):
            try:
                line = self.mcu.commandBlocking(
                    "T",
                    self.step_pin,
                    self.dir_pin,
                    steps,
                    delay_us,
                    accel_start_delay_us,
                    accel_steps,
                    decel_steps,
                    timeout_ms=timeout_ms,
                )
                last_error = None
                break
            except RuntimeError as error:
                last_error = error
                if attempt_index >= total_attempts - 1:
                    break
                self.gc.logger.error(
                    f"Stepper '{self.name}' moveStepsBlocking retry {attempt_index + 1}/{BLOCKING_MOVE_RETRY_COUNT} after error: {error}"
                )
                time.sleep(RETRY_DELAY_MS / 1000.0)

        if last_error is not None:
            raise last_error

        self.current_position_steps += steps
        setStepperPosition(self.name, self.current_position_steps)
        return line

    def estimateMoveStepsMs(
        self,
        steps: int,
        delay_us: int | None = None,
        accel_start_delay_us: int | None = None,
        accel_steps: int | None = None,
        decel_steps: int | None = None,
    ) -> int:
        if delay_us is None:
            delay_us = self.default_delay_us
        if accel_start_delay_us is None:
            accel_start_delay_us = self.default_accel_start_delay_us
        if accel_steps is None:
            accel_steps = self.default_accel_steps
        if decel_steps is None:
            decel_steps = self.default_decel_steps

        if delay_us < 1:
            delay_us = 1
        if accel_start_delay_us < delay_us:
            accel_start_delay_us = delay_us
        if accel_steps < 0:
            accel_steps = 0
        if decel_steps < 0:
            decel_steps = 0

        abs_steps = abs(steps)
        accel_zone = accel_steps
        decel_zone = decel_steps
        if accel_zone + decel_zone > abs_steps:
            accel_zone = abs_steps // 2
            decel_zone = abs_steps - accel_zone

        delay_delta = accel_start_delay_us - delay_us
        total_us = 0
        for i in range(abs_steps):
            step_delay_us = delay_us
            if delay_delta > 0 and accel_zone > 0 and i < accel_zone:
                step_delay_us = accel_start_delay_us - (
                    (delay_delta * (i + 1)) // accel_zone
                )
            if delay_delta > 0 and decel_zone > 0 and i >= abs_steps - decel_zone:
                decel_index = i - (abs_steps - decel_zone)
                step_delay_us = delay_us + (
                    (delay_delta * (decel_index + 1)) // decel_zone
                )
            total_us += step_delay_us * 2

        return (total_us + 999) // 1000

    def disable(self) -> None:
        self.mcu.command("D", self.enable_pin, 1)

    def enable(self) -> None:
        self.mcu.command("D", self.enable_pin, 0)
