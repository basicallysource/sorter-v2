import time

from global_config import GlobalConfig
from .mcu import MCU
from .mcu_pico import PicoMCU
from .stepper import Stepper
from .servo import Servo
from .device_discovery import discoverMCU
from typing import TYPE_CHECKING, Union

SERVO_OPEN_ANGLE = 0
SERVO_CLOSED_ANGLE = 72

if TYPE_CHECKING:
    from subsystems.distribution.chute import Chute

from .bin_layout import (
    getBinLayout,
    BinLayoutConfig,
    DistributionLayout,
    mkLayoutFromConfig,
    layoutMatchesCategories,
    applyCategories,
)
from blob_manager import getBinCategories, getCameraSetup


class CameraConfig:
    device_index: int
    width: int
    height: int
    fps: int

    def __init__(self):
        pass


class StepperConfig:
    step_pin: int
    dir_pin: int
    enable_pin: int

    def __init__(self):
        pass


class CarouselArucoTagConfig:
    corner1_id: int
    corner2_id: int
    corner3_id: int
    corner4_id: int

    def __init__(self):
        pass


class ArucoTagConfig:
    second_c_channel_center_id: int
    second_c_channel_radius1_id: int
    second_c_channel_radius2_id: int
    third_c_channel_center_id: int
    third_c_channel_radius1_id: int
    third_c_channel_radius2_id: int
    carousel_platform1: CarouselArucoTagConfig
    carousel_platform2: CarouselArucoTagConfig
    carousel_platform3: CarouselArucoTagConfig
    carousel_platform4: CarouselArucoTagConfig

    def __init__(self):
        pass


class IRLConfig:
    mcu_path: str
    mcu_type: str
    feeder_camera: CameraConfig
    classification_camera_bottom: CameraConfig
    classification_camera_top: CameraConfig
    carousel_stepper: StepperConfig
    chute_stepper: StepperConfig
    first_c_channel_rotor_stepper: StepperConfig
    second_c_channel_rotor_stepper: StepperConfig
    third_c_channel_rotor_stepper: StepperConfig
    aruco_tags: ArucoTagConfig
    bin_layout_config: BinLayoutConfig

    def __init__(self):
        pass


class IRLInterface:
    mcu: Union[MCU, PicoMCU]
    carousel_stepper: Stepper
    chute_stepper: Stepper
    first_c_channel_rotor_stepper: Stepper
    second_c_channel_rotor_stepper: Stepper
    third_c_channel_rotor_stepper: Stepper
    servos: list[Servo]
    chute: "Chute"
    distribution_layout: DistributionLayout

    def __init__(self):
        pass

    def enableSteppers(self) -> None:
        self.first_c_channel_rotor_stepper.enable()
        self.second_c_channel_rotor_stepper.enable()
        self.third_c_channel_rotor_stepper.enable()

    def disableSteppers(self) -> None:
        self.first_c_channel_rotor_stepper.disable()
        self.second_c_channel_rotor_stepper.disable()
        self.third_c_channel_rotor_stepper.disable()

    def shutdownMotors(self) -> None:
        self.disableSteppers()


def mkCameraConfig(
    device_index: int, width: int = 1920, height: int = 1080, fps: int = 30
) -> CameraConfig:
    camera_config = CameraConfig()
    camera_config.device_index = device_index
    camera_config.width = width
    camera_config.height = height
    camera_config.fps = fps
    return camera_config


def mkStepperConfig(step_pin: int, dir_pin: int, enable_pin: int) -> StepperConfig:
    stepper_config = StepperConfig()
    stepper_config.step_pin = step_pin
    stepper_config.dir_pin = dir_pin
    stepper_config.enable_pin = enable_pin
    return stepper_config


def mkCarouselArucoTagConfig(
    c1: int, c2: int, c3: int, c4: int
) -> CarouselArucoTagConfig:
    config = CarouselArucoTagConfig()
    config.corner1_id = c1
    config.corner2_id = c2
    config.corner3_id = c3
    config.corner4_id = c4
    return config


def mkArucoTagConfig() -> ArucoTagConfig:
    config = ArucoTagConfig()
    # Channel 2 (second) - 3 tags: center, radius1, radius2
    config.second_c_channel_center_id = 20
    config.second_c_channel_radius1_id = 31
    config.second_c_channel_radius2_id = 7
    # Channel 3 (third) - 3 tags: center, radius1, radius2
    config.third_c_channel_center_id = 33
    config.third_c_channel_radius1_id = 14
    config.third_c_channel_radius2_id = 30
    # Carousel platforms - 4 tags per platform (corner1, corner2, corner3, corner4)
    config.carousel_platform1 = mkCarouselArucoTagConfig(4, 2, 18, 9)
    config.carousel_platform2 = mkCarouselArucoTagConfig(1, 32, 35, 8)
    config.carousel_platform3 = mkCarouselArucoTagConfig(6, 16, 11, 0)
    config.carousel_platform4 = mkCarouselArucoTagConfig(12, 22, 28, 5)
    return config


def mkIRLConfig() -> IRLConfig:
    irl_config = IRLConfig()
    mcu_port, mcu_type = discoverMCU()
    irl_config.mcu_path = mcu_port
    irl_config.mcu_type = mcu_type
    camera_setup = getCameraSetup()

    if camera_setup is None:
        raise RuntimeError(
            "No camera setup found. Run client/scripts/camera_setup.py first."
        )

    def resolveCamera(role: str) -> int:
        if role not in camera_setup:
            raise RuntimeError(
                f"Camera '{role}' not in setup. Run client/scripts/camera_setup.py first."
            )
        return camera_setup[role]

    feeder_camera_index = resolveCamera("feeder")
    classification_camera_bottom_index = resolveCamera("classification_bottom")
    classification_camera_top_index = resolveCamera("classification_top")

    irl_config.feeder_camera = mkCameraConfig(device_index=feeder_camera_index)
    irl_config.classification_camera_bottom = mkCameraConfig(
        device_index=classification_camera_bottom_index
    )
    irl_config.classification_camera_top = mkCameraConfig(
        device_index=classification_camera_top_index
    )
    
    # Use Pico-specific pin configuration if running on RPi Pico
    if mcu_type == "rpi_pico":
        # Basically board stepper configuration: only 4 steppers available
        # Stepper 0: carousel
        irl_config.carousel_stepper = mkStepperConfig(
            step_pin=28, dir_pin=27, enable_pin=0
        )
        # Stepper 1: chute
        irl_config.chute_stepper = mkStepperConfig(step_pin=26, dir_pin=22, enable_pin=0)
        # Stepper 2: first_c_channel_rotor
        irl_config.first_c_channel_rotor_stepper = mkStepperConfig(
            step_pin=21, dir_pin=20, enable_pin=0
        )
        # Stepper 3: second_c_channel_rotor
        irl_config.second_c_channel_rotor_stepper = mkStepperConfig(
            step_pin=19, dir_pin=18, enable_pin=0
        )
        # Note: Pico board doesn't have a 5th stepper, so we use the same as second
        irl_config.third_c_channel_rotor_stepper = mkStepperConfig(
            step_pin=19, dir_pin=18, enable_pin=0
        )
    else:
        # Arduino/RAMPS 1.4 configuration
        irl_config.carousel_stepper = mkStepperConfig(
            step_pin=36, dir_pin=34, enable_pin=30
        )
        irl_config.chute_stepper = mkStepperConfig(step_pin=26, dir_pin=28, enable_pin=24)
        # RAMPS 1.4: Z axis (first), Y axis (second), X axis (third)
        irl_config.first_c_channel_rotor_stepper = mkStepperConfig(
            step_pin=46, dir_pin=48, enable_pin=62
        )
        irl_config.second_c_channel_rotor_stepper = mkStepperConfig(
            step_pin=60, dir_pin=61, enable_pin=56
        )
        irl_config.third_c_channel_rotor_stepper = mkStepperConfig(
            step_pin=54, dir_pin=55, enable_pin=38
        )
    
    irl_config.aruco_tags = mkArucoTagConfig()
    irl_config.bin_layout_config = getBinLayout()
    return irl_config


def mkIRLInterface(config: IRLConfig, gc: GlobalConfig) -> IRLInterface:
    irl_interface = IRLInterface()

    # Initialize the appropriate MCU type
    mcu_type = config.mcu_type if hasattr(config, 'mcu_type') else "arduino"
    
    if mcu_type == "rpi_pico":
        gc.logger.info(f"Initializing RPi Pico MCU on {config.mcu_path}")
        mcu = PicoMCU(gc, config.mcu_path)
    else:
        gc.logger.info(f"Initializing Arduino MCU on {config.mcu_path}")
        mcu = MCU(gc, config.mcu_path)
    
    irl_interface.mcu = mcu

    irl_interface.carousel_stepper = Stepper(
        gc,
        mcu,
        config.carousel_stepper.step_pin,
        config.carousel_stepper.dir_pin,
        config.carousel_stepper.enable_pin,
        name="carousel",
        default_delay_us=1000,
    )
    time.sleep(1)

    irl_interface.chute_stepper = Stepper(
        gc,
        mcu,
        config.chute_stepper.step_pin,
        config.chute_stepper.dir_pin,
        config.chute_stepper.enable_pin,
        name="chute",
        default_delay_us=500,
        default_accel_start_delay_us=2500,
        default_accel_steps=250,
        default_decel_steps=250,
    )
    time.sleep(1)

    irl_interface.first_c_channel_rotor_stepper = Stepper(
        gc,
        mcu,
        config.first_c_channel_rotor_stepper.step_pin,
        config.first_c_channel_rotor_stepper.dir_pin,
        config.first_c_channel_rotor_stepper.enable_pin,
        name="first_c_channel_rotor",
        default_delay_us=800,
    )
    time.sleep(1)

    irl_interface.second_c_channel_rotor_stepper = Stepper(
        gc,
        mcu,
        config.second_c_channel_rotor_stepper.step_pin,
        config.second_c_channel_rotor_stepper.dir_pin,
        config.second_c_channel_rotor_stepper.enable_pin,
        name="second_c_channel_rotor",
        default_delay_us=800,
    )
    time.sleep(1)

    irl_interface.third_c_channel_rotor_stepper = Stepper(
        gc,
        mcu,
        config.third_c_channel_rotor_stepper.step_pin,
        config.third_c_channel_rotor_stepper.dir_pin,
        config.third_c_channel_rotor_stepper.enable_pin,
        name="third_c_channel_rotor",
        default_delay_us=800,
    )
    time.sleep(1)

    irl_interface.distribution_layout = mkLayoutFromConfig(config.bin_layout_config)

    irl_interface.servos = [
        Servo(gc, mcu, layer.servo_pin, f"layer_{i}_servo")
        for i, layer in enumerate(irl_interface.distribution_layout.layers)
    ]

    saved_categories = getBinCategories()
    if saved_categories is not None:
        if layoutMatchesCategories(irl_interface.distribution_layout, saved_categories):
            applyCategories(irl_interface.distribution_layout, saved_categories)
            gc.logger.info("Loaded bin categories from storage")
        else:
            gc.logger.warn("Saved bin categories don't match layout, ignoring")

    from subsystems.distribution.chute import Chute

    irl_interface.chute = Chute(
        gc, irl_interface.chute_stepper, irl_interface.distribution_layout
    )

    return irl_interface
