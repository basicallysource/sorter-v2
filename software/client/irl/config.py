import time

from global_config import GlobalConfig
from .mcu import MCU
from .stepper import Stepper
from .device_discovery import discoverMCU
from typing import TYPE_CHECKING

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


class ArucoTagConfig:
    second_c_channel_center_id: int
    second_c_channel_radius1_id: int
    second_c_channel_radius2_id: int
    third_c_channel_center_id: int
    third_c_channel_radius1_id: int
    third_c_channel_radius2_id: int

    def __init__(self):
        pass


class IRLConfig:
    mcu_path: str
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
    mcu: MCU
    carousel_stepper: Stepper
    chute_stepper: Stepper
    first_c_channel_rotor_stepper: Stepper
    second_c_channel_rotor_stepper: Stepper
    third_c_channel_rotor_stepper: Stepper
    servo_angles: list[int]
    chute: "Chute"
    distribution_layout: DistributionLayout

    def __init__(self):
        pass

    def shutdownMotors(self) -> None:
        self.first_c_channel_rotor_stepper.disable()
        self.second_c_channel_rotor_stepper.disable()
        self.third_c_channel_rotor_stepper.disable()


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


def mkArucoTagConfig() -> ArucoTagConfig:
    config = ArucoTagConfig()
    # Channel 2 (second) - 3 tags: center, radius1, radius2
    config.second_c_channel_center_id = 298
    config.second_c_channel_radius1_id = 815
    config.second_c_channel_radius2_id = 451
    # Channel 3 (third) - 3 tags: center, radius1, radius2
    config.third_c_channel_center_id = 73
    config.third_c_channel_radius1_id = 957
    config.third_c_channel_radius2_id = 517
    return config


def mkIRLConfig() -> IRLConfig:
    irl_config = IRLConfig()
    irl_config.mcu_path = discoverMCU()
    camera_setup = getCameraSetup()

    if camera_setup is None:
        raise RuntimeError(
            "No camera setup found. Run client/scripts/camera_setup.py first."
        )

    def resolveCamera(role: str) -> int:
        if role not in camera_setup:
            raise RuntimeError(f"Camera '{role}' not in setup. Run client/scripts/camera_setup.py first.")
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
        default_delay_us=1000,
        default_accel_start_delay_us=5000,
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

    num_layers = len(irl_interface.distribution_layout.layers)
    irl_interface.servo_angles = [SERVO_OPEN_ANGLE] * num_layers

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
