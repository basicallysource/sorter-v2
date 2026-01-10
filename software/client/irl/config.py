from global_config import GlobalConfig
from .dc_motor import DCMotor
from .mcu import MCU


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


class IRLConfig:
    mc_path: str
    feeder_camera: CameraConfig
    first_v_channel_dc_motor: DCMotorConfig
    second_v_channel_dc_motor: DCMotorConfig
    third_v_channel_dc_motor: DCMotorConfig

    def __init__(self):
        pass


class IRLInterface:
    mcu: MCU
    first_v_channel_dc_motor: DCMotor
    second_v_channel_dc_motor: DCMotor
    third_v_channel_dc_motor: DCMotor

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


def mkIRLConfig() -> IRLConfig:
    irl_config = IRLConfig()
    irl_config.mc_path = "/dev/cu.usbserial-112410"
    irl_config.feeder_camera = mkCameraConfig(device_index=0)
    irl_config.first_v_channel_dc_motor = mkDCMotorConfig(
        enable_pin=9, input_1_pin=12, input_2_pin=13
    )
    irl_config.second_v_channel_dc_motor = mkDCMotorConfig(
        enable_pin=10, input_1_pin=14, input_2_pin=15
    )
    irl_config.third_v_channel_dc_motor = mkDCMotorConfig(
        enable_pin=5, input_1_pin=4, input_2_pin=7
    )
    return irl_config


def mkIRLInterface(config: IRLConfig, gc: GlobalConfig) -> IRLInterface:
    irl_interface = IRLInterface()

    mcu = MCU(gc, config.mc_path)
    irl_interface.mcu = mcu

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

    return irl_interface
