from global_config import GlobalConfig
from typing import Optional, TYPE_CHECKING
import time

if TYPE_CHECKING:
    from .mcu import MCU


class DCMotor:
    def __init__(
        self,
        gc: GlobalConfig,
        mcu: "MCU",
        enable_pin: int,
        input_1_pin: int,
        input_2_pin: int,
    ):
        self.gc = gc
        self.mcu = mcu
        self.enable_pin = enable_pin
        self.input_1_pin = input_1_pin
        self.input_2_pin = input_2_pin
        self.current_speed: Optional[int] = None

        logger = gc.logger
        logger.info(
            f"Initialized DCMotor with enable={enable_pin}, input1={input_1_pin}, input2={input_2_pin}"
        )

        # set pins to OUTPUT mode
        mcu.command("P", input_1_pin, 1)
        mcu.command("P", input_2_pin, 1)
        mcu.command("P", enable_pin, 1)

    def setSpeed(self, speed: int, override: bool = False) -> None:
        original_speed = speed
        speed = max(-254, min(254, speed))

        if self.current_speed == speed and not override:
            return

        logger = self.gc.logger
        logger.info(f"DCMotor setSpeed: requested={original_speed}, clamped={speed}")
        logger.info(
            f"Using pins: enable={self.enable_pin}, input1={self.input_1_pin}, input2={self.input_2_pin}"
        )

        if speed > 0:
            logger.info("Setting FORWARD: IN1=HIGH, IN2=LOW")
            self.mcu.command("D", self.input_1_pin, 1)
            self.mcu.command("D", self.input_2_pin, 0)
        elif speed < 0:
            logger.info("Setting REVERSE: IN1=LOW, IN2=HIGH")
            self.mcu.command("D", self.input_1_pin, 0)
            self.mcu.command("D", self.input_2_pin, 1)
        else:
            logger.info("Setting STOP: IN1=LOW, IN2=LOW")
            self.mcu.command("D", self.input_1_pin, 0)
            self.mcu.command("D", self.input_2_pin, 0)

        pwm_value = int(abs(speed))
        logger.info(f"Setting enable pin {self.enable_pin} to PWM value: {pwm_value}")
        self.mcu.command("A", self.enable_pin, pwm_value)

        self.current_speed = speed

    def backstop(
        self,
        current_speed: int,
        backstop_speed: int = 75,
        backstop_duration_ms: int = 10,
    ) -> None:
        DO_BACKSTOP = True
        if not DO_BACKSTOP:
            self.setSpeed(0)
            return
        backstop_speed = max(-255, min(255, backstop_speed))

        if current_speed > 0:
            backstop_direction = -backstop_speed
        elif current_speed < 0:
            backstop_direction = backstop_speed
        else:
            return

        self.setSpeed(backstop_direction)
        time.sleep(backstop_duration_ms / 1000.0)
        self.setSpeed(0)
