import time

from global_config import GlobalConfig
from .device_discovery import discoverMCU, discoverMCUs
from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface
from typing import TYPE_CHECKING

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
    mcu_paths: list[str]
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
    carousel_stepper: "StepperMotor"
    chute_stepper: "StepperMotor"
    first_c_channel_rotor_stepper: "StepperMotor"
    second_c_channel_rotor_stepper: "StepperMotor"
    third_c_channel_rotor_stepper: "StepperMotor"
    servos: "list[ServoMotor]"
    chute: "Chute"
    distribution_layout: DistributionLayout

    def __init__(self):
        pass

    def enableSteppers(self) -> None:
        for stepper_name in [
            "first_c_channel_rotor",
            "second_c_channel_rotor",
            "third_c_channel_rotor",
            "carousel",
            "chute",
        ]:
            attr = f"{stepper_name}_stepper"
            if hasattr(self, attr):
                getattr(self, attr).enabled = True

    def disableSteppers(self) -> None:
        for stepper_name in [
            "first_c_channel_rotor",
            "second_c_channel_rotor",
            "third_c_channel_rotor",
            "carousel",
            "chute",
        ]:
            attr = f"{stepper_name}_stepper"
            if hasattr(self, attr):
                getattr(self, attr).enabled = False

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
    mcu_ports = discoverMCUs()
    irl_config.mcu_paths = mcu_ports
    irl_config.mcu_path = mcu_ports[0] if mcu_ports else discoverMCU()
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

    ports = getattr(config, "mcu_paths", None) or [config.mcu_path]
    discovered_interfaces: list[tuple[str, int, SorterInterface]] = []

    for port in ports:
        gc.logger.info(f"Scanning SorterInterface devices on {port}")
        bus = MCUBus(port=port)
        devices = bus.scan_devices()
        if not devices:
            gc.logger.warning(f"No SorterInterface devices found on {port}")
            continue

        for address in devices:
            try:
                sorter_interface = SorterInterface(bus, address)
                discovered_interfaces.append((port, address, sorter_interface))
                gc.logger.info(
                    f"SorterInterface initialized: port={port} address={address} name={sorter_interface.name}"
                )
            except Exception as e:
                gc.logger.warning(
                    f"Failed to initialize SorterInterface on {port} addr {address}: {e}"
                )

    if not discovered_interfaces:
        raise RuntimeError(
            f"No SorterInterface devices found on discovered ports: {ports}"
        )

    # Backward compatibility references
    irl_interface.sorter_interfaces = [si for _, _, si in discovered_interfaces]
    irl_interface.sorter_interface = irl_interface.sorter_interfaces[0]

    stepper_entries: list[tuple[str, object, str, int, str]] = []
    servo_source: SorterInterface | None = None

    for port, address, sorter_interface in discovered_interfaces:
        board_info = sorter_interface._board_info
        device_name = board_info.get("device_name", sorter_interface.name)
        stepper_names = board_info.get("stepper_names", [])
        available_stepper_count = len(sorter_interface.steppers)

        if not stepper_names:
            gc.logger.warning(
                f"{device_name} on {port}:{address} did not report stepper_names; using generic names"
            )
            stepper_names = [
                f"{device_name.lower().replace(' ', '_')}_ch{i}"
                for i in range(available_stepper_count)
            ]

        if len(stepper_names) > available_stepper_count:
            gc.logger.warning(
                f"{device_name} reported {len(stepper_names)} stepper_names but only {available_stepper_count} channels; truncating"
            )
            stepper_names = stepper_names[:available_stepper_count]

        gc.logger.info(
            f"Detected actuators on {device_name} ({port}:{address}): steppers={stepper_names}, servos={len(sorter_interface.servos)}"
        )

        for channel, stepper_name in enumerate(stepper_names):
            stepper_entries.append(
                (stepper_name, sorter_interface.steppers[channel], port, address, device_name)
            )

        if servo_source is None and len(sorter_interface.servos) > 0:
            servo_source = sorter_interface
        if (
            len(sorter_interface.servos) > 0
            and "chute_stepper" in stepper_names
        ):
            servo_source = sorter_interface

    gc.logger.info(
        f"Global actuator inventory: steppers={[name for name, _, _, _, _ in stepper_entries]}"
    )

    required_steppers = [
        "carousel",
        "third_c_channel_rotor",
        "second_c_channel_rotor",
        "first_c_channel_rotor",
        "chute_stepper",
    ]
    available_stepper_names = {name for name, _, _, _, _ in stepper_entries}
    for stepper_name in required_steppers:
        if stepper_name not in available_stepper_names:
            gc.logger.warning(
                f"Required stepper interface '{stepper_name}' not found in detected firmware actuators"
            )

    # Bind steppers by firmware name (first match wins)
    for stepper_name, stepper, port, address, device_name in stepper_entries:
        attr = stepper_name if stepper_name.endswith("_stepper") else f"{stepper_name}_stepper"
        if hasattr(irl_interface, attr):
            gc.logger.warning(
                f"Duplicate stepper name '{stepper_name}' detected at {device_name} ({port}:{address}); keeping first binding"
            )
            continue

        stepper.set_name(stepper_name)
        setattr(irl_interface, attr, stepper)
        gc.logger.info(
            f"Initialized Stepper '{stepper_name}' from {device_name} ({port}:{address}), position={stepper._current_position_steps} steps"
        )
        time.sleep(0.1)

    irl_interface.distribution_layout = mkLayoutFromConfig(config.bin_layout_config)

    # Initialize servos directly from sorter_interface
    irl_interface.servos = []
    if servo_source is None:
        gc.logger.warning("No servo-capable SorterInterface detected")
        servo_source = irl_interface.sorter_interface

    for i, layer in enumerate(irl_interface.distribution_layout.layers):
        if i >= len(servo_source.servos):
            gc.logger.error(f"Not enough servos! Layer {i} requested but only {len(servo_source.servos)} servos available")
            raise IndexError(f"Layer {i} servo not available. Only {len(servo_source.servos)} servos configured.")
        servo = servo_source.servos[i]
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
