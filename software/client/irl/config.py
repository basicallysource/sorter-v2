from global_config import GlobalConfig
from .dc_motor import DCMotor
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


class DCMotorConfig:
    enable_pin: int
    input_1_pin: int
    input_2_pin: int

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
    first_v_channel_dc_motor: DCMotorConfig
    second_v_channel_dc_motor: DCMotorConfig
    third_v_channel_dc_motor: DCMotorConfig
    carousel_stepper: StepperConfig
    chute_stepper: StepperConfig

    def __init__(self):
        pass


class IRLInterface:
    mcu: MCU
    second_mcu: MCU
    first_v_channel_dc_motor: DCMotor
    second_v_channel_dc_motor: DCMotor
    third_v_channel_dc_motor: DCMotor
    carousel_stepper: Stepper
    chute_stepper: Stepper

    def __init__(self):
        pass

    def shutdownMotors(self) -> None:
        self.first_v_channel_dc_motor.setSpeed(0)
        self.second_v_channel_dc_motor.setSpeed(0)
        self.third_v_channel_dc_motor.setSpeed(0)

        self.mcu.command("D", self.first_v_channel_dc_motor.input_1_pin, 0)
        self.mcu.command("D", self.first_v_channel_dc_motor.input_2_pin, 0)
        self.mcu.command("D", self.first_v_channel_dc_motor.enable_pin, 0)

        self.mcu.command("D", self.second_v_channel_dc_motor.input_1_pin, 0)
        self.mcu.command("D", self.second_v_channel_dc_motor.input_2_pin, 0)
        self.mcu.command("D", self.second_v_channel_dc_motor.enable_pin, 0)

        self.mcu.command("D", self.third_v_channel_dc_motor.input_1_pin, 0)
        self.mcu.command("D", self.third_v_channel_dc_motor.input_2_pin, 0)
        self.mcu.command("D", self.third_v_channel_dc_motor.enable_pin, 0)


def mkCameraConfig(
    device_index: int, width: int = 1920, height: int = 1080, fps: int = 30
) -> CameraConfig:
    camera_config = CameraConfig()
    camera_config.device_index = device_index
    camera_config.width = width
    camera_config.height = height
    camera_config.fps = fps
    return camera_config


def mkDCMotorConfig(
    enable_pin: int, input_1_pin: int, input_2_pin: int
) -> DCMotorConfig:
    dc_motor_config = DCMotorConfig()
    dc_motor_config.enable_pin = enable_pin
    dc_motor_config.input_1_pin = input_1_pin
    dc_motor_config.input_2_pin = input_2_pin
    return dc_motor_config


def mkStepperConfig(step_pin: int, dir_pin: int, enable_pin: int) -> StepperConfig:
    stepper_config = StepperConfig()
    stepper_config.step_pin = step_pin
    stepper_config.dir_pin = dir_pin
    stepper_config.enable_pin = enable_pin
    return stepper_config


def mkIRLConfig() -> IRLConfig:
    irl_config = IRLConfig()
    irl_config.mcu_path, irl_config.second_mcu_path = discoverMCUs()
    irl_config.feeder_camera = mkCameraConfig(device_index=0)
    irl_config.classification_camera_bottom = mkCameraConfig(device_index=2)
    irl_config.classification_camera_top = mkCameraConfig(device_index=1)
    irl_config.first_v_channel_dc_motor = mkDCMotorConfig(
        enable_pin=9, input_1_pin=12, input_2_pin=13
    )
    irl_config.second_v_channel_dc_motor = mkDCMotorConfig(
        enable_pin=10, input_1_pin=14, input_2_pin=15
    )
    irl_config.third_v_channel_dc_motor = mkDCMotorConfig(
        enable_pin=5, input_1_pin=4, input_2_pin=7
    )
    irl_config.carousel_stepper = mkStepperConfig(
        step_pin=36, dir_pin=34, enable_pin=30
    )
    irl_config.chute_stepper = mkStepperConfig(step_pin=26, dir_pin=28, enable_pin=24)
    return irl_config


def mkIRLInterface(config: IRLConfig, gc: GlobalConfig) -> IRLInterface:
    irl_interface = IRLInterface()

    mcu = MCU(gc, config.mcu_path)
    irl_interface.mcu = mcu

    second_mcu = MCU(gc, config.second_mcu_path)
    irl_interface.second_mcu = second_mcu

    irl_interface.first_v_channel_dc_motor = DCMotor(
        gc,
        mcu,
        config.first_v_channel_dc_motor.enable_pin,
        config.first_v_channel_dc_motor.input_1_pin,
        config.first_v_channel_dc_motor.input_2_pin,
    )

    irl_interface.second_v_channel_dc_motor = DCMotor(
        gc,
        mcu,
        config.second_v_channel_dc_motor.enable_pin,
        config.second_v_channel_dc_motor.input_1_pin,
        config.second_v_channel_dc_motor.input_2_pin,
    )

    irl_interface.third_v_channel_dc_motor = DCMotor(
        gc,
        mcu,
        config.third_v_channel_dc_motor.enable_pin,
        config.third_v_channel_dc_motor.input_1_pin,
        config.third_v_channel_dc_motor.input_2_pin,
    )

    irl_interface.carousel_stepper = Stepper(
        gc,
        second_mcu,
        config.carousel_stepper.step_pin,
        config.carousel_stepper.dir_pin,
        config.carousel_stepper.enable_pin,
        name="carousel",
    )

    irl_interface.chute_stepper = Stepper(
        gc,
        second_mcu,
        config.chute_stepper.step_pin,
        config.chute_stepper.dir_pin,
        config.chute_stepper.enable_pin,
        name="chute",
    )

    return irl_interface
