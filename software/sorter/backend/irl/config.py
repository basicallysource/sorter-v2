import os
import time
from dataclasses import dataclass

from global_config import GlobalConfig
from hardware.bus import MCUBus, MCUBusError
from hardware.cobs import DecodeError
from hardware.sorter_interface import SorterInterface
from machine_platform import (
    build_machine_profile,
    build_servo_controller,
    discover_control_boards,
)
from machine_setup import (
    DEFAULT_MACHINE_SETUP,
    MachineSetupDefinition,
    get_machine_setup_definition,
)
from role_aliases import (
    lookup_camera_role_keys,
    public_aux_camera_role,
    stored_camera_role_key,
)
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from machine_platform.control_board import ControlBoard
    from machine_platform.machine_profile import MachineProfile
    from machine_platform.servo_controller import ServoController
    from hardware.sorter_interface import StepperMotor, ServoMotor, DigitalInputPin
    from subsystems.classification.carousel_hardware import CarouselHardware
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
    LOGICAL_STEPPER_BINDING_BASES,
    loadMachineSetupConfig,
    loadMachineConfig,
    loadMachineSpecificParams,
    loadStepperBindingOverrides,
    loadStepperCurrentOverrides,
    loadStepperDirectionInverts,
    loadServoChannelConfig,
    loadWaveshareServoConfig,
    loadCarouselCalibrationConfig,
    loadChuteCalibrationConfig,
    loadCameraLayoutConfig,
    applyStepperCurrentOverride,
)
from blob_manager import getBinCategories
from local_state import get_servo_states, set_servo_states

HARDWARE_INIT_COMMAND_ATTEMPTS = 4
HARDWARE_INIT_RETRY_DELAY_S = 0.2


def _run_stepper_init_command_with_retry(
    gc: GlobalConfig,
    stepper_name: str,
    description: str,
    command,
    *,
    attempts: int = HARDWARE_INIT_COMMAND_ATTEMPTS,
    retry_delay_s: float = HARDWARE_INIT_RETRY_DELAY_S,
) -> bool:
    for attempt in range(1, attempts + 1):
        try:
            command()
            return True
        except (MCUBusError, OSError, DecodeError) as exc:
            if attempt == attempts:
                gc.logger.warning(
                    f"Failed to apply {description} for stepper '{stepper_name}' after "
                    f"{attempts} attempts: {exc}. Continuing."
                )
                return False
            gc.logger.warning(
                f"Failed to apply {description} for stepper '{stepper_name}' on "
                f"attempt {attempt}/{attempts}: {exc}. Retrying in {retry_delay_s:.2f}s..."
            )
            time.sleep(retry_delay_s)

    return False


def save_servo_states(servos: list, gc: GlobalConfig) -> None:
    states = {}
    for i, servo in enumerate(servos):
        is_open = getattr(servo, "isOpen", lambda: None)()
        if is_open is not None:
            states[str(i)] = {"is_open": is_open}
    try:
        set_servo_states(states)
    except Exception as e:
        gc.logger.warning(f"Failed to save servo states: {e}")


def restore_servo_states(servos: list, gc: GlobalConfig) -> None:
    try:
        states = get_servo_states()
    except Exception as e:
        gc.logger.warning(f"Failed to load servo states: {e}")
        return

    if not states:
        return

    for i, servo in enumerate(servos):
        entry = states.get(str(i))
        if entry is None:
            continue
        was_open = entry.get("is_open")
        if was_open is None:
            continue
        try:
            if was_open:
                servo.open()
            else:
                servo.close()
            gc.logger.info(f"Restored servo {i} to {'open' if was_open else 'closed'}")
        except Exception as e:
            gc.logger.warning(f"Failed to restore servo {i}: {e}")


class CameraConfig:
    device_index: int
    url: str | None  # if set, use URL instead of device_index
    width: int
    height: int
    fps: int
    fourcc: str | None
    picture_settings: "CameraPictureSettings"
    device_settings: dict[str, int | float | bool]
    color_profile: "CameraColorProfile"

    def __init__(self):
        self.url = None
        self.fourcc = None


class CameraPictureSettings:
    rotation: int
    flip_horizontal: bool
    flip_vertical: bool

    def __init__(
        self,
        rotation: int = 0,
        flip_horizontal: bool = False,
        flip_vertical: bool = False,
    ):
        self.rotation = rotation
        self.flip_horizontal = flip_horizontal
        self.flip_vertical = flip_vertical


class CameraColorProfile:
    enabled: bool
    matrix: list[list[float]]
    bias: list[float]
    response_lut_r: list[float] | None
    response_lut_g: list[float] | None
    response_lut_b: list[float] | None
    gamma_a: list[float] | None
    gamma_exp: list[float] | None
    gamma_b: list[float] | None

    def __init__(
        self,
        enabled: bool = False,
        matrix: list[list[float]] | None = None,
        bias: list[float] | None = None,
        response_lut_r: list[float] | None = None,
        response_lut_g: list[float] | None = None,
        response_lut_b: list[float] | None = None,
        gamma_a: list[float] | None = None,
        gamma_exp: list[float] | None = None,
        gamma_b: list[float] | None = None,
    ):
        self.enabled = enabled
        self.matrix = matrix or [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
        self.bias = bias or [0.0, 0.0, 0.0]
        self.response_lut_r = response_lut_r
        self.response_lut_g = response_lut_g
        self.response_lut_b = response_lut_b
        self.gamma_a = gamma_a
        self.gamma_exp = gamma_exp
        self.gamma_b = gamma_b


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
    acceleration_microsteps_per_second_sq: int | None

    def __init__(
        self,
        steps: int,
        microsteps_per_second: int,
        delay_between_ms: int,
        acceleration_microsteps_per_second_sq: int | None = None,
    ):
        self.steps_per_pulse = steps
        self.microsteps_per_second = microsteps_per_second
        self.delay_between_pulse_ms = delay_between_ms
        self.acceleration_microsteps_per_second_sq = (
            int(acceleration_microsteps_per_second_sq)
            if acceleration_microsteps_per_second_sq is not None
            else None
        )


@dataclass(frozen=True)
class ClassificationChannelSizeClassConfig:
    name: str
    max_measured_half_width_deg: float
    body_half_width_deg: float
    soft_guard_deg: float
    hard_guard_deg: float


class ClassificationChannelConfig:
    use_dynamic_zones: bool
    max_zones: int
    intake_angle_deg: float
    intake_body_half_width_deg: float
    intake_guard_deg: float
    drop_angle_deg: float
    drop_tolerance_deg: float
    point_of_no_return_deg: float
    recognition_window_deg: float
    positioning_window_deg: float
    exit_release_overlap_ratio: float
    exit_release_shimmy_amplitude_deg: float
    exit_release_shimmy_cycles: int
    exit_release_shimmy_microsteps_per_second: int | None
    exit_release_shimmy_acceleration_microsteps_per_second_sq: int | None
    stale_zone_timeout_s: float
    hood_dwell_ms: int
    min_carousel_crops_for_recognize: int
    min_carousel_dwell_ms: int
    min_carousel_traversal_deg: float
    size_downgrade_confirmations: int
    size_classes: tuple[ClassificationChannelSizeClassConfig, ...]
    leader_wins_policy: bool
    leader_wins_requires_classified: bool
    post_distribute_cooldown_s: float

    def __init__(self) -> None:
        self.use_dynamic_zones = True
        # Raised from 2 -> 4 after pipeline stabilization (OSNet fix,
        # liveness probe, leader-wins). Physical safety (arc-clear check,
        # hard-collision guards, leader-wins) still prevents double-drops;
        # this cap only governs how many pieces C4 accepts before throttling
        # C3. Upstream gates (admission.py, running.py) pick this up
        # automatically — no other call sites hardcode the old value.
        self.max_zones = 4
        self.intake_angle_deg = 305.0
        self.intake_body_half_width_deg = 10.0
        self.intake_guard_deg = 28.0
        # Live calibration on the dedicated classification channel shows the
        # real guide / point-of-no-return on the lower-right quadrant, not on
        # the legacy left-side position from the old chamber model.
        self.drop_angle_deg = 30.0
        self.drop_tolerance_deg = 14.0
        self.point_of_no_return_deg = 18.0
        self.recognition_window_deg = 170.0
        self.positioning_window_deg = 48.0
        self.exit_release_overlap_ratio = 0.5
        self.exit_release_shimmy_amplitude_deg = 1.5
        self.exit_release_shimmy_cycles = 2
        self.exit_release_shimmy_microsteps_per_second = 4200
        self.exit_release_shimmy_acceleration_microsteps_per_second_sq = 9000
        self.stale_zone_timeout_s = 3.0
        self.hood_dwell_ms = 300
        # Minimum number of carousel-source crops required before the
        # recognizer may fire for a piece. Prevents recognition from
        # committing using only c_channel_2/c_channel_3 history (which, if
        # misbound, can belong to a different piece still upstream).
        self.min_carousel_crops_for_recognize = 2
        # Minimum elapsed time since the piece's first carousel-source
        # observation before recognition may fire. Guards against a
        # freshly-spawned carousel track that briefly stacks 2+ crops in
        # quick succession but hasn't yet stabilized on the physical C4 tray.
        self.min_carousel_dwell_ms = 300
        # Minimum angular traversal on the carousel (degrees) since the
        # piece was first observed there before recognition may fire.
        # Time-based gates don't guarantee viewing-angle diversity when the
        # carousel rotates fast; this ensures the piece has physically
        # rotated enough to present multiple sides to the C4 camera, so the
        # accumulated crops cover meaningfully different viewpoints.
        self.min_carousel_traversal_deg = 30.0
        self.size_downgrade_confirmations = 3
        # Leader-wins drop policy: when the drop candidate has an interferer
        # inside the clearance window, only flip the *leader* to
        # ``multi_drop_fail`` if the interferer is strictly trailing (hasn't
        # reached drop yet). Spares the trailer so it can take its own drop
        # cycle next rotation instead of being discarded with the leader.
        self.leader_wins_policy = True
        # When True, the spare-the-trailer path only activates if the leader
        # already has a part_id (i.e. status == classified). Keeps the old
        # "both fail" behavior for pending/classifying leaders where the
        # carousel pulse would otherwise burn through an unrecognized piece.
        self.leader_wins_requires_classified = False
        # Minimum cooldown (seconds) the distribution Sending state waits
        # *after* the chute-settle timer before it reopens the downstream
        # distribution gate. Used as the fallback when the live carousel
        # tracker can't confirm that the dropped piece has physically
        # left the classification channel. Physical transit measures at
        # ~400-600ms; 0.8s adds margin while keeping throughput impact
        # below ~5%.
        self.post_distribute_cooldown_s = 0.8
        self.size_classes = (
            ClassificationChannelSizeClassConfig(
                name="S",
                max_measured_half_width_deg=6.0,
                body_half_width_deg=7.0,
                soft_guard_deg=8.0,
                hard_guard_deg=11.0,
            ),
            ClassificationChannelSizeClassConfig(
                name="M",
                max_measured_half_width_deg=11.0,
                body_half_width_deg=11.0,
                soft_guard_deg=10.0,
                hard_guard_deg=14.0,
            ),
            ClassificationChannelSizeClassConfig(
                name="L",
                max_measured_half_width_deg=18.0,
                body_half_width_deg=17.0,
                soft_guard_deg=14.0,
                hard_guard_deg=18.0,
            ),
            ClassificationChannelSizeClassConfig(
                name="XL",
                max_measured_half_width_deg=360.0,
                body_half_width_deg=24.0,
                soft_guard_deg=18.0,
                hard_guard_deg=24.0,
            ),
        )


class FeederConfig:
    first_rotor: RotorPulseConfig
    second_rotor_normal: RotorPulseConfig
    second_rotor_precision: RotorPulseConfig
    third_rotor_normal: RotorPulseConfig
    third_rotor_precision: RotorPulseConfig
    classification_channel_eject: RotorPulseConfig
    first_rotor_jam_timeout_s: float
    first_rotor_jam_min_pulses: int
    first_rotor_jam_retry_cooldown_s: float
    first_rotor_jam_backtrack_output_degrees: float
    first_rotor_jam_max_output_degrees: float
    first_rotor_jam_max_cycles: int

    def __init__(self):
        self.first_rotor = RotorPulseConfig(
            steps=100,
            microsteps_per_second=2000,
            delay_between_ms=1000,
        )
        self.second_rotor_normal = RotorPulseConfig(
            steps=1000,
            microsteps_per_second=5000,
            delay_between_ms=250,
        )
        self.second_rotor_precision = RotorPulseConfig(
            steps=400,
            microsteps_per_second=2500,
            delay_between_ms=1000,
        )
        self.third_rotor_normal = RotorPulseConfig(
            steps=1000,
            microsteps_per_second=5000,
            delay_between_ms=250,
        )
        self.third_rotor_precision = RotorPulseConfig(
            steps=300,
            microsteps_per_second=3000,
            delay_between_ms=1000,
        )
        self.classification_channel_eject = RotorPulseConfig(
            steps=1000,
            microsteps_per_second=3400,
            delay_between_ms=400,
            acceleration_microsteps_per_second_sq=2500,
        )
        self.first_rotor_jam_timeout_s = 10.0
        self.first_rotor_jam_min_pulses = 6
        self.first_rotor_jam_retry_cooldown_s = 8.0
        self.first_rotor_jam_backtrack_output_degrees = 18.0
        self.first_rotor_jam_max_output_degrees = 30.0
        self.first_rotor_jam_max_cycles = 5


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
    classification_channel_config: ClassificationChannelConfig
    feeding_mode: str
    machine_setup: MachineSetupDefinition

    def __init__(self):
        self.camera_layout = "default"
        self.c_channel_2_camera = None
        self.c_channel_3_camera = None
        self.carousel_camera = None
        self.feeder_config = FeederConfig()
        self.classification_channel_config = ClassificationChannelConfig()
        self.feeding_mode = "auto_channels"
        self.machine_setup = get_machine_setup_definition(DEFAULT_MACHINE_SETUP)


class IRLInterface:
    carousel_stepper: "StepperMotor"
    carousel_home_pin: "DigitalInputPin"
    carousel_hw: "CarouselHardware"
    chute_stepper: "StepperMotor"
    c_channel_1_rotor_stepper: "StepperMotor"
    c_channel_2_rotor_stepper: "StepperMotor"
    c_channel_3_rotor_stepper: "StepperMotor"
    servos: "list[ServoMotor]"
    chute: "Chute"
    distribution_layout: DistributionLayout
    interfaces: dict[str, SorterInterface]
    control_boards: dict[str, "ControlBoard"]
    servo_controller: "ServoController | None"
    machine_profile: "MachineProfile | None"

    def __init__(self):
        self.interfaces: dict[str, SorterInterface] = {}
        self.control_boards = {}
        self.servo_controller = None
        self.machine_profile = None

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
        if self.servo_controller is not None and hasattr(self.servo_controller, "shutdown"):
            try:
                self.servo_controller.shutdown()
            except Exception:
                pass
        for iface in self.interfaces.values():
            iface.shutdown()


def mkCameraConfig(
    device_index: int = -1, width: int = 1920, height: int = 1080, fps: int = 30,
    url: str | None = None,
    fourcc: str | None = None,
    picture_settings: CameraPictureSettings | None = None,
    device_settings: dict[str, int | float | bool] | None = None,
    color_profile: CameraColorProfile | None = None,
) -> CameraConfig:
    camera_config = CameraConfig()
    camera_config.device_index = device_index
    camera_config.url = url
    camera_config.width = width
    camera_config.height = height
    camera_config.fps = fps
    camera_config.fourcc = fourcc
    camera_config.picture_settings = picture_settings or mkCameraPictureSettings()
    camera_config.device_settings = parseCameraDeviceSettings(device_settings)
    camera_config.color_profile = color_profile or mkCameraColorProfile()
    return camera_config


def mkCameraPictureSettings(
    rotation: int = 0,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
) -> CameraPictureSettings:
    return CameraPictureSettings(
        rotation=rotation,
        flip_horizontal=flip_horizontal,
        flip_vertical=flip_vertical,
    )


def clampCameraPictureSettings(settings: CameraPictureSettings) -> CameraPictureSettings:
    def _number(value: object, default: float) -> float:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default

    rotation = int(round(_number(getattr(settings, "rotation", 0), 0.0)))
    rotation = (round(rotation / 90) * 90) % 360
    flip_horizontal = bool(getattr(settings, "flip_horizontal", False))
    flip_vertical = bool(getattr(settings, "flip_vertical", False))

    return mkCameraPictureSettings(
        rotation=rotation,
        flip_horizontal=flip_horizontal,
        flip_vertical=flip_vertical,
    )


def parseCameraPictureSettings(raw: object) -> CameraPictureSettings:
    if not isinstance(raw, dict):
        return mkCameraPictureSettings()

    return clampCameraPictureSettings(
        mkCameraPictureSettings(
            rotation=raw.get("rotation", 0),
            flip_horizontal=raw.get("flip_horizontal", False),
            flip_vertical=raw.get("flip_vertical", False),
        )
    )


def cameraPictureSettingsToDict(settings: CameraPictureSettings) -> dict[str, int | float | bool]:
    clamped = clampCameraPictureSettings(settings)
    return {
        "rotation": clamped.rotation,
        "flip_horizontal": clamped.flip_horizontal,
        "flip_vertical": clamped.flip_vertical,
    }


def mkCameraColorProfile(
    enabled: bool = False,
    matrix: list[list[float]] | None = None,
    bias: list[float] | None = None,
    response_lut_r: list[float] | None = None,
    response_lut_g: list[float] | None = None,
    response_lut_b: list[float] | None = None,
    gamma_a: list[float] | None = None,
    gamma_exp: list[float] | None = None,
    gamma_b: list[float] | None = None,
) -> CameraColorProfile:
    return CameraColorProfile(
        enabled=enabled,
        matrix=matrix,
        bias=bias,
        response_lut_r=response_lut_r,
        response_lut_g=response_lut_g,
        response_lut_b=response_lut_b,
        gamma_a=gamma_a,
        gamma_exp=gamma_exp,
        gamma_b=gamma_b,
    )


def clampCameraColorProfile(profile: CameraColorProfile) -> CameraColorProfile:
    def _number(value: object, default: float) -> float:
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default

    raw_matrix = getattr(profile, "matrix", None)
    matrix_rows: list[list[float]] = []
    if isinstance(raw_matrix, list):
        for row_index, raw_row in enumerate(raw_matrix[:3]):
            if isinstance(raw_row, list):
                row = [
                    _number(raw_row[col_index] if col_index < len(raw_row) else 1.0 if row_index == col_index else 0.0,
                            1.0 if row_index == col_index else 0.0)
                    for col_index in range(3)
                ]
            else:
                row = [1.0 if row_index == col_index else 0.0 for col_index in range(3)]
            matrix_rows.append(row)
    while len(matrix_rows) < 3:
        row_index = len(matrix_rows)
        matrix_rows.append([1.0 if row_index == col_index else 0.0 for col_index in range(3)])

    raw_bias = getattr(profile, "bias", None)
    bias_values: list[float] = []
    if isinstance(raw_bias, list):
        bias_values = [
            _number(raw_bias[index] if index < len(raw_bias) else 0.0, 0.0)
            for index in range(3)
        ]
    while len(bias_values) < 3:
        bias_values.append(0.0)

    def _parse_float_list(attr_name: str, length: int) -> list[float] | None:
        raw = getattr(profile, attr_name, None)
        if not isinstance(raw, list) or len(raw) < length:
            return None
        values = [_number(v, 0.0) for v in raw[:length]]
        return values

    return mkCameraColorProfile(
        enabled=bool(getattr(profile, "enabled", False)),
        matrix=matrix_rows,
        bias=bias_values,
        response_lut_r=_parse_float_list("response_lut_r", 256),
        response_lut_g=_parse_float_list("response_lut_g", 256),
        response_lut_b=_parse_float_list("response_lut_b", 256),
        gamma_a=_parse_float_list("gamma_a", 3),
        gamma_exp=_parse_float_list("gamma_exp", 3),
        gamma_b=_parse_float_list("gamma_b", 3),
    )


def parseCameraColorProfile(raw: object) -> CameraColorProfile:
    if not isinstance(raw, dict):
        return mkCameraColorProfile()

    return clampCameraColorProfile(
        mkCameraColorProfile(
            enabled=bool(raw.get("enabled", False)),
            matrix=raw.get("matrix") if isinstance(raw.get("matrix"), list) else None,
            bias=raw.get("bias") if isinstance(raw.get("bias"), list) else None,
            response_lut_r=raw.get("response_lut_r") if isinstance(raw.get("response_lut_r"), list) else None,
            response_lut_g=raw.get("response_lut_g") if isinstance(raw.get("response_lut_g"), list) else None,
            response_lut_b=raw.get("response_lut_b") if isinstance(raw.get("response_lut_b"), list) else None,
            gamma_a=raw.get("gamma_a") if isinstance(raw.get("gamma_a"), list) else None,
            gamma_exp=raw.get("gamma_exp") if isinstance(raw.get("gamma_exp"), list) else None,
            gamma_b=raw.get("gamma_b") if isinstance(raw.get("gamma_b"), list) else None,
        )
    )


def cameraColorProfileToDict(profile: CameraColorProfile) -> dict[str, object]:
    clamped = clampCameraColorProfile(profile)
    result: dict[str, object] = {
        "enabled": clamped.enabled,
        "matrix": [[float(value) for value in row] for row in clamped.matrix],
        "bias": [float(value) for value in clamped.bias],
    }
    if clamped.response_lut_r is not None:
        result["response_lut_r"] = [float(v) for v in clamped.response_lut_r]
    if clamped.response_lut_g is not None:
        result["response_lut_g"] = [float(v) for v in clamped.response_lut_g]
    if clamped.response_lut_b is not None:
        result["response_lut_b"] = [float(v) for v in clamped.response_lut_b]
    if clamped.gamma_a is not None:
        result["gamma_a"] = [float(v) for v in clamped.gamma_a]
    if clamped.gamma_exp is not None:
        result["gamma_exp"] = [float(v) for v in clamped.gamma_exp]
    if clamped.gamma_b is not None:
        result["gamma_b"] = [float(v) for v in clamped.gamma_b]
    return result


def parseCameraDeviceSettings(raw: object) -> dict[str, int | float | bool]:
    if not isinstance(raw, dict):
        return {}

    result: dict[str, int | float | bool] = {}
    bool_keys = {
        "auto_exposure",
        "auto_white_balance",
        "autofocus",
    }
    float_keys = {
        "brightness",
        "contrast",
        "saturation",
        "sharpness",
        "gamma",
        "gain",
        "exposure",
        "white_balance_temperature",
        "focus",
        "power_line_frequency",
        "backlight_compensation",
    }

    for key in bool_keys:
        value = raw.get(key)
        if isinstance(value, bool):
            result[key] = value

    for key in float_keys:
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            result[key] = float(value)

    return result


def cameraDeviceSettingsToDict(
    settings: dict[str, int | float | bool] | None,
) -> dict[str, int | float | bool]:
    return parseCameraDeviceSettings(settings)


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
    import os
    from toml_config import loadTomlFile
    camera_layout_type = "default"
    feeding_mode = "auto_channels"
    machine_setup_key = DEFAULT_MACHINE_SETUP
    raw_toml: dict[str, object] = {}
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if params_path and os.path.exists(params_path):
        raw_toml = loadTomlFile(params_path)
        cameras_section = raw_toml.get("cameras", {})
        if isinstance(cameras_section, dict):
            camera_layout_type = cameras_section.get("layout", "default")
        if camera_layout_type not in ("default", "split_feeder"):
            camera_layout_type = "default"

    class _SilentLogger:
        def warning(self, *args: object, **kwargs: object) -> None:
            return None

        def info(self, *args: object, **kwargs: object) -> None:
            return None

    class _SilentGlobalConfig:
        def __init__(self) -> None:
            self.logger = _SilentLogger()

    machine_setup_key = loadMachineSetupConfig(cast(Any, _SilentGlobalConfig()), raw_toml)
    machine_setup = get_machine_setup_definition(machine_setup_key)
    feeding_mode = machine_setup.feeding_mode

    picture_settings_section = {}
    if isinstance(raw_toml, dict):
        picture_settings_section = raw_toml.get("camera_picture_settings", {})
    device_settings_section = {}
    if isinstance(raw_toml, dict):
        device_settings_section = raw_toml.get("camera_device_settings", {})
    color_profiles_section = {}
    if isinstance(raw_toml, dict):
        color_profiles_section = raw_toml.get("camera_color_profiles", {})
    capture_modes_section = {}
    if isinstance(raw_toml, dict):
        capture_modes_section = raw_toml.get("camera_capture_modes", {})

    aux_camera_role = public_aux_camera_role(raw_toml)

    def _config_role(role: str) -> str:
        if role == "carousel":
            return stored_camera_role_key(role, raw_toml)
        return role

    def _camera_source(
        cameras_section: dict[str, object],
        role: str,
    ) -> object | None:
        for lookup_role in lookup_camera_role_keys(role, raw_toml):
            if lookup_role in cameras_section:
                return cameras_section.get(lookup_role)
        return None

    def _capture_mode(role: str) -> dict[str, int | str]:
        if not isinstance(capture_modes_section, dict):
            return {}
        entry = capture_modes_section.get(_config_role(role))
        if not isinstance(entry, dict):
            return {}
        out: dict[str, int | str] = {}
        for key in ("width", "height", "fps"):
            value = entry.get(key)
            if isinstance(value, int) and value > 0:
                out[key] = value
        fourcc = entry.get("fourcc")
        if isinstance(fourcc, str) and fourcc.strip():
            out["fourcc"] = fourcc.strip()
        return out

    def _picture_settings(role: str) -> CameraPictureSettings:
        if not isinstance(picture_settings_section, dict):
            return mkCameraPictureSettings()
        return parseCameraPictureSettings(picture_settings_section.get(_config_role(role)))

    def _device_settings(role: str) -> dict[str, int | float | bool]:
        if not isinstance(device_settings_section, dict):
            return {}
        return parseCameraDeviceSettings(device_settings_section.get(_config_role(role)))

    def _color_profile(role: str) -> CameraColorProfile:
        if not isinstance(color_profiles_section, dict):
            return mkCameraColorProfile()
        return parseCameraColorProfile(color_profiles_section.get(_config_role(role)))

    def _mkCameraConfigForRole(role: str, **kwargs) -> CameraConfig:
        mode = _capture_mode(role)
        merged = dict(kwargs)
        for key in ("width", "height", "fps", "fourcc"):
            if key in mode and key not in merged:
                merged[key] = mode[key]
        return mkCameraConfig(**merged)

    irl_config.camera_layout = camera_layout_type
    irl_config.feeding_mode = feeding_mode
    irl_config.machine_setup = machine_setup

    if camera_layout_type == "split_feeder":
        # split_feeder: per-channel cameras from TOML, no single feeder or classification
        cameras_section = cast(dict[str, object], raw_toml.get("cameras", {})) if isinstance(raw_toml, dict) else {}

        c_ch2_idx = _camera_source(cameras_section, "c_channel_2")
        c_ch3_idx = _camera_source(cameras_section, "c_channel_3")
        carousel_source = _camera_source(cameras_section, aux_camera_role)

        if isinstance(c_ch2_idx, int):
            irl_config.c_channel_2_camera = _mkCameraConfigForRole(
                "c_channel_2",
                device_index=c_ch2_idx,
                picture_settings=_picture_settings("c_channel_2"),
                device_settings=_device_settings("c_channel_2"),
                color_profile=_color_profile("c_channel_2"),
            )
        if isinstance(c_ch3_idx, int):
            irl_config.c_channel_3_camera = _mkCameraConfigForRole(
                "c_channel_3",
                device_index=c_ch3_idx,
                picture_settings=_picture_settings("c_channel_3"),
                device_settings=_device_settings("c_channel_3"),
                color_profile=_color_profile("c_channel_3"),
            )
        if isinstance(carousel_source, str):
            irl_config.carousel_camera = _mkCameraConfigForRole(
                "carousel",
                url=carousel_source,
                picture_settings=_picture_settings("carousel"),
                device_settings=_device_settings("carousel"),
                color_profile=_color_profile("carousel"),
            )
        elif isinstance(carousel_source, int):
            irl_config.carousel_camera = _mkCameraConfigForRole(
                "carousel",
                device_index=carousel_source,
                picture_settings=_picture_settings("carousel"),
                device_settings=_device_settings("carousel"),
                color_profile=_color_profile("carousel"),
            )

        # Classification cameras (optional in split_feeder mode) — int or URL string
        cls_top = cameras_section.get("classification_top")
        cls_bottom = cameras_section.get("classification_bottom")

        if isinstance(cls_top, str):
            irl_config.classification_camera_top = _mkCameraConfigForRole(
                "classification_top",
                url=cls_top,
                picture_settings=_picture_settings("classification_top"),
                device_settings=_device_settings("classification_top"),
                color_profile=_color_profile("classification_top"),
            )
        elif isinstance(cls_top, int):
            irl_config.classification_camera_top = _mkCameraConfigForRole(
                "classification_top",
                device_index=cls_top,
                width=9999,
                height=9999,
                picture_settings=_picture_settings("classification_top"),
                device_settings=_device_settings("classification_top"),
                color_profile=_color_profile("classification_top"),
            )
        else:
            irl_config.classification_camera_top = _mkCameraConfigForRole(
                "classification_top",
                device_index=-1,
                picture_settings=_picture_settings("classification_top"),
                device_settings=_device_settings("classification_top"),
                color_profile=_color_profile("classification_top"),
            )

        if isinstance(cls_bottom, str):
            irl_config.classification_camera_bottom = _mkCameraConfigForRole(
                "classification_bottom",
                url=cls_bottom,
                picture_settings=_picture_settings("classification_bottom"),
                device_settings=_device_settings("classification_bottom"),
                color_profile=_color_profile("classification_bottom"),
            )
        elif isinstance(cls_bottom, int):
            irl_config.classification_camera_bottom = _mkCameraConfigForRole(
                "classification_bottom",
                device_index=cls_bottom,
                width=9999,
                height=9999,
                picture_settings=_picture_settings("classification_bottom"),
                device_settings=_device_settings("classification_bottom"),
                color_profile=_color_profile("classification_bottom"),
            )
        else:
            irl_config.classification_camera_bottom = _mkCameraConfigForRole(
                "classification_bottom",
                device_index=-1,
                picture_settings=_picture_settings("classification_bottom"),
                device_settings=_device_settings("classification_bottom"),
                color_profile=_color_profile("classification_bottom"),
            )

        # Dummy feeder camera so nothing crashes on attr access
        irl_config.feeder_camera = _mkCameraConfigForRole(
            "feeder",
            device_index=-1,
            picture_settings=_picture_settings("feeder"),
            device_settings=_device_settings("feeder"),
            color_profile=_color_profile("feeder"),
        )
    else:
        # default: single feeder + classification cameras from TOML [cameras]
        cameras_section = cast(dict[str, object], raw_toml.get("cameras", {})) if isinstance(raw_toml, dict) else {}

        feeder_camera_index = cameras_section.get("feeder")
        classification_camera_bottom_index = cameras_section.get("classification_bottom")
        classification_camera_top_index = cameras_section.get("classification_top")

        if feeder_camera_index is None and classification_camera_top_index is None:
            raise RuntimeError(
                "No camera setup found in TOML [cameras] section. "
                "Assign cameras from the Settings → Cameras page in the UI, or edit "
                "machine_params.toml directly."
            )

        if not isinstance(feeder_camera_index, int):
            feeder_camera_index = -1
        if not isinstance(classification_camera_bottom_index, int):
            classification_camera_bottom_index = -1
        if not isinstance(classification_camera_top_index, int):
            classification_camera_top_index = -1

        irl_config.feeder_camera = _mkCameraConfigForRole(
            "feeder",
            device_index=feeder_camera_index,
            picture_settings=_picture_settings("feeder"),
            device_settings=_device_settings("feeder"),
            color_profile=_color_profile("feeder"),
        )
        irl_config.classification_camera_bottom = _mkCameraConfigForRole(
            "classification_bottom",
            device_index=classification_camera_bottom_index,
            width=9999,
            height=9999,
            picture_settings=_picture_settings("classification_bottom"),
            device_settings=_device_settings("classification_bottom"),
            color_profile=_color_profile("classification_bottom"),
        )
        irl_config.classification_camera_top = _mkCameraConfigForRole(
            "classification_top",
            device_index=classification_camera_top_index,
            width=9999,
            height=9999,
            picture_settings=_picture_settings("classification_top"),
            device_settings=_device_settings("classification_top"),
            color_profile=_color_profile("classification_top"),
        )
    
    irl_config.carousel_stepper = mkStepperConfig(default_steps_per_second=1000, microsteps=16)
    irl_config.chute_stepper = mkStepperConfig(default_steps_per_second=3000, microsteps=8)
    irl_config.c_channel_1_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.c_channel_2_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.c_channel_3_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)

    irl_config.aruco_tags = mkArucoTagConfig()
    irl_config.bin_layout_config = getBinLayout()
    return irl_config


REQUIRED_STEPPER_NAMES = [
    "carousel",
    "c_channel_3_rotor",
    "c_channel_2_rotor",
    "c_channel_1_rotor",
    "chute_stepper",
]
HARDWARE_DISCOVERY_ATTEMPTS = 8
HARDWARE_DISCOVERY_RETRY_DELAY_S = 0.75


def mkIRLInterface(config: IRLConfig, gc: GlobalConfig) -> IRLInterface:
    """
    Initialize the hardware interface using SorterInterface directly.

    Uses SorterInterface firmware and dynamic stepper name discovery.
    The firmware reports which steppers are available via stepper_names.
    """
    irl_interface = IRLInterface()
    machine_specific_params = loadMachineSpecificParams(gc)
    machine_config = loadMachineConfig(gc, machine_specific_params)
    stepper_binding_overrides = loadStepperBindingOverrides(gc, machine_specific_params)
    stepper_current_overrides = machine_config.stepper_current_overrides
    stepper_direction_inverts = loadStepperDirectionInverts(gc, machine_specific_params)
    servo_open_angle = machine_config.servo_open_angle
    servo_closed_angle = machine_config.servo_closed_angle
    servo_channel_config = loadServoChannelConfig(gc, machine_specific_params)
    mcu_ports = MCUBus.enumerate_buses()
    control_boards = discover_control_boards(
        gc,
        REQUIRED_STEPPER_NAMES,
        attempts=HARDWARE_DISCOVERY_ATTEMPTS,
        retry_delay_s=HARDWARE_DISCOVERY_RETRY_DELAY_S,
    )
    irl_interface.interfaces = {
        board.interface.name: board.interface for board in control_boards
    }
    irl_interface.control_boards = {
        board.board_key: board for board in control_boards
    }

    stepper_entries: list[tuple[str, str, "StepperMotor", "ControlBoard"]] = []
    feeder_board: "ControlBoard | None" = None
    distribution_board: "ControlBoard | None" = None

    for board in control_boards:
        identity = board.identity
        gc.logger.info(
            f"Detected actuators on {identity.device_name} ({identity.port}:{identity.address}): "
            f"family={identity.family}, role={identity.role}, "
            f"steppers={list(board.logical_stepper_names)}, servos={len(board.servos)}"
        )
        for discovered_stepper in board.iter_steppers():
            stepper_entries.append(
                (
                    discovered_stepper.canonical_name,
                    discovered_stepper.physical_name,
                    discovered_stepper.stepper,
                    board,
                )
            )
        if board.identity.role == "feeder":
            feeder_board = board
        if board.identity.role == "distribution":
            distribution_board = board

    gc.logger.info(
        f"Global actuator inventory: steppers={[name for name, _, _, _ in stepper_entries]}"
    )

    available_stepper_names = {name for name, _, _, _ in stepper_entries}
    for stepper_name in REQUIRED_STEPPER_NAMES:
        if stepper_name not in available_stepper_names:
            gc.logger.warning(
                f"Required stepper interface '{stepper_name}' not found in detected firmware actuators"
            )

    logical_attr_base_for_physical: dict[str, str] = {
        physical_name: physical_name
        for physical_name in LOGICAL_STEPPER_BINDING_BASES.values()
    }
    for logical_name, physical_name in stepper_binding_overrides.items():
        logical_attr_base_for_physical[physical_name] = LOGICAL_STEPPER_BINDING_BASES[
            logical_name
        ]

    logical_name_for_attr_base: dict[str, str] = {
        attr_base: logical_name
        for logical_name, attr_base in LOGICAL_STEPPER_BINDING_BASES.items()
    }

    bound_attrs: dict[str, str] = {}

    # Bind steppers by canonical physical name, then remap to logical attrs if configured.
    for canonical_name, physical_name, stepper, board in stepper_entries:
        identity = board.identity
        attr_base = logical_attr_base_for_physical.get(canonical_name, canonical_name)
        attr = attr_base if attr_base.endswith("_stepper") else f"{attr_base}_stepper"
        if attr in bound_attrs:
            gc.logger.warning(
                f"Stepper '{physical_name}' at {identity.device_name} ({identity.port}:{identity.address}) maps to logical attr "
                f"'{attr}', which is already bound to physical stepper '{bound_attrs[attr]}'. Keeping first binding."
            )
            continue

        stepper_config: StepperConfig | None = getattr(config, attr, None)
        stepper.set_hardware_name(physical_name)
        stepper.set_name(attr_base)
        if stepper_config is not None:
            microsteps = stepper_config.microsteps
            default_steps_per_second = stepper_config.default_steps_per_second
            _run_stepper_init_command_with_retry(
                gc,
                attr_base,
                f"microsteps={microsteps}",
                lambda: stepper.set_microsteps(microsteps),
            )
            _run_stepper_init_command_with_retry(
                gc,
                attr_base,
                f"speed limits min=16 max={default_steps_per_second}",
                lambda: stepper.set_speed_limits(16, default_steps_per_second),
            )
            gc.logger.info(
                f"Stepper '{attr_base}' (physical '{physical_name}') config: microsteps={microsteps}, speed={default_steps_per_second}"
            )
        else:
            gc.logger.warn(
                f"Stepper '{attr_base}' (physical '{physical_name}') has no StepperConfig (attr='{attr}'), using defaults"
            )

        applyStepperCurrentOverride(stepper, canonical_name, stepper_current_overrides, gc)
        logical_name = logical_name_for_attr_base.get(attr_base)
        stepper.set_direction_inverted(
            stepper_direction_inverts.get(logical_name, False) if logical_name is not None else False
        )

        setattr(irl_interface, attr, stepper)
        bound_attrs[attr] = physical_name
        gc.logger.info(
            f"Initialized Stepper logical='{attr_base}' physical='{physical_name}' from {identity.device_name} "
            f"({identity.port}:{identity.address}), channel={stepper.channel}, position={stepper.current_position_steps} steps, "
            f"direction_inverted={stepper.direction_inverted}"
        )
        time.sleep(0.1)

    for logical_name, attr_base in LOGICAL_STEPPER_BINDING_BASES.items():
        attr = attr_base if attr_base.endswith("_stepper") else f"{attr_base}_stepper"
        if not hasattr(irl_interface, attr):
            gc.logger.warning(
                f"Logical stepper '{logical_name}' (attr '{attr}') is unbound after applying stepper_bindings."
            )

    bin_layout = config.bin_layout_config
    irl_interface.distribution_layout = mkLayoutFromConfig(bin_layout)

    # Initialize servos — either Waveshare SC bus or PCA9685 (default)
    if gc.disable_servos:
        gc.logger.info("Servo init skipped (--disable servos)")
        irl_interface.servo_controller = None
        irl_interface.servos = []
    else:
        waveshare_config = loadWaveshareServoConfig(gc, machine_specific_params)
        irl_interface.servo_controller = build_servo_controller(
            gc,
            control_boards=control_boards,
            open_angle=servo_open_angle,
            closed_angle=servo_closed_angle,
            servo_channel_config=servo_channel_config,
            waveshare_config=waveshare_config,
            mcu_ports=mcu_ports,
        )
        irl_interface.servos = irl_interface.servo_controller.create_layer_servos(
            irl_interface.distribution_layout
        )
        for layer_index, servo in enumerate(irl_interface.servos):
            layer_open = bin_layout.layers[layer_index].servo_open_angle if layer_index < len(bin_layout.layers) else None
            layer_closed = bin_layout.layers[layer_index].servo_closed_angle if layer_index < len(bin_layout.layers) else None
            open_angle = layer_open if layer_open is not None else servo_open_angle
            closed_angle = layer_closed if layer_closed is not None else servo_closed_angle
            if hasattr(servo, "set_preset_angles"):
                servo.set_preset_angles(open_angle, closed_angle)
        restore_servo_states(irl_interface.servos, gc)
    irl_interface.machine_profile = build_machine_profile(
        camera_layout=config.camera_layout,
        feeding_mode=config.feeding_mode,
        machine_setup=config.machine_setup.key,
        servo_backend=irl_interface.servo_controller.backend_name if irl_interface.servo_controller else "none",
        stepper_bindings=stepper_binding_overrides,
        stepper_direction_inverts=stepper_direction_inverts,
        control_boards=control_boards,
    )

    saved_categories = getBinCategories()
    if saved_categories is not None:
        if layoutMatchesCategories(irl_interface.distribution_layout, saved_categories):
            applyCategories(irl_interface.distribution_layout, saved_categories)
            gc.logger.info("Loaded bin categories from storage")
        else:
            gc.logger.warn("Saved bin categories don't match layout, ignoring")

    from subsystems.classification.carousel_hardware import CarouselHardware
    carousel_calibration = loadCarouselCalibrationConfig(gc, machine_specific_params)

    if feeder_board is None:
        raise RuntimeError("Feeder board not found — cannot initialize carousel homing")
    carousel_home_pin = feeder_board.get_input(carousel_calibration.home_pin_channel)
    if carousel_home_pin is None:
        raise RuntimeError(
            f"Feeder board carousel home input channel {carousel_calibration.home_pin_channel} is unavailable."
        )
    irl_interface.carousel_home_pin = carousel_home_pin
    irl_interface.carousel_hw = CarouselHardware(
        gc,
        irl_interface.carousel_stepper,
        carousel_home_pin,
        endstop_active_high=carousel_calibration.endstop_active_high,
    )

    from subsystems.distribution.chute import Chute
    chute_calibration = loadChuteCalibrationConfig(gc, machine_specific_params)

    if distribution_board is None:
        raise RuntimeError("Distribution board not found — cannot initialize chute homing")
    chute_home_pin = distribution_board.get_input(chute_calibration.home_pin_channel)
    if chute_home_pin is None:
        raise RuntimeError(
            f"Distribution board chute home input channel {chute_calibration.home_pin_channel} is unavailable."
        )
    irl_interface.chute = Chute(
        gc,
        irl_interface.chute_stepper,
        chute_home_pin,
        irl_interface.distribution_layout,
        first_bin_center=chute_calibration.first_bin_center,
        pillar_width_deg=chute_calibration.pillar_width_deg,
        endstop_active_high=chute_calibration.endstop_active_high,
        operating_speed_microsteps_per_second=chute_calibration.operating_speed_microsteps_per_second,
    )

    return irl_interface
