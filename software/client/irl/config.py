import time

from global_config import GlobalConfig
from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor, ServoMotor
    from subsystems.distribution.chute import Chute

from .bin_layout import (
    getBinLayout,
    BinLayoutConfig,
    DistributionLayout,
    mkLayoutFromConfig,
    layoutMatchesCategories,
    applyCategories,
)
from .parse_user_toml import (
    loadMachineSpecificParams,
    loadStepperCurrentOverrides,
    loadServoPresetAngles,
    loadWaveshareServoConfig,
    loadCameraLayoutConfig,
    applyStepperCurrentOverride,
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
    default_steps_per_second: int
    microsteps: int

    def __init__(self, default_steps_per_second: int = 2000, microsteps: int = 8):
        self.default_steps_per_second = default_steps_per_second
        self.microsteps = microsteps


class CarouselArucoTagConfig:
    corner1_id: int | None
    corner2_id: int | None
    corner3_id: int | None
    corner4_id: int | None

    def __init__(self):
        pass


class ArucoTagConfig:
    second_c_channel_center_id: int | None
    second_c_channel_output_guide_id: int | None
    second_c_channel_radius1_id: int | None
    second_c_channel_radius2_id: int | None
    second_c_channel_radius3_id: int | None
    second_c_channel_radius4_id: int | None
    second_c_channel_radius5_id: int | None
    second_c_channel_radius_ids: list[int]
    second_c_channel_radius_multiplier: float
    third_c_channel_center_id: int | None
    third_c_channel_output_guide_id: int | None
    third_c_channel_radius1_id: int | None
    third_c_channel_radius2_id: int | None
    third_c_channel_radius3_id: int | None
    third_c_channel_radius4_id: int | None
    third_c_channel_radius5_id: int | None
    third_c_channel_radius_ids: list[int]
    third_c_channel_radius_multiplier: float
    carousel_platform1: CarouselArucoTagConfig
    carousel_platform2: CarouselArucoTagConfig
    carousel_platform3: CarouselArucoTagConfig
    carousel_platform4: CarouselArucoTagConfig

    def __init__(self):
        pass


class RotorPulseConfig:
    steps_per_pulse: int
    microsteps_per_second: int
    delay_between_pulse_ms: int

    def __init__(
        self,
        steps: int,
        microsteps_per_second: int,
        delay_between_ms: int,
    ):
        self.steps_per_pulse = steps
        self.microsteps_per_second = microsteps_per_second
        self.delay_between_pulse_ms = delay_between_ms


class FeederConfig:
    first_rotor: RotorPulseConfig
    second_rotor_normal: RotorPulseConfig
    second_rotor_precision: RotorPulseConfig
    third_rotor_normal: RotorPulseConfig
    third_rotor_precision: RotorPulseConfig

    def __init__(self):
        self.first_rotor = RotorPulseConfig(
            steps=50,
            microsteps_per_second=2000,
            delay_between_ms=1500,
        )
        self.second_rotor_normal = RotorPulseConfig(
            steps=500,
            microsteps_per_second=5000,
            delay_between_ms=250,
        )
        self.second_rotor_precision = RotorPulseConfig(
            steps=200,
            microsteps_per_second=2500,
            delay_between_ms=350,
        )
        self.third_rotor_normal = RotorPulseConfig(
            steps=1000,
            microsteps_per_second=5000,
            delay_between_ms=250,
        )
        self.third_rotor_precision = RotorPulseConfig(
            steps=100,
            microsteps_per_second=2000,
            delay_between_ms=500,
        )


class IRLConfig:
    # camera_layout: "default" = single feeder + classification cameras
    #                "split_feeder" = per-channel + carousel cameras (no classification)
    camera_layout: str
    feeder_camera: CameraConfig
    classification_camera_bottom: CameraConfig
    classification_camera_top: CameraConfig
    # split_feeder cameras (only set when camera_layout == "split_feeder")
    c_channel_2_camera: CameraConfig | None
    c_channel_3_camera: CameraConfig | None
    carousel_camera: CameraConfig | None
    carousel_stepper: StepperConfig
    chute_stepper: StepperConfig
    c_channel_1_rotor_stepper: StepperConfig
    c_channel_2_rotor_stepper: StepperConfig
    c_channel_3_rotor_stepper: StepperConfig
    aruco_tags: ArucoTagConfig
    bin_layout_config: BinLayoutConfig
    feeder_config: FeederConfig

    def __init__(self):
        self.camera_layout = "default"
        self.c_channel_2_camera = None
        self.c_channel_3_camera = None
        self.carousel_camera = None
        self.feeder_config = FeederConfig()


class IRLInterface:
    carousel_stepper: "StepperMotor"
    chute_stepper: "StepperMotor"
    c_channel_1_rotor_stepper: "StepperMotor"
    c_channel_2_rotor_stepper: "StepperMotor"
    c_channel_3_rotor_stepper: "StepperMotor"
    servos: "list[ServoMotor]"
    chute: "Chute"
    distribution_layout: DistributionLayout
    interfaces: dict[str, SorterInterface]

    def __init__(self):
        self.interfaces: dict[str, SorterInterface] = {}

    def enableSteppers(self) -> None:
        for stepper_name in [
            "c_channel_1_rotor",
            "c_channel_2_rotor",
            "c_channel_3_rotor",
            "carousel",
            "chute",
        ]:
            attr = f"{stepper_name}_stepper"
            if hasattr(self, attr):
                getattr(self, attr).enabled = True

    def disableSteppers(self) -> None:
        for stepper_name in [
            "c_channel_1_rotor",
            "c_channel_2_rotor",
            "c_channel_3_rotor",
            "carousel",
            "chute",
        ]:
            attr = f"{stepper_name}_stepper"
            if hasattr(self, attr):
                getattr(self, attr).enabled = False

    def shutdown(self) -> None:
        self.disableSteppers()
        for iface in self.interfaces.values():
            iface.shutdown()


def mkCameraConfig(
    device_index: int, width: int = 1920, height: int = 1080, fps: int = 30
) -> CameraConfig:
    camera_config = CameraConfig()
    camera_config.device_index = device_index
    camera_config.width = width
    camera_config.height = height
    camera_config.fps = fps
    return camera_config


def mkStepperConfig(
    default_steps_per_second: int = 2000,
    microsteps: int = 8,
) -> StepperConfig:
    return StepperConfig(default_steps_per_second, microsteps)


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


def mkIRLConfig(machine_params: dict[str, object] | None = None) -> IRLConfig:
    irl_config = IRLConfig()

    # Check for TOML camera layout override
    from global_config import mkGlobalConfig as _mkGC
    # We need a lightweight logger; borrow from GlobalConfig if available later.
    # For now, camera layout is parsed in mkIRLInterface where gc is available.
    # Here we just check the raw TOML for layout type.
    import os, tomllib
    camera_layout_type = "default"
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if params_path and os.path.exists(params_path):
        try:
            with open(params_path, "rb") as f:
                raw_toml = tomllib.load(f)
            cameras_section = raw_toml.get("cameras", {})
            if isinstance(cameras_section, dict):
                camera_layout_type = cameras_section.get("layout", "default")
        except Exception:
            pass

    irl_config.camera_layout = camera_layout_type

    if camera_layout_type == "split_feeder":
        # split_feeder: per-channel cameras from TOML, no single feeder or classification
        cameras_section = {}
        if params_path and os.path.exists(params_path):
            try:
                with open(params_path, "rb") as f:
                    raw_toml = tomllib.load(f)
                cameras_section = raw_toml.get("cameras", {})
            except Exception:
                pass

        c_ch2_idx = cameras_section.get("c_channel_2")
        c_ch3_idx = cameras_section.get("c_channel_3")
        carousel_idx = cameras_section.get("carousel")

        if isinstance(c_ch2_idx, int):
            irl_config.c_channel_2_camera = mkCameraConfig(device_index=c_ch2_idx)
        if isinstance(c_ch3_idx, int):
            irl_config.c_channel_3_camera = mkCameraConfig(device_index=c_ch3_idx)
        if isinstance(carousel_idx, int):
            irl_config.carousel_camera = mkCameraConfig(device_index=carousel_idx)

        # Set dummy configs for the default cameras so nothing crashes on attr access
        irl_config.feeder_camera = mkCameraConfig(device_index=-1)
        irl_config.classification_camera_bottom = mkCameraConfig(device_index=-1)
        irl_config.classification_camera_top = mkCameraConfig(device_index=-1)
    else:
        # default: single feeder + classification cameras from camera_setup
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
            device_index=classification_camera_bottom_index, width=9999, height=9999
        )
        irl_config.classification_camera_top = mkCameraConfig(
            device_index=classification_camera_top_index, width=9999, height=9999
        )
    
    irl_config.carousel_stepper = mkStepperConfig(default_steps_per_second=500, microsteps=16)
    irl_config.chute_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.c_channel_1_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.c_channel_2_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.c_channel_3_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)

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
    machine_specific_params = loadMachineSpecificParams(gc)
    stepper_current_overrides = loadStepperCurrentOverrides(gc, machine_specific_params)
    servo_open_angle, servo_closed_angle = loadServoPresetAngles(gc, machine_specific_params)

    ports = MCUBus.enumerate_buses()
    if not ports:
        raise RuntimeError("No MCU buses found.")
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
                sorter_interface = SorterInterface(bus, address, gc)
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
            f"No SorterInterface devices found on buses: {ports}"
        )

    irl_interface.interfaces = {si.name: si for _, _, si in discovered_interfaces}

    stepper_entries: list[tuple[str, "StepperMotor", str, int, str]] = []
    servo_source: SorterInterface | None = None
    distribution_board: SorterInterface | None = None

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
        if "chute_stepper" in stepper_names:
            distribution_board = sorter_interface
            servo_source = sorter_interface

    gc.logger.info(
        f"Global actuator inventory: steppers={[name for name, _, _, _, _ in stepper_entries]}"
    )

    required_steppers = [
        "carousel",
        "c_channel_3_rotor",
        "c_channel_2_rotor",
        "c_channel_1_rotor",
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

        stepper_config: StepperConfig | None = getattr(config, attr, None)
        stepper.set_name(stepper_name)
        if stepper_config is not None:
            stepper.set_microsteps(stepper_config.microsteps)
            stepper.set_speed_limits(16, stepper_config.default_steps_per_second)
            gc.logger.info(
                f"Stepper '{stepper_name}' config: microsteps={stepper_config.microsteps}, speed={stepper_config.default_steps_per_second}"
            )
        else:
            gc.logger.warn(
                f"Stepper '{stepper_name}' has no StepperConfig (attr='{attr}'), using defaults"
            )

        applyStepperCurrentOverride(stepper, stepper_name, stepper_current_overrides, gc)

        setattr(irl_interface, attr, stepper)
        gc.logger.info(
            f"Initialized Stepper '{stepper_name}' from {device_name} ({port}:{address}), position={stepper._current_position_steps} steps"
        )
        time.sleep(0.1)

    irl_interface.distribution_layout = mkLayoutFromConfig(config.bin_layout_config)

    # Initialize servos — either Waveshare SC bus or PCA9685 (default)
    irl_interface.servos = []
    waveshare_config = loadWaveshareServoConfig(gc, machine_specific_params)

    if waveshare_config is not None:
        from hardware.waveshare_servo import ScServoBus, WaveshareServoMotor

        ws_port = waveshare_config.port
        if ws_port is None:
            # Auto-detect: find a USB serial device that is NOT one of our MCU buses
            import serial.tools.list_ports
            mcu_ports = set(ports)
            for p in serial.tools.list_ports.comports():
                if p.device not in mcu_ports and p.vid is not None:
                    ws_port = p.device
                    break
        if ws_port is None:
            raise RuntimeError("Waveshare servo backend configured but no serial port found. Set servo.port in config.")

        gc.logger.info(f"Using Waveshare SC servo bus on {ws_port}")
        ws_bus = ScServoBus(ws_port)

        for i, layer in enumerate(irl_interface.distribution_layout.layers):
            if i >= len(waveshare_config.channels):
                raise IndexError(
                    f"Layer {i} servo not configured. Only {len(waveshare_config.channels)} servo.channels defined."
                )
            ch_cfg = waveshare_config.channels[i]
            servo = WaveshareServoMotor(ws_bus, ch_cfg.id, invert=ch_cfg.invert)
            servo.initialize()
            servo.set_name(f"layer_{i}_servo")
            irl_interface.servos.append(servo)
            gc.logger.info(
                f"Initialized Waveshare Servo 'layer_{i}_servo' id={ch_cfg.id}, "
                f"range={servo._min_limit}-{servo._max_limit}, invert={ch_cfg.invert}"
            )
    else:
        # Default: PCA9685 servos via SorterInterface
        if servo_source is None:
            gc.logger.warning("No servo-capable SorterInterface detected")
            servo_source = next(iter(irl_interface.interfaces.values()))

        for i, layer in enumerate(irl_interface.distribution_layout.layers):
            if i >= len(servo_source.servos):
                gc.logger.error(f"Not enough servos! Layer {i} requested but only {len(servo_source.servos)} servos available")
                raise IndexError(f"Layer {i} servo not available. Only {len(servo_source.servos)} servos configured.")
            servo = servo_source.servos[i]
            servo.set_name(f"layer_{i}_servo")
            servo.set_preset_angles(servo_open_angle, servo_closed_angle)
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

    CHUTE_HOME_PIN_CHANNEL = 0
    if distribution_board is None:
        raise RuntimeError("Distribution board not found — cannot initialize chute homing")
    chute_home_pin = distribution_board.digital_inputs[CHUTE_HOME_PIN_CHANNEL]

    irl_interface.chute = Chute(
        gc, irl_interface.chute_stepper, chute_home_pin, irl_interface.distribution_layout
    )

    return irl_interface
