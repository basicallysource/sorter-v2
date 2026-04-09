from global_config import GlobalConfig
from irl.config import IRLInterface

SENSORLESS_HOME_DEGREES: float = 10


def sensorlessHomeCarousel(gc: GlobalConfig, irl: IRLInterface) -> None:
    gc.logger.info(f"Homing carousel (+{SENSORLESS_HOME_DEGREES}°, zeroing)...")
    irl.carousel_stepper.move_degrees_blocking(SENSORLESS_HOME_DEGREES)
    irl.carousel_stepper.position_degrees = 0.0
    gc.logger.info("Carousel homed")
