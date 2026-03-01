import time

from global_config import GlobalConfig
from .device_discovery import discoverMCU
from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface
from typing import TYPE_CHECKING, Union

SERVO_OPEN_ANGLE = 0
SERVO_CLOSED_ANGLE = 72

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor, ServoMotor

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
    second_c_channel_output_guide_id: int
    second_c_channel_radius1_id: int
    second_c_channel_radius2_id: int
    second_c_channel_radius3_id: int
    second_c_channel_radius4_id: int
    second_c_channel_radius5_id: int
    second_c_channel_radius_ids: list[int]
    second_c_channel_radius_multiplier: float
    third_c_channel_center_id: int
    third_c_channel_output_guide_id: int
    third_c_channel_radius1_id: int
    third_c_channel_radius2_id: int
    third_c_channel_radius3_id: int
    third_c_channel_radius4_id: int
    third_c_channel_radius5_id: int
    third_c_channel_radius_ids: list[int]
    third_c_channel_radius_multiplier: float
    carousel_platform1: CarouselArucoTagConfig
    carousel_platform2: CarouselArucoTagConfig
    carousel_platform3: CarouselArucoTagConfig
    carousel_platform4: CarouselArucoTagConfig

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
        self.first_c_channel_rotor_stepper.enabled = True
        self.second_c_channel_rotor_stepper.enabled = True
        self.third_c_channel_rotor_stepper.enabled = True

    def disableSteppers(self) -> None:
        self.first_c_channel_rotor_stepper.enabled = False
        self.second_c_channel_rotor_stepper.enabled = False
        self.third_c_channel_rotor_stepper.enabled = False

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
    config.second_c_channel_output_guide_id = None
    config.second_c_channel_radius1_id = 31
    config.second_c_channel_radius2_id = 7
    config.second_c_channel_radius3_id = None
    config.second_c_channel_radius4_id = None
    config.second_c_channel_radius5_id = None
    config.second_c_channel_radius_ids = [31, 7]
    config.second_c_channel_radius_multiplier = 1.0
    # Channel 3 (third) - 3 tags: center, radius1, radius2
    config.third_c_channel_center_id = 33
    config.third_c_channel_output_guide_id = None
    config.third_c_channel_radius1_id = 14
    config.third_c_channel_radius2_id = 30
    config.third_c_channel_radius3_id = None
    config.third_c_channel_radius4_id = None
    config.third_c_channel_radius5_id = None
    config.third_c_channel_radius_ids = [14, 30]
    config.third_c_channel_radius_multiplier = 1.0
    # Carousel platforms - 4 tags per platform (corner1, corner2, corner3, corner4)
    config.carousel_platform1 = mkCarouselArucoTagConfig(4, 2, 18, 9)
    config.carousel_platform2 = mkCarouselArucoTagConfig(1, 32, 35, 8)
    config.carousel_platform3 = mkCarouselArucoTagConfig(6, 16, 11, 0)
    config.carousel_platform4 = mkCarouselArucoTagConfig(12, 22, 28, 5)
    return config


def mkIRLConfig() -> IRLConfig:
    """
    Create the IRL (In Real Life) interface configuration.
    
    Note: Pin configuration is no longer used. The Pico firmware reports stepper names
    at initialization time, making the client pin-agnostic.
    """
    irl_config = IRLConfig()
    mcu_port = discoverMCU()
    irl_config.mcu_path = mcu_port
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
    
    # Camera configuration complete - stepper config happens at firmware discovery time
    irl_config.aruco_tags = mkArucoTagConfig()
    irl_config.bin_layout_config = getBinLayout()
    return irl_config


def mkIRLInterface(config: IRLConfig, gc: GlobalConfig) -> IRLInterface:
    """
    Initialize the hardware interface using SorterInterface directly.

    Uses SorterInterface firmware and dynamic stepper name discovery.
    The firmware reports which steppers are available via stepper_names.
    """
    irl_interface = IRLInterface()

    # Initialize the SorterInterface via MCUBus
    gc.logger.info(f"Initializing SorterInterface on {config.mcu_path}")
    
    bus = MCUBus(port=config.mcu_path)
    devices = bus.scan_devices()
    
    if not devices:
        raise RuntimeError(f"No Pico devices found on {config.mcu_path}")
    
    sorter_interface = SorterInterface(bus, devices[0])
    gc.logger.info(f"SorterInterface initialized: {sorter_interface.name}")
    
    # Store reference to sorter_interface for shutdown
    irl_interface.sorter_interface = sorter_interface
    
    # Get stepper names from firmware configuration
    board_info = sorter_interface._board_info
    stepper_names = board_info.get("stepper_names", [])
    device_name = board_info.get("device_name", "")
    
    # Fallback to default names if firmware doesn't report them (for old firmware)
    if not stepper_names:
        gc.logger.warning("Firmware did not report stepper names, using defaults")
        # Verified FEEDER MB channel order:
        # ch0=first_c_channel, ch1=second_c_channel, ch2=third_c_channel, ch3=carousel
        stepper_names = [
            "first_c_channel_rotor",
            "second_c_channel_rotor",
            "third_c_channel_rotor",
            "carousel",
        ]
    elif (
        device_name == "FEEDER MB"
        and stepper_names
        == [
            "carousel",
            "third_c_channel_rotor",
            "second_c_channel_rotor",
            "first_c_channel_rotor",
        ]
    ):
        gc.logger.warning(
            "FEEDER MB firmware reported legacy stepper_names order; applying client-side override"
        )
        stepper_names = [
            "first_c_channel_rotor",
            "second_c_channel_rotor",
            "third_c_channel_rotor",
            "carousel",
        ]
    
    gc.logger.info(f"Found {len(stepper_names)} steppers: {stepper_names}")
    
    # Dynamically assign steppers by their names from firmware
    for channel, stepper_name in enumerate(stepper_names):
        if channel >= len(sorter_interface.steppers):
            gc.logger.warning(f"Channel {channel} exceeds available steppers")
            break
        
        stepper = sorter_interface.steppers[channel]
        stepper.set_name(stepper_name)
        
        # Assign to IRLInterface dynamically
        setattr(irl_interface, f"{stepper_name}_stepper", stepper)
        gc.logger.info(f"Initialized Stepper '{stepper_name}' on channel {channel}, position={stepper._current_position_steps} steps")
        time.sleep(0.3)
    
    # Verify required steppers are present
    required_steppers = ["carousel", "first_c_channel_rotor", "second_c_channel_rotor", "third_c_channel_rotor"]
    for stepper_name in required_steppers:
        if not hasattr(irl_interface, f"{stepper_name}_stepper"):
            gc.logger.warning(f"Required stepper '{stepper_name}' not found from firmware")
    
    # Provide compatibility alias for "chute" mapped to third_c_channel_rotor
    if hasattr(irl_interface, "chute_stepper"):
        pass  # Already set by firmware
    elif hasattr(irl_interface, "third_c_channel_rotor_stepper"):
        irl_interface.chute_stepper = irl_interface.third_c_channel_rotor_stepper
        gc.logger.info("Using third_c_channel_rotor as chute_stepper (compatibility alias)")
    else:
        gc.logger.warning("Neither chute_stepper nor third_c_channel_rotor_stepper found")

    irl_interface.distribution_layout = mkLayoutFromConfig(config.bin_layout_config)

    # Initialize servos directly from sorter_interface
    irl_interface.servos = []
    for i, layer in enumerate(irl_interface.distribution_layout.layers):
        if i >= len(sorter_interface.servos):
            gc.logger.error(f"Not enough servos! Layer {i} requested but only {len(sorter_interface.servos)} servos available")
            raise IndexError(f"Layer {i} servo not available. Only {len(sorter_interface.servos)} servos configured.")
        servo = sorter_interface.servos[i]
        servo.set_name(f"layer_{i}_servo")
        servo.set_preset_angles(SERVO_OPEN_ANGLE, SERVO_CLOSED_ANGLE)
        irl_interface.servos.append(servo)
        gc.logger.info(f"Initialized Servo 'layer_{i}_servo' on channel {i}, angle={servo.angle}°")

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
