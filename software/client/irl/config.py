import time
import os

from global_config import GlobalConfig
from .mcu import MCU
from .stepper import Stepper
from .device_discovery import discoverMCUs


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


class IRLConfig:
    mcu_path: str
    second_mcu_path: str
    feeder_camera: CameraConfig
    classification_camera_bottom: CameraConfig
    classification_camera_top: CameraConfig
    carousel_stepper: StepperConfig
    chute_stepper: StepperConfig
    first_c_channel_rotor_stepper: StepperConfig
    second_c_channel_rotor_stepper: StepperConfig
    third_c_channel_rotor_stepper: StepperConfig
    first_c_channel_aruco_tag_id: int
    second_c_channel_aruco_tag_id: int
    third_c_channel_aruco_tag_id: int

    def __init__(self):
        pass


class IRLInterface:
    mcu: MCU
    second_mcu: MCU
    carousel_stepper: Stepper
    chute_stepper: Stepper
    first_c_channel_rotor_stepper: Stepper
    second_c_channel_rotor_stepper: Stepper
    third_c_channel_rotor_stepper: Stepper

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


def mkIRLConfig() -> IRLConfig:
    irl_config = IRLConfig()
    irl_config.mcu_path, irl_config.second_mcu_path = discoverMCUs()
    feeder_camera_index = int(os.environ["FEEDER_CAMERA_INDEX"])
    classification_camera_bottom_index = int(
        os.environ["CLASSIFICATION_CAMERA_BOTTOM_INDEX"]
    )
    classification_camera_top_index = int(os.environ["CLASSIFICATION_CAMERA_TOP_INDEX"])

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
    irl_config.first_c_channel_aruco_tag_id = 86
    irl_config.second_c_channel_aruco_tag_id = 815
    irl_config.third_c_channel_aruco_tag_id = 957
    return irl_config


def mkIRLInterface(config: IRLConfig, gc: GlobalConfig) -> IRLInterface:
    irl_interface = IRLInterface()

    mcu = MCU(gc, config.mcu_path)
    irl_interface.mcu = mcu

    second_mcu = MCU(gc, config.second_mcu_path)
    irl_interface.second_mcu = second_mcu

    irl_interface.carousel_stepper = Stepper(
        gc,
        second_mcu,
        config.carousel_stepper.step_pin,
        config.carousel_stepper.dir_pin,
        config.carousel_stepper.enable_pin,
        name="carousel",
        default_delay_us=1000,
    )
    time.sleep(1)

    irl_interface.chute_stepper = Stepper(
        gc,
        second_mcu,
        config.chute_stepper.step_pin,
        config.chute_stepper.dir_pin,
        config.chute_stepper.enable_pin,
        name="chute",
        default_delay_us=400,
    )
    time.sleep(1)

    irl_interface.first_c_channel_rotor_stepper = Stepper(
        gc,
        second_mcu,
        config.first_c_channel_rotor_stepper.step_pin,
        config.first_c_channel_rotor_stepper.dir_pin,
        config.first_c_channel_rotor_stepper.enable_pin,
        name="first_c_channel_rotor",
        default_delay_us=800,
    )
    time.sleep(1)

    irl_interface.second_c_channel_rotor_stepper = Stepper(
        gc,
        second_mcu,
        config.second_c_channel_rotor_stepper.step_pin,
        config.second_c_channel_rotor_stepper.dir_pin,
        config.second_c_channel_rotor_stepper.enable_pin,
        name="second_c_channel_rotor",
        default_delay_us=800,
    )
    time.sleep(1)

    irl_interface.third_c_channel_rotor_stepper = Stepper(
        gc,
        second_mcu,
        config.third_c_channel_rotor_stepper.step_pin,
        config.third_c_channel_rotor_stepper.dir_pin,
        config.third_c_channel_rotor_stepper.enable_pin,
        name="third_c_channel_rotor",
        default_delay_us=800,
    )
    time.sleep(1)

    return irl_interface
