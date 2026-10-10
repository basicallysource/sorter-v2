import contextlib
import time
from dataclasses import dataclass


# The one feeder flow and the one classification-channel flow every machine
# runs, under the names Hive's control data and telemetry record them by.
FEEDER_FLOW = "pulse_perception_rev01"
CLASSIFICATION_CHANNEL_FLOW = "two_piece_state_machine_rev01"
MACHINE_SETUP = "classification_channel"

from global_config import GlobalConfig
from hardware.bus import MCUBus, MCUBusError
from hardware.cobs import DecodeError
from hardware.fault import HardwareFault
from hardware.sorter_interface import DISABLE_STALLGUARD, SorterInterface
from machine_platform import (
    build_servo_controller,
    discover_control_boards,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from machine_platform.control_board import ControlBoard
    from machine_platform.servo_controller import ServoController
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
    DEFAULT_STEPPER_CURRENTS,
    DEFAULT_STEPPER_IHOLD,
    DEFAULT_STEPPER_IHOLD_DELAY,
    DEFAULT_STEPPER_IRUN,
    LOGICAL_STEPPER_BINDING_BASES,
    loadMachineConfig,
    loadMachineSpecificParams,
    loadStepperBindingOverrides,
    loadStepperDirectionInverts,
    loadServoChannelConfig,
    loadWaveshareServoConfig,
    loadChuteCalibrationConfig,
)
from .leds import LedController, discoverLedOutputs
from bin_layout_store import get_bin_categories, get_not_in_inventory_bins
from local_state import get_led_state, get_servo_states

HARDWARE_INIT_COMMAND_ATTEMPTS = 4
HARDWARE_INIT_RETRY_DELAY_S = 0.2
# TMC2209 registers. Driver writes are one-way (the board acknowledges them
# without hearing from the driver), so init reads IFCNT, the driver's count of
# writes it accepted, before and after to prove they all landed.
_TMC_REG_GCONF = 0x00
_TMC_REG_IFCNT = 0x02
_TMC_REG_TCOOLTHRS = 0x14
_TMC_REG_SGTHRS = 0x40
_TMC_GCONF_UART_INIT = 0x1C0  # PD_DISABLE | MSTEP_REG_SELECT | MULTISTEP_FILT
_STEPPER_LABELS = {
    "c_channel_1_rotor": "C-Channel 1",
    "c_channel_2_rotor": "C-Channel 2",
    "c_channel_3_rotor": "C-Channel 3",
    "carousel": "carousel",
    "chute_stepper": "chute",
}
_CHECK_POWER = (
    "Check that the motor power supply is on and the control board is connected, "
    "then home again."
)


def _initCommand(gc: GlobalConfig, label: str, action: str, command):
    """One init command, retried on bus errors. When the last attempt fails the
    stepper would run on whatever settings it has, so init stops with the reason."""
    for attempt in range(1, HARDWARE_INIT_COMMAND_ATTEMPTS + 1):
        try:
            return command()
        except (MCUBusError, OSError, DecodeError) as exc:
            if attempt == HARDWARE_INIT_COMMAND_ATTEMPTS:
                raise HardwareFault(
                    "Stepper setup failed",
                    f"The control board could not {action} for the {label} stepper "
                    f"({HARDWARE_INIT_COMMAND_ATTEMPTS} tries: {exc}). {_CHECK_POWER}",
                ) from exc
            gc.logger.warning(
                f"Could not {action} for the {label} stepper on attempt "
                f"{attempt}/{HARDWARE_INIT_COMMAND_ATTEMPTS}: {exc}. "
                f"Retrying in {HARDWARE_INIT_RETRY_DELAY_S:.2f}s..."
            )
            time.sleep(HARDWARE_INIT_RETRY_DELAY_S)


def _configureStepper(
    gc: GlobalConfig,
    stepper: "StepperMotor",
    canonical_name: str,
    label: str,
    stepper_config: "StepperConfig | None",
    machine_config,
) -> None:
    """Put the stepper's TMC2209 in UART mode and write its microsteps, speed,
    acceleration, current and StallGuard settings. Raises HardwareFault when a
    command fails or the driver did not take every write: a driver left on its
    power-on settings runs at the wrong current and microstepping, or not at all.

    Without motor power (NO_POWER_DEVELOPMENT_MODE) the drivers cannot answer,
    so the writes go out unchecked."""
    verify = not gc.no_power_development_mode

    def run(action: str, command):
        return _initCommand(gc, label, action, command)

    def interfaceCount() -> int:
        return run("read its driver", lambda: stepper.read_driver_register(_TMC_REG_IFCNT)) & 0xFF

    before = interfaceCount() if verify else 0
    # GCONF puts the TMC2209 in UART-controlled mode. The chip may have powered
    # on (or reset) after the firmware's own initialize() ran, leaving it at its
    # reset defaults, so init writes it whatever the power sequencing was.
    run("set GCONF", lambda: stepper.write_driver_register(_TMC_REG_GCONF, _TMC_GCONF_UART_INIT))
    writes = 1
    if stepper_config is not None:
        microsteps = stepper_config.microsteps
        speed = stepper_config.default_steps_per_second
        acceleration = stepper_config.acceleration_microsteps_per_second_sq
        run(f"set microsteps={microsteps}", lambda: stepper.set_microsteps(microsteps))
        writes += 1
        run(f"set speed limits 16..{speed}", lambda: stepper.set_speed_limits(16, speed))
        # Every move re-asserts the default acceleration; this sets it before the
        # first move (homing).
        stepper.set_default_acceleration(acceleration)
        run(f"set acceleration={acceleration}", lambda: stepper.set_acceleration(acceleration))

    irun, ihold, ihold_delay = machine_config.stepper_current_overrides.get(
        canonical_name
    ) or DEFAULT_STEPPER_CURRENTS.get(
        canonical_name,
        (DEFAULT_STEPPER_IRUN, DEFAULT_STEPPER_IHOLD, DEFAULT_STEPPER_IHOLD_DELAY),
    )
    run(
        f"set current IRUN={irun} IHOLD={ihold}",
        lambda: stepper.set_current(irun, ihold, ihold_delay),
    )
    writes += 1

    # [stepper_stallguard.*]: detection is switched on here, once, and stays on;
    # the stall monitor reads the stamped values. Homing does not false-trip: it
    # runs below the TCOOLTHRS velocity floor, where DIAG is inactive.
    stallguard = machine_config.stepper_stallguard.get(canonical_name)
    if stallguard is not None and not DISABLE_STALLGUARD:
        sgthrs, tcoolthrs, enabled = stallguard
        stepper.stallguard_sgthrs = sgthrs
        stepper.stallguard_tcoolthrs = tcoolthrs
        stepper.stallguard_enabled = enabled
        if enabled:
            run("set the StallGuard threshold", lambda: stepper.write_driver_register(_TMC_REG_SGTHRS, sgthrs))
            run("set the StallGuard speed floor", lambda: stepper.write_driver_register(_TMC_REG_TCOOLTHRS, tcoolthrs))
            writes += 2
            try:
                run("clear its stall latch", stepper.clear_stall)
                run("arm stall detection", lambda: stepper.enable_stall_detection(True))
            except Exception as exc:
                # Boards that wire no DIAG pin for a channel (e.g. SKR Pico:
                # STEPPER_DIAG_PINS = {-1, -1, -1, -1}) can never arm StallGuard;
                # the firmware rejects the command with b'No DIAG pin for channel
                # N'. Run that stepper without stall detection instead of failing
                # the whole init.
                if "No DIAG pin" not in str(exc):
                    raise
                stepper.stallguard_enabled = False
                gc.logger.warning(
                    f"StallGuard skipped for the {label} stepper: the board reports no DIAG pin for this channel."
                )

    if verify:
        took = (interfaceCount() - before) % 256
        if took < writes:
            raise HardwareFault(
                "Stepper settings not applied",
                f"The {label} stepper's driver took {took} of the {writes} settings it "
                f"was sent, so it would run at the wrong current or microstepping. "
                f"Check the driver's connection. {_CHECK_POWER}",
            )
    gc.logger.info(
        f"Stepper '{label}' configured: IRUN={irun} IHOLD={ihold} IHOLD_DELAY={ihold_delay}, "
        f"StallGuard {'on' if stepper.stallguard_enabled else 'off'}"
        + (f", driver took {writes} writes" if verify else ", unchecked (no motor power)")
    )


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
        if not getattr(servo, "is_calibrated", True):
            # Uncalibrated PWM servos must not move on boot.
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
    fourcc: str
    # True when machine.toml names this camera's capture mode. Otherwise the
    # camera service gives a USB camera its own default (see vision/camera_modes.py).
    capture_mode_saved: bool
    picture_settings: "CameraPictureSettings"
    device_settings: dict[str, int | float | bool]

    def __init__(self):
        self.url = None
        self.fourcc = "MJPG"
        self.capture_mode_saved = False


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


# Matches the firmware's Stepper constructor default (`_accel(10000)` in
# Stepper.cpp). The firmware keeps acceleration as mutable per-motor state that
# is not reliably at this value at runtime, so the backend is authoritative: it
# stores a per-stepper default here and re-applies it before every move (see
# StepperMotor.move_*; jitter is the only exception, it manages its own).
# Change this one value to retune the acceleration of every stepper at once.
FIRMWARE_DEFAULT_ACCELERATION_MICROSTEPS_PER_SECOND_SQ = 10000


class StepperConfig:
    default_steps_per_second: int
    microsteps: int
    acceleration_microsteps_per_second_sq: int

    def __init__(
        self,
        default_steps_per_second: int = 2000,
        microsteps: int = 8,
        acceleration_microsteps_per_second_sq: int = FIRMWARE_DEFAULT_ACCELERATION_MICROSTEPS_PER_SECOND_SQ,
    ):
        self.default_steps_per_second = default_steps_per_second
        self.microsteps = microsteps
        self.acceleration_microsteps_per_second_sq = acceleration_microsteps_per_second_sq


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


@dataclass(frozen=True)
class ClassificationChannelExitReleaseStage:
    name: str
    amplitude_output_deg: float
    cycles: int
    microsteps_per_second: int
    acceleration_microsteps_per_second_sq: int
    settle_ms: int


class ClassificationChannelConfig:
    max_zones: int
    intake_angle_deg: float
    intake_body_half_width_deg: float
    intake_guard_deg: float
    intake_registration_window_deg: float
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
    exit_release_shimmy_stepper_per_output_deg: float
    exit_release_shimmy_stages: tuple[ClassificationChannelExitReleaseStage, ...]
    exit_release_review_pause_enabled: bool
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
        # Keep C4 pipelined instead of serialised: target one piece in the
        # intake/drop zone and three more spread across the platter on the way
        # to the exit. Zone hard-guards still prevent same-sector loading.
        self.max_zones = 4
        self.intake_angle_deg = 305.0
        self.intake_body_half_width_deg = 10.0
        # Admission is governed by the actual intake/dropzone being clear, not
        # by an extra angular safety moat. Existing piece hard-zones still
        # protect the landing zone; this guard stays at zero for C4 dynamic
        # intake so C3 can refill as soon as the last piece has left intake.
        self.intake_guard_deg = 0.0
        # A newly dropped piece may appear a bit downstream before the tracker
        # has enough hits to register it. Keep that registration search wider
        # than the admission-clearance window.
        self.intake_registration_window_deg = 46.0
        # Live calibration on the dedicated classification channel shows the
        # real guide / point-of-no-return on the lower-right quadrant, not on
        # the legacy left-side position from the old chamber model.
        self.drop_angle_deg = 30.0
        self.drop_tolerance_deg = 14.0
        self.point_of_no_return_deg = 18.0
        self.recognition_window_deg = 170.0
        self.positioning_window_deg = 48.0
        self.exit_release_overlap_ratio = 0.5
        # Stuck wheel release uses the old gated C4 release probe pattern:
        # per attempt, rock +A / -2A / +A so the net position returns to
        # zero, with slow speeds and settle pauses. Repeated release attempts
        # on the same piece walk this ladder from calm to firmer motion.
        # Amplitudes are output/platter degrees and are converted to stepper
        # degrees at runtime via the measured C4 gear ratio.
        self.exit_release_shimmy_amplitude_deg = 3.0
        self.exit_release_shimmy_cycles = 3
        self.exit_release_shimmy_microsteps_per_second = 4200
        self.exit_release_shimmy_acceleration_microsteps_per_second_sq = 9000
        self.exit_release_shimmy_stepper_per_output_deg = 130.0 / 12.0
        self.exit_release_shimmy_stages = (
            ClassificationChannelExitReleaseStage(
                "contact-break-micro",
                amplitude_output_deg=0.25,
                cycles=2,
                microsteps_per_second=700,
                acceleration_microsteps_per_second_sq=1800,
                settle_ms=300,
            ),
            ClassificationChannelExitReleaseStage(
                "low-rock",
                amplitude_output_deg=0.50,
                cycles=2,
                microsteps_per_second=950,
                acceleration_microsteps_per_second_sq=2600,
                settle_ms=300,
            ),
            ClassificationChannelExitReleaseStage(
                "medium-rock",
                amplitude_output_deg=0.85,
                cycles=3,
                microsteps_per_second=1250,
                acceleration_microsteps_per_second_sq=3600,
                settle_ms=350,
            ),
            ClassificationChannelExitReleaseStage(
                "firm-rock",
                amplitude_output_deg=1.25,
                cycles=3,
                microsteps_per_second=1600,
                acceleration_microsteps_per_second_sq=4800,
                settle_ms=400,
            ),
            ClassificationChannelExitReleaseStage(
                "last-resort-small-kick",
                amplitude_output_deg=1.75,
                cycles=2,
                microsteps_per_second=1900,
                acceleration_microsteps_per_second_sq=6000,
                settle_ms=450,
            ),
        )
        self.exit_release_review_pause_enabled = True
        self.stale_zone_timeout_s = 3.0
        # Dropped to 0 in T4: with the pipeline running at ~11 pieces/min
        # (post-supervisor-restart, no backpressure deadlock) individual
        # pieces transit C4 fast enough that the 300 ms hood dwell timer
        # never clears before point_of_no_return — every step() returns
        # early at _shouldHoldForHoodDwell and _fireRecognition is never
        # reached, even for the non-hood piece. With min_carousel_crops=5
        # + the free-fall burst + the retro low-conf scan already enforcing
        # quality, the hood-dwell timer is redundant defence. Old comment
        # about "poor crops" no longer applies because the new gates filter
        # quality differently.
        self.hood_dwell_ms = 0
        # Minimum number of carousel-source crops required before the
        # recognizer may fire for a piece. Prevents recognition from
        # committing using only c_channel_2/c_channel_3 history (which, if
        # misbound, can belong to a different piece still upstream).
        # Reverted to 5 in T11: T8 / T10 with min_crops=3 catastrophically
        # increased ghost fires (a static platter feature at angle ~44°
        # gets re-detected each frame and trivially clears 3 crops within
        # the 1.2 s free-fall burst window where every sector_snapshot is
        # captured). Net result: 5-6 fires/min of which 80 % returned
        # bk_empty. Sticking with 5 keeps T7 throughput (median 3.54).
        self.min_carousel_crops_for_recognize = 5
        # Minimum elapsed time since the piece's first carousel-source
        # observation before recognition may fire. Guards against a
        # freshly-spawned carousel track that briefly stacks 2+ crops in
        # quick succession but hasn't yet stabilized on the physical C4 tray.
        # Dropped to 0 in T3: the T2 family established that
        # min_carousel_crops_for_recognize=5 + carousel-only filter +
        # free-fall burst already guarantees the piece is post-landing
        # before recognition fires. The dwell gate is now redundant
        # defence and was costing us retry windows.
        self.min_carousel_dwell_ms = 0
        # Minimum angular traversal on the carousel (degrees) since the
        # piece was first observed there before recognition may fire.
        # Time-based gates don't guarantee viewing-angle diversity when the
        # carousel rotates fast; this ensures the piece has physically
        # rotated enough to present multiple sides to the C4 camera, so the
        # accumulated crops cover meaningfully different viewpoints.
        # Reverted to 0.0 after T14 (8° killed all fires) and T15 (4°
        # killed all fires). Real pieces apparently don't accumulate
        # enough angular displacement BEFORE recognition needs to fire,
        # at least not measured at zone.center_deg granularity. The
        # ghost-fire-blocking benefit doesn't materialize; T7's 0°
        # setting still produces the best median (3.54).
        self.min_carousel_traversal_deg = 0.0
        self.size_downgrade_confirmations = 3
        # Leader-wins drop policy: when the drop candidate has an interferer
        # inside the clearance window, only flip the *leader* to
        # ``multi_drop_fail`` if the interferer is strictly trailing (hasn't
        # reached drop yet). Spares the trailer so it can take its own drop
        # cycle next rotation instead of being discarded with the leader.
        self.leader_wins_policy = False
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
        # C3→C4 speed ratio: C4 ~40-50% faster than C3 so pieces don't
        # accumulate on the carousel. Both kept slow overall — fast C4
        # confused the upstream coupling (C2 backspin observed at 5000+).
        # C3=2500, C4=3600 → C4 is ~44% faster than C3.
        self.third_rotor_normal = RotorPulseConfig(
            steps=1000,
            microsteps_per_second=2500,
            delay_between_ms=250,
        )
        self.third_rotor_precision = RotorPulseConfig(
            steps=300,
            microsteps_per_second=1600,
            delay_between_ms=1000,
        )
        self.classification_channel_eject = RotorPulseConfig(
            steps=1000,
            microsteps_per_second=3600,
            # 400 ms inter-pulse is the keeper. T2d tested 800 ms and
            # cls/min DROPPED to ~1 instead of rising — upstream blocking
            # (``classification_channel_occupied`` reasons exploded) dragged
            # supply faster than the extra C4 dwell improved conversion.
            # The real lever for 8 cls/min is not slowing the platter; it
            # is widening the recognition window through earlier captures
            # and fewer gate skips, not more dwell-per-piece on C4.
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
    c_channel_2_camera: CameraConfig | None
    c_channel_3_camera: CameraConfig | None
    carousel_camera: CameraConfig | None
    carousel_stepper: StepperConfig
    c_channel_4_rotor_stepper: StepperConfig
    chute_stepper: StepperConfig
    c_channel_1_rotor_stepper: StepperConfig
    c_channel_2_rotor_stepper: StepperConfig
    c_channel_3_rotor_stepper: StepperConfig
    bin_layout_config: BinLayoutConfig
    feeder_config: FeederConfig
    classification_channel_config: ClassificationChannelConfig

    def __init__(self):
        self.c_channel_2_camera = None
        self.c_channel_3_camera = None
        self.carousel_camera = None
        self.feeder_config = FeederConfig()
        self.classification_channel_config = ClassificationChannelConfig()


class IRLInterface:
    carousel_stepper: "StepperMotor"
    c_channel_4_rotor_stepper: "StepperMotor"
    classification_channel_rotor_stepper: "StepperMotor"
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
    led_controller: "LedController | None"

    def __init__(self):
        self.interfaces: dict[str, SorterInterface] = {}
        self.control_boards = {}
        self.servo_controller = None
        self.led_controller = None

    def enableSteppers(self) -> None:
        for stepper_name in [
            "c_channel_1_rotor",
            "c_channel_2_rotor",
            "c_channel_3_rotor",
            "c_channel_4_rotor",
            "carousel",
            "chute",
        ]:
            attr = f"{stepper_name}_stepper"
            if hasattr(self, attr):
                getattr(self, attr).enabled = True

    def disableSteppers(self) -> None:
        seen: set[int] = set()
        for stepper_name in [
            "c_channel_1_rotor",
            "c_channel_2_rotor",
            "c_channel_3_rotor",
            "c_channel_4_rotor",
            "carousel",
            "chute",
        ]:
            attr = f"{stepper_name}_stepper"
            if hasattr(self, attr):
                stepper = getattr(self, attr)
                identity = id(stepper)
                if identity in seen:
                    continue
                seen.add(identity)
                stepper.enabled = False

    def shutdown(self) -> None:
        try:
            if self.led_controller is not None:
                self.led_controller.allOff()
            if self.servo_controller is not None and hasattr(self.servo_controller, "shutdown"):
                try:
                    self.servo_controller.shutdown()
                except Exception:
                    pass
            for iface in self.interfaces.values():
                iface.shutdown()
        finally:
            # Close the underlying serial buses, even when a board no longer
            # answers, so standby genuinely releases the ttys: otherwise the fds
            # linger until GC and the firmware flasher (or the next discovery
            # pass) races a stale open on the same port. Interfaces can share a
            # bus (multi-address), so dedupe before closing.
            seen_buses: set[int] = set()
            for iface in self.interfaces.values():
                bus = getattr(iface, "_bus", None)
                if bus is None or id(bus) in seen_buses:
                    continue
                seen_buses.add(id(bus))
                try:
                    bus.close()
                except Exception:
                    pass


def mkCameraConfig(
    device_index: int = -1, width: int = 1920, height: int = 1080, fps: int = 30,
    url: str | None = None,
    fourcc: str | None = None,
    picture_settings: CameraPictureSettings | None = None,
    device_settings: dict[str, int | float | bool] | None = None,
) -> CameraConfig:
    camera_config = CameraConfig()
    camera_config.device_index = device_index
    camera_config.url = url
    camera_config.width = width
    camera_config.height = height
    camera_config.fps = fps
    camera_config.fourcc = fourcc.strip() if (isinstance(fourcc, str) and fourcc.strip()) else "MJPG"
    camera_config.picture_settings = picture_settings or mkCameraPictureSettings()
    camera_config.device_settings = parseCameraDeviceSettings(device_settings)
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
            # Driver sentinel: cap.get() returns -1 for properties the device
            # does not actually expose. Persisting/applying these poisons the
            # camera — drop them.
            if float(value) == -1.0 and key in {"focus", "gain", "exposure", "white_balance_temperature"}:
                continue
            result[key] = float(value)

    # Drop manual settings that fight their auto-mode counterpart. A UVC camera
    # silently flips `auto_exposure` to Manual the moment a manual exposure value
    # is written, so persisting both leaves the device in a self-contradictory
    # state and the manual value always wins on reopen. Auto wins here: if the
    # user wants manual control, they explicitly turn auto off.
    if result.get("auto_exposure") is True:
        result.pop("exposure", None)
        result.pop("gain", None)
    if result.get("auto_white_balance") is True:
        result.pop("white_balance_temperature", None)
    if result.get("autofocus") is True:
        result.pop("focus", None)

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


def cameraSourceForRole(cameras: object, role: str) -> int | str | None:
    if not isinstance(cameras, dict):
        return None
    roles = ("classification_channel", "carousel") if role in {"classification_channel", "carousel"} else (role,)
    for key in roles:
        value = cameras.get(key)
        if type(value) is int and value >= 0:
            return value
        if isinstance(value, str):
            value = value.strip()
            if value and value.lower() not in {"none", "null", "-1"}:
                return value
    return None


def cameraSettingsForRole(settings: object, role: str) -> dict:
    if not isinstance(settings, dict):
        return {}
    roles = ("classification_channel", "carousel") if role in {"classification_channel", "carousel"} else (role,)
    for key in roles:
        entry = settings.get(key)
        if isinstance(entry, dict):
            return entry
    return {}


def mkIRLConfig(machine_params: dict[str, object] | None = None) -> IRLConfig:
    irl_config = IRLConfig()

    import machine_toml
    raw_toml: dict[str, object] = machine_toml.read()

    picture_settings_section = {}
    if isinstance(raw_toml, dict):
        picture_settings_section = raw_toml.get("camera_picture_settings", {})
    device_settings_section = {}
    if isinstance(raw_toml, dict):
        device_settings_section = raw_toml.get("camera_device_settings", {})
    capture_modes_section = {}
    if isinstance(raw_toml, dict):
        capture_modes_section = raw_toml.get("camera_capture_modes", {})

    def _capture_mode(role: str) -> dict[str, int | str]:
        entry = cameraSettingsForRole(capture_modes_section, role)
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
        return parseCameraPictureSettings(cameraSettingsForRole(picture_settings_section, role))

    def _device_settings(role: str) -> dict[str, int | float | bool]:
        return parseCameraDeviceSettings(cameraSettingsForRole(device_settings_section, role))


    def _mkCameraConfigForRole(role: str, **kwargs) -> CameraConfig:
        mode = _capture_mode(role)
        merged = dict(kwargs)
        for key in ("width", "height", "fps", "fourcc"):
            if key in mode and key not in merged:
                merged[key] = mode[key]
        config = mkCameraConfig(**merged)
        config.capture_mode_saved = bool(mode)
        return config

    cameras_section = raw_toml.get("cameras", {})
    c_ch2_idx = cameraSourceForRole(cameras_section, "c_channel_2")
    c_ch3_idx = cameraSourceForRole(cameras_section, "c_channel_3")
    carousel_source = cameraSourceForRole(cameras_section, "classification_channel")
    aux_camera_role = "classification_channel"

    if isinstance(c_ch2_idx, int):
        irl_config.c_channel_2_camera = _mkCameraConfigForRole(
            "c_channel_2",
            device_index=c_ch2_idx,
            picture_settings=_picture_settings("c_channel_2"),
            device_settings=_device_settings("c_channel_2"),
        )
    elif isinstance(c_ch2_idx, str):
        irl_config.c_channel_2_camera = _mkCameraConfigForRole(
            "c_channel_2",
            url=c_ch2_idx,
            picture_settings=_picture_settings("c_channel_2"),
            device_settings=_device_settings("c_channel_2"),
        )
    if isinstance(c_ch3_idx, int):
        irl_config.c_channel_3_camera = _mkCameraConfigForRole(
            "c_channel_3",
            device_index=c_ch3_idx,
            picture_settings=_picture_settings("c_channel_3"),
            device_settings=_device_settings("c_channel_3"),
        )
    elif isinstance(c_ch3_idx, str):
        irl_config.c_channel_3_camera = _mkCameraConfigForRole(
            "c_channel_3",
            url=c_ch3_idx,
            picture_settings=_picture_settings("c_channel_3"),
            device_settings=_device_settings("c_channel_3"),
        )
    if isinstance(carousel_source, str):
        irl_config.carousel_camera = _mkCameraConfigForRole(
            aux_camera_role,
            url=carousel_source,
            picture_settings=_picture_settings(aux_camera_role),
            device_settings=_device_settings(aux_camera_role),
        )
    elif isinstance(carousel_source, int):
        irl_config.carousel_camera = _mkCameraConfigForRole(
            aux_camera_role,
            device_index=carousel_source,
            picture_settings=_picture_settings(aux_camera_role),
            device_settings=_device_settings(aux_camera_role),
        )

    irl_config.carousel_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.c_channel_4_rotor_stepper = irl_config.carousel_stepper
    irl_config.chute_stepper = mkStepperConfig(default_steps_per_second=3000, microsteps=8)
    irl_config.c_channel_1_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.c_channel_2_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)
    irl_config.c_channel_3_rotor_stepper = mkStepperConfig(default_steps_per_second=4000, microsteps=8)

    irl_config.bin_layout_config = getBinLayout()
    return irl_config


HARDWARE_DISCOVERY_ATTEMPTS = 8
HARDWARE_DISCOVERY_RETRY_DELAY_S = 0.75


def _requiredCanonicalStepperNames(stepper_binding_overrides: dict[str, str]) -> list[str]:
    logical_required = ["chute", "c_channel_1", "c_channel_2", "c_channel_3", "carousel"]
    return [
        stepper_binding_overrides.get(logical, LOGICAL_STEPPER_BINDING_BASES[logical])
        for logical in logical_required
    ]


def _apply_stepper_software_disable(gc: GlobalConfig, irl: IRLInterface) -> None:
    c_channel_attrs = {
        1: "c_channel_1_rotor_stepper",
        2: "c_channel_2_rotor_stepper",
        3: "c_channel_3_rotor_stepper",
        4: "c_channel_4_rotor_stepper",
    }
    for ch, attr in c_channel_attrs.items():
        if ch in gc.disable_c_channels:
            stepper = getattr(irl, attr, None)
            if stepper is not None:
                stepper.software_disabled = True
                gc.logger.info(f"c_channel_{ch} rotor stepper software-disabled (motor suppressed)")
    if gc.disable_carousel:
        stepper = getattr(irl, "carousel_stepper", None)
        if stepper is not None:
            stepper.software_disabled = True
            gc.logger.info("Carousel stepper software-disabled (motor suppressed)")


def mkIRLInterface(config: IRLConfig, gc: GlobalConfig) -> IRLInterface:
    """
    Initialize the hardware interface using SorterInterface directly.

    Uses SorterInterface firmware and dynamic stepper name discovery.
    The firmware reports which steppers are available via stepper_names.
    """
    irl_interface = IRLInterface()
    try:
        _bindHardware(irl_interface, config, gc)
    except BaseException:
        # Release the boards discovery opened: their ports are opened
        # exclusively, so the next attempt would find them held.
        with contextlib.suppress(Exception):
            irl_interface.shutdown()
        raise
    return irl_interface


def _bindHardware(irl_interface: IRLInterface, config: IRLConfig, gc: GlobalConfig) -> None:
    machine_specific_params = loadMachineSpecificParams(gc)
    machine_config = loadMachineConfig(gc, machine_specific_params)
    stepper_binding_overrides = loadStepperBindingOverrides(gc, machine_specific_params)
    stepper_direction_inverts = loadStepperDirectionInverts(gc, machine_specific_params)
    servo_channel_config = loadServoChannelConfig(gc, machine_specific_params)
    mcu_ports = MCUBus.enumerate_buses()
    required_stepper_names = _requiredCanonicalStepperNames(stepper_binding_overrides)
    gc.logger.info(f"Required steppers: {required_stepper_names}")
    control_boards = discover_control_boards(
        gc,
        required_stepper_names,
        attempts=HARDWARE_DISCOVERY_ATTEMPTS,
        retry_delay_s=HARDWARE_DISCOVERY_RETRY_DELAY_S,
    )
    irl_interface.interfaces = {
        board.interface.name: board.interface for board in control_boards
    }
    irl_interface.control_boards = {
        board.board_key: board for board in control_boards
    }

    irl_interface.led_controller = LedController(gc, discoverLedOutputs(gc, control_boards))
    irl_interface.led_controller.apply(get_led_state())

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
    for stepper_name in required_stepper_names:
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
        attr_base = logical_attr_base_for_physical.get(canonical_name)
        if attr_base is None:
            # A channel no part of the machine drives, like the aux channels of a
            # four-channel distribution board. Its socket is often empty, so init
            # leaves it alone instead of waiting for a driver that is not there.
            gc.logger.info(
                f"Stepper '{physical_name}' at {identity.device_name} ({identity.port}:{identity.address}) "
                "is not used by this machine; leaving it unconfigured."
            )
            continue
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
        _configureStepper(
            gc,
            stepper,
            canonical_name,
            _STEPPER_LABELS.get(attr_base, attr_base),
            stepper_config,
            machine_config,
        )
        stepper.set_direction_inverted(
            stepper_direction_inverts.get(logical_name_for_attr_base[attr_base], False)
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

    if hasattr(irl_interface, "carousel_stepper"):
        irl_interface.c_channel_4_rotor_stepper = irl_interface.carousel_stepper
        irl_interface.classification_channel_rotor_stepper = irl_interface.carousel_stepper

    _apply_stepper_software_disable(gc, irl_interface)

    bin_layout = config.bin_layout_config
    irl_interface.distribution_layout = mkLayoutFromConfig(bin_layout)

    from .bin_layout import calibratedAnglesForLayer

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
            servo_channel_config=servo_channel_config,
            waveshare_config=waveshare_config,
            mcu_ports=mcu_ports,
        )
        irl_interface.servos = irl_interface.servo_controller.create_layer_servos(
            irl_interface.distribution_layout
        )
        for layer_index, servo in enumerate(irl_interface.servos):
            if not hasattr(servo, "set_preset_angles"):
                continue
            # Angles come from the per-channel calibration store (resolved via the
            # layer's servo_channel_id, with a legacy fallback to the layer's own
            # angle if the channel isn't calibrated yet).
            layer_open, layer_closed = calibratedAnglesForLayer(
                bin_layout, layer_index, servo_channel_config
            )
            if layer_open is not None and layer_closed is not None:
                servo.set_preset_angles(layer_open, layer_closed)
            if hasattr(servo, "set_motion_speeds"):
                servo.set_motion_speeds(
                    machine_config.servo_open_speed,
                    machine_config.servo_close_speed,
                    machine_config.servo_homing_speed,
                )
                # Start at the standard speed; sorting re-applies open/close
                # speed per move and homing re-applies the standard speed.
                servo.apply_homing_speed()
        restore_servo_states(irl_interface.servos, gc)


    saved_categories = get_bin_categories()
    if saved_categories is not None:
        if layoutMatchesCategories(irl_interface.distribution_layout, saved_categories):
            applyCategories(irl_interface.distribution_layout, saved_categories)
            gc.logger.info("Loaded bin categories from storage")
        else:
            gc.logger.warn("Saved bin categories don't match layout, ignoring")

    from irl.bin_layout import applyNotInInventory, notInInventoryMatchesLayout
    saved_nii = get_not_in_inventory_bins()
    if saved_nii is not None:
        if notInInventoryMatchesLayout(irl_interface.distribution_layout, saved_nii):
            applyNotInInventory(irl_interface.distribution_layout, saved_nii)
            gc.logger.info("Loaded not-in-inventory bin flags from storage")
        else:
            gc.logger.warn("Saved not-in-inventory bin flags don't match layout, ignoring")

    from subsystems.distribution.chute import Chute

    if distribution_board is None:
        raise RuntimeError("Distribution board not found — cannot initialize chute homing")
    chute_calibration = loadChuteCalibrationConfig(
        gc,
        machine_specific_params,
        dict(distribution_board.input_aliases),
        distribution_board.chute_home_active_high,
    )
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
        num_sections=chute_calibration.num_sections,
        section_width_deg=chute_calibration.section_width_deg,
        first_section_offset_deg=chute_calibration.first_section_offset_deg,
        endstop_active_high=chute_calibration.endstop_active_high,
        operating_speed_microsteps_per_second=chute_calibration.operating_speed_microsteps_per_second,
    )
