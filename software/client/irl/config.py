import time

from global_config import GlobalConfig
from hardware.bus import MCUBus
from hardware.sorter_interface import SorterInterface
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor, ServoMotor
    from subsystems.distribution.chute import Chute

from .bin_layout import (
    BinLayoutConfig,
    LayerConfig,
    DEFAULT_BIN_LAYOUT,
    DistributionLayout,
    mkLayoutFromConfig,
)
from .parse_user_toml import (
    loadMachineConfig,
    applyStepperCurrentOverride,
)


# Locked manual controls for the classification cameras. These disable the
# camera's auto exposure / white balance / gain so the backlit magenta floor
# reads a stable, consistent color for HSV-based detection. Values are starting
# points to be tuned empirically per machine; re-capture the classification
# baseline after changing them (the absolute levels shift once auto is off).
CLASSIFICATION_CAMERA_LOCK = {
    "auto_exposure": False,
    "exposure": 3.0,
    "auto_wb": False,
    "wb_temperature": 5971.0,
    "auto_gain": False,
    "gain": 0.0,
    "hue": -15.0,
    "saturation": 100.0,
}

# UVC product name of the classification top camera, used to lock its controls
# out-of-band via the uvc-util utility on macOS (AVFoundation ignores OpenCV's
# property sets, so the values above are no-ops there). On V4L2 (Linux) the locks
# go through OpenCV directly and this is unused. Machine-specific.
CLASSIFICATION_TOP_UVC_NAME = "Innomaker-U20CAM-1080p-S1"

# Locked manual controls for the carousel camera. Same out-of-band lock mechanism
# as the classification cameras (see CLASSIFICATION_CAMERA_LOCK / camera.py), so
# the carousel scene reads a stable, consistent color/brightness for detection.
# Fresh neutral starting point (autos off, controls at their UVC defaults) — tune
# empirically for the carousel scene with scripts/calibrate_camera_color.py
# --camera carousel, then re-capture the carousel baseline.
CAROUSEL_CAMERA_LOCK = {
    "auto_exposure": False,
    "exposure": 830.0,        # UVC exposure-time-abs default
    "auto_wb": False,
    "wb_temperature": 3757.0,  # UVC white-balance-temp default
    "auto_gain": False,
    "gain": 0.0,
    "hue": 0.0,
    "saturation": 64.0,        # UVC saturation default
}

# UVC product name of the carousel camera, as reported by *uvc-util* (which can
# differ from the AVFoundation/system_profiler name used for capture: this is the
# Arducam, which uvc-util calls "USB 2.0 Camera" while AVFoundation calls it
# "Arducam IMX323 USB2.0 Camera"). Must be a DIFFERENT physical camera than
# CLASSIFICATION_TOP_UVC_NAME, or their locks fight over one camera.
CAROUSEL_UVC_NAME = "USB 2.0 Camera"

# Carousel detection method: "gray" keeps the legacy grayscale single-snapshot
# diff (captureBaseline + CarouselDiffConfig); "hsv" uses the same HSV rotational-
# envelope pipeline as the classification chamber (calibrate_classification_baseline
# --camera carousel + the HSV heatmap). Selectable per machine.
CAROUSEL_DETECTION_MODE = "gray"


class CameraConfig:
    device_index: int
    width: int
    height: int
    fps: int
    # Optional manual camera controls. None => leave at driver default (do not
    # touch). Locking these is required for color-stable HSV detection.
    auto_exposure: "bool | None"
    exposure: "float | None"
    auto_wb: "bool | None"
    wb_temperature: "float | None"
    auto_gain: "bool | None"
    gain: "float | None"
    hue: "float | None"
    saturation: "float | None"
    # UVC product name for out-of-band control locking via uvc-util on macOS,
    # where OpenCV/AVFoundation cannot set these properties. None => not used.
    uvc_device_name: "str | None"

    def __init__(self):
        self.auto_exposure = None
        self.exposure = None
        self.auto_wb = None
        self.wb_temperature = None
        self.auto_gain = None
        self.gain = None
        self.hue = None
        self.saturation = None
        self.uvc_device_name = None


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
    # Cameras are optional — a machine may not have a feeder, a bottom
    # classification camera, etc. Absent ones are None and consumers degrade.
    feeder_camera: "CameraConfig | None"
    classification_camera_bottom: "CameraConfig | None"
    classification_camera_top: "CameraConfig | None"
    c_channel_2_camera: "CameraConfig | None"
    c_channel_3_camera: "CameraConfig | None"
    carousel_camera: "CameraConfig | None"
    carousel_stepper: StepperConfig
    chute_stepper: StepperConfig
    first_c_channel_rotor_stepper: StepperConfig
    second_c_channel_rotor_stepper: StepperConfig
    third_c_channel_rotor_stepper: StepperConfig
    aruco_tags: ArucoTagConfig
    feeder_config: FeederConfig
    carousel_trigger_score: "float | None"

    def __init__(self):
        self.feeder_config = FeederConfig()
        self.feeder_camera = None
        self.classification_camera_bottom = None
        self.classification_camera_top = None
        self.c_channel_2_camera = None
        self.c_channel_3_camera = None
        self.carousel_camera = None
        self.carousel_trigger_score = None


class IRLInterface:
    carousel_stepper: "StepperMotor"
    chute_stepper: "StepperMotor"
    first_c_channel_rotor_stepper: "StepperMotor"
    second_c_channel_rotor_stepper: "StepperMotor"
    third_c_channel_rotor_stepper: "StepperMotor"
    servos: "list[ServoMotor]"
    chute: "Chute"
    distribution_layout: DistributionLayout
    interfaces: dict[str, SorterInterface]

    def __init__(self):
        self.interfaces: dict[str, SorterInterface] = {}

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

    def shutdown(self) -> None:
        self.disableSteppers()
        for iface in self.interfaces.values():
            iface.shutdown()


def mkCameraConfig(
    device_index: int,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    auto_exposure: "bool | None" = None,
    exposure: "float | None" = None,
    auto_wb: "bool | None" = None,
    wb_temperature: "float | None" = None,
    auto_gain: "bool | None" = None,
    gain: "float | None" = None,
    hue: "float | None" = None,
    saturation: "float | None" = None,
    uvc_device_name: "str | None" = None,
) -> CameraConfig:
    camera_config = CameraConfig()
    camera_config.device_index = device_index
    camera_config.width = width
    camera_config.height = height
    camera_config.fps = fps
    camera_config.auto_exposure = auto_exposure
    camera_config.exposure = exposure
    camera_config.auto_wb = auto_wb
    camera_config.wb_temperature = wb_temperature
    camera_config.auto_gain = auto_gain
    camera_config.gain = gain
    camera_config.hue = hue
    camera_config.saturation = saturation
    camera_config.uvc_device_name = uvc_device_name
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


def mkIRLConfig() -> IRLConfig:
    irl_config = IRLConfig()
    # Resolve each role to its CURRENT cv2 index by stable camera identity
    # (name + USB location), since power cycles can reorder indices. Falls back
    # to the stored index if a camera can't be resolved. See camera_resolver.
    from hardware.camera_resolver import resolveCameraSetup
    camera_setup = resolveCameraSetup()

    if not camera_setup:
        raise RuntimeError(
            "No camera setup found. Run client/scripts/camera_setup.py first."
        )

    # Cameras are optional: build each role only if it's assigned. Missing
    # cameras stay None and consumers (VisionManager) degrade gracefully, so a
    # machine without e.g. a feeder still runs.
    def cameraIndex(role: str) -> "int | None":
        idx = camera_setup.get(role)
        if idx is None:
            print(f"[config] camera '{role}' not assigned; that subsystem is disabled.")
        return idx

    feeder_idx = cameraIndex("feeder")
    if feeder_idx is not None:
        irl_config.feeder_camera = mkCameraConfig(device_index=feeder_idx)

    bottom_idx = cameraIndex("classification_bottom")
    if bottom_idx is not None:
        irl_config.classification_camera_bottom = mkCameraConfig(
            device_index=bottom_idx, width=9999, height=9999,
            **CLASSIFICATION_CAMERA_LOCK,
        )

    top_idx = cameraIndex("classification_top")
    if top_idx is not None:
        irl_config.classification_camera_top = mkCameraConfig(
            device_index=top_idx, width=9999, height=9999,
            uvc_device_name=CLASSIFICATION_TOP_UVC_NAME,
            **CLASSIFICATION_CAMERA_LOCK,
        )

    if "c_channel_2" in camera_setup:
        irl_config.c_channel_2_camera = mkCameraConfig(device_index=camera_setup["c_channel_2"])
    if "c_channel_3" in camera_setup:
        irl_config.c_channel_3_camera = mkCameraConfig(device_index=camera_setup["c_channel_3"])
    if "carousel" in camera_setup:
        irl_config.carousel_camera = mkCameraConfig(
            device_index=camera_setup["carousel"], width=9999, height=9999,
            uvc_device_name=CAROUSEL_UVC_NAME,
            **CAROUSEL_CAMERA_LOCK,
        )

    irl_config.carousel_stepper = mkStepperConfig(default_steps_per_second=500, microsteps=16)
    irl_config.chute_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.first_c_channel_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.second_c_channel_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.third_c_channel_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)

    irl_config.aruco_tags = mkArucoTagConfig()
    return irl_config


def mkIRLInterface(config: IRLConfig, gc: GlobalConfig) -> IRLInterface:
    """
    Initialize the hardware interface using SorterInterface directly.

    Uses SorterInterface firmware and dynamic stepper name discovery.
    The firmware reports which steppers are available via stepper_names.
    """
    irl_interface = IRLInterface()
    machine_config = loadMachineConfig(gc)
    stepper_current_overrides = machine_config.stepper_current_overrides
    config.carousel_trigger_score = machine_config.carousel_trigger_score

    if config.c_channel_2_camera is not None:
        gc.logger.info(f"Split-feeder mode: c_channel_2 camera index={config.c_channel_2_camera.device_index}")
    if config.c_channel_3_camera is not None:
        gc.logger.info(f"Split-feeder mode: c_channel_3 camera index={config.c_channel_3_camera.device_index}")
    if config.carousel_camera is not None:
        gc.logger.info(f"Carousel camera index={config.carousel_camera.device_index}")

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

    bin_layout = BinLayoutConfig(layers=[
        LayerConfig(sections=s) for s in machine_config.layer_sections
    ]) if machine_config.layer_sections else DEFAULT_BIN_LAYOUT
    irl_interface.distribution_layout = mkLayoutFromConfig(bin_layout)

    # Initialize servos directly from sorter_interface
    irl_interface.servos = []
    if servo_source is None:
        gc.logger.warning("No servo-capable SorterInterface detected")
        servo_source = next(iter(irl_interface.interfaces.values()))

    for i in range(len(irl_interface.distribution_layout.layers)):
        if i >= len(servo_source.servos):
            gc.logger.error(f"Not enough servos! Layer {i} requested but only {len(servo_source.servos)} servos available")
            raise IndexError(f"Layer {i} servo not available. Only {len(servo_source.servos)} servos configured.")
        servo = servo_source.servos[i]
        servo.set_name(f"layer_{i}_servo")
        open_angle = machine_config.servo_open_angle_overrides.get(i, machine_config.servo_open_angle)
        closed_angle = machine_config.servo_closed_angle_overrides.get(i, machine_config.servo_closed_angle)
        servo.set_preset_angles(open_angle, closed_angle)
        irl_interface.servos.append(servo)
        gc.logger.info(f"Initialized Servo 'layer_{i}_servo' on channel {i}, open={open_angle}° closed={closed_angle}°")


    from subsystems.distribution.chute import Chute

    CHUTE_HOME_PIN_CHANNEL = 0
    if distribution_board is None:
        raise RuntimeError("Distribution board not found — cannot initialize chute homing")
    chute_home_pin = distribution_board.digital_inputs[CHUTE_HOME_PIN_CHANNEL]

    chute_kwargs = {}
    if machine_config.first_bin_center is not None:
        chute_kwargs["first_section_center"] = machine_config.first_bin_center
    if machine_config.pillar_width_deg is not None:
        chute_kwargs["pillar_width_deg"] = machine_config.pillar_width_deg
    if machine_config.chute_home_direction is not None:
        chute_kwargs["home_direction"] = machine_config.chute_home_direction
    if machine_config.chute_home_angle is not None:
        chute_kwargs["home_angle"] = machine_config.chute_home_angle
    irl_interface.chute = Chute(
        gc, irl_interface.chute_stepper, chute_home_pin, irl_interface.distribution_layout,
        **chute_kwargs
    )

    return irl_interface
