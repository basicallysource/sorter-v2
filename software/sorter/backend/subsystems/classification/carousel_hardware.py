import time
from typing import TYPE_CHECKING
from global_config import GlobalConfig

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor, DigitalInputPin

HOME_SPEED_MICROSTEPS_PER_SEC = 400
HOME_SPEED_SLOW_MICROSTEPS_PER_SEC = 100
# Match the older direct homing path that was stable in day-to-day use.
BACKOFF_STEPS = 40
HOME_PASSES = 3
HOME_TIMEOUT_MS = 30000


class CarouselHardware:
    def __init__(
        self,
        gc: GlobalConfig,
        stepper: "StepperMotor",
        home_pin: "DigitalInputPin",
        endstop_active_high: bool = False,
    ):
        self.gc = gc
        self.logger = gc.logger
        self.stepper = stepper
        self.home_pin = home_pin
        self.endstop_active_high = endstop_active_high

    @property
    def raw_endstop_active(self) -> bool:
        return bool(self.home_pin.value)

    @property
    def endstop_triggered(self) -> bool:
        raw = self.raw_endstop_active
        return raw if self.endstop_active_high else not raw

    def home(self) -> bool:
        self.logger.info("Carousel: homing via sensor")
        self.stepper.enabled = True

        if not self._homePass(HOME_SPEED_MICROSTEPS_PER_SEC):
            return False

        for _ in range(HOME_PASSES - 1):
            self.stepper.move_steps_blocking(-BACKOFF_STEPS, timeout_ms=5000)
            if not self._homePass(HOME_SPEED_SLOW_MICROSTEPS_PER_SEC):
                return False

        self.stepper.position_degrees = 0.0
        self.logger.info("Carousel: homed successfully")
        return True

    def _homePass(self, speed: int) -> bool:
        self.stepper.home(
            speed,
            self.home_pin,
            home_pin_active_high=self.endstop_active_high,
        )
        start = time.monotonic()
        while not self.stepper.stopped:
            if (time.monotonic() - start) * 1000 > HOME_TIMEOUT_MS:
                self.logger.error("Carousel: homing timed out")
                self.stepper.move_at_speed(0)
                return False
            time.sleep(0.01)
        if not self.endstop_triggered:
            self.logger.warning("Carousel: homing stopped before endstop triggered")
            return False
        return True
