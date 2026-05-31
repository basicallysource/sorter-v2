import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from global_config import GlobalConfig
from irl.bin_layout import DistributionLayout
from irl.parse_user_toml import DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor, DigitalInputPin

GEAR_RATIO = 120 / 25  # 25T motor gear -> 25T idle gear -> 120T chute gear
CHUTE_MAX_ANGLE = 350

# Chute aiming geometry.
#
# The chute rotates within [0, 360) and hits a HARD STOP at either end — it
# can neither cross zero nor pass 360. So every reachable bin angle must stay
# inside that arc, and the home switch must sit such that the trailing margin
# of the last section still fits before 360.
#
# The geometry is described by three calibrated invariants, all of which are
# bin-count INDEPENDENT (this is what lets one calibration serve 1/2/3/5-bin
# layers alike):
#   - num_sections (N): how many bin sections tile the circle. The section
#     pitch — first-bin to first-bin across adjacent sections — is 360 / N.
#   - section_width_deg (W): the usable angular arc one section's bins occupy.
#     The physical pillar between sections is therefore (360/N - W).
#   - first_section_offset_deg (theta0): home-zero to the START edge of
#     section 0's usable arc. From home the chute turns clockwise this far to
#     reach the leading edge of the first section.
#
# Within a section of K bins, bins are equal-width slots and we aim at each
# slot's MIDPOINT:
#     bin_center = theta0 + section*(360/N) + (i + 0.5)*(W / K)
# The (i + 0.5) term is what centers a 1-bin layer and splits 2/3/5-bin
# layers evenly from the same W. See the agent-notes task
# "chute-aiming-calibration" for the full derivation and the calibration
# routine that measures theta0 and W.
DEFAULT_NUM_SECTIONS = 6
DEFAULT_SECTION_WIDTH_DEG = 51.75  # = 360/6 - 8.25 (legacy 60° pitch minus 8.25° pillar)
DEFAULT_FIRST_SECTION_OFFSET_DEG = 8.25

HOME_SPEED_MICROSTEPS_PER_SEC = -1000
HOME_TIMEOUT_MS = 15000


@dataclass
class BinAddress:
    layer_index: int
    section_index: int
    bin_index: int


class Chute:
    def __init__(
        self,
        gc: GlobalConfig,
        stepper: "StepperMotor",
        home_pin: "DigitalInputPin",
        layout: DistributionLayout,
        num_sections: int = DEFAULT_NUM_SECTIONS,
        section_width_deg: float = DEFAULT_SECTION_WIDTH_DEG,
        first_section_offset_deg: float = DEFAULT_FIRST_SECTION_OFFSET_DEG,
        endstop_active_high: bool = True,
        operating_speed_microsteps_per_second: int = DEFAULT_CHUTE_OPERATING_SPEED_MICROSTEPS_PER_SEC,
    ):
        self.gc = gc
        self.logger = gc.logger
        self.stepper = stepper
        self.home_pin = home_pin
        self.layout = layout
        self.num_sections = max(1, int(num_sections))
        self.section_width_deg = float(section_width_deg)
        self.first_section_offset_deg = float(first_section_offset_deg)
        self.endstop_active_high = endstop_active_high
        self.operating_speed_microsteps_per_second = operating_speed_microsteps_per_second
        self._homed: bool = False

    @property
    def homed(self) -> bool:
        return self._homed

    @property
    def section_pitch_deg(self) -> float:
        return 360.0 / self.num_sections

    @property
    def pillar_width_deg(self) -> float:
        # Derived for display / legacy callers: the dead arc between two
        # adjacent sections' usable regions.
        return self.section_pitch_deg - self.section_width_deg

    @property
    def usable_deg_per_section(self) -> float:
        return self.section_width_deg

    @property
    def first_bin_center(self) -> float:
        # Legacy alias (chute_stress, old settings page): the angle to the
        # center of bin 0 in section 0, using that section's real bin count.
        # Falls back to the bare section offset when the layout is empty.
        angle = self.angleForVirtualBin(
            0, 0, self._binsInFirstSection(), unclamped=True
        )
        return angle if angle is not None else self.first_section_offset_deg

    def setCalibration(
        self,
        first_bin_center: float,
        pillar_width_deg: float,
        endstop_active_high: bool | None = None,
    ) -> None:
        # Legacy entry point (old /settings/chute page). Map the old params
        # onto the canonical model at the current num_sections: pillar width
        # becomes the usable section width, and first_bin_center is treated as
        # the section-0 start offset. Prefer setAimingCalibration for the new
        # calibration flow.
        self.section_width_deg = self.section_pitch_deg - float(pillar_width_deg)
        self.first_section_offset_deg = float(first_bin_center)
        if endstop_active_high is not None:
            self.endstop_active_high = endstop_active_high

    def setAimingCalibration(
        self,
        num_sections: int,
        section_width_deg: float,
        first_section_offset_deg: float,
        endstop_active_high: bool | None = None,
    ) -> None:
        self.num_sections = max(1, int(num_sections))
        self.section_width_deg = float(section_width_deg)
        self.first_section_offset_deg = float(first_section_offset_deg)
        if endstop_active_high is not None:
            self.endstop_active_high = endstop_active_high

    def setOperatingSpeed(self, operating_speed_microsteps_per_second: int) -> None:
        self.operating_speed_microsteps_per_second = max(1, int(operating_speed_microsteps_per_second))

    @property
    def raw_endstop_active(self) -> bool:
        return bool(self.home_pin.value)

    @property
    def endstop_triggered(self) -> bool:
        raw_value = self.raw_endstop_active
        return raw_value if self.endstop_active_high else not raw_value

    @property
    def current_angle(self) -> float:
        stepper_angle = self.stepper.position_degrees
        return stepper_angle / GEAR_RATIO

    def _binsInSection(self, layer_index: int, section_index: int) -> int:
        try:
            return max(1, len(self.layout.layers[layer_index].sections[section_index].bins))
        except (IndexError, AttributeError):
            return 1

    def _binsInFirstSection(self) -> int:
        for layer in self.layout.layers:
            if layer.sections:
                return max(1, len(layer.sections[0].bins))
        return 1

    def angleForVirtualBin(
        self,
        section_index: int,
        bin_index: int,
        bins_in_section: int,
        num_sections: int | None = None,
        unclamped: bool = False,
    ) -> float | None:
        # Canonical aiming formula. Used both by getAngleForBin (real layout)
        # and by the calibration UI (arbitrary, customizable layouts) so there
        # is a single source of truth for where the chute points.
        n = max(1, int(num_sections)) if num_sections else self.num_sections
        k = max(1, int(bins_in_section))
        slot = self.section_width_deg / k
        angle = (
            self.first_section_offset_deg
            + section_index * (360.0 / n)
            + (bin_index + 0.5) * slot
        )
        if unclamped:
            return angle
        if angle < 0 or angle > CHUTE_MAX_ANGLE:
            return None
        return angle

    def getAngleForBin(self, address: BinAddress) -> float | None:
        num_bins = self._binsInSection(address.layer_index, address.section_index)
        return self.angleForVirtualBin(
            address.section_index, address.bin_index, num_bins
        )

    def moveToAngle(self, target: float) -> int:
        target = max(0.0, min(360.0, target))
        current = self.current_angle
        target_stepper_angle = target * GEAR_RATIO
        current_stepper_angle = current * GEAR_RATIO
        delta_stepper_angle = target_stepper_angle - current_stepper_angle
        estimated_ms = self.stepper.estimateMoveDegreesMs(
            delta_stepper_angle,
            max_speed=self.operating_speed_microsteps_per_second,
        )

        if self.gc.disable_chute:
            self.logger.info(
                f"Chute: [DISABLED] would move from {current:.1f}° to {target:.1f}° (delta_stepper_deg={delta_stepper_angle:.2f}, est_ms={estimated_ms})"
            )
            return estimated_ms

        self.logger.info(
            f"Chute: moving from {current:.1f}° to {target:.1f}° (delta_stepper_deg={delta_stepper_angle:.2f}, est_ms={estimated_ms})"
        )
        self.stepper.move_degrees(delta_stepper_angle)
        return estimated_ms

    def isBinReachable(self, address: BinAddress) -> bool:
        return self.getAngleForBin(address) is not None

    def moveToBin(self, address: BinAddress) -> int:
        target = self.getAngleForBin(address)
        if target is None:
            self.logger.error(f"Chute: bin {address} is unreachable")
            return 0
        self.logger.info(
            f"Chute: moveToBin layer={address.layer_index} section={address.section_index} bin={address.bin_index} -> {target:.2f}°"
        )
        return self.moveToAngle(target)

    def moveToAngleBlocking(self, target: float, timeout_buffer_ms: int = 0) -> int:
        target = max(0.0, min(360.0, target))
        current = self.current_angle
        target_stepper_angle = target * GEAR_RATIO
        current_stepper_angle = current * GEAR_RATIO
        delta_stepper_angle = target_stepper_angle - current_stepper_angle
        estimated_ms = self.stepper.estimateMoveDegreesMs(
            delta_stepper_angle,
            max_speed=self.operating_speed_microsteps_per_second,
        )
        timeout_ms = max(1, estimated_ms + timeout_buffer_ms)

        if self.gc.disable_chute:
            self.logger.info(
                f"Chute: [DISABLED] would move from {current:.1f}° to {target:.1f}° (delta_stepper_deg={delta_stepper_angle:.2f}, est_ms={estimated_ms}, timeout_ms={timeout_ms})"
            )
            return estimated_ms

        self.logger.info(
            f"Chute: moving(blocking) from {current:.1f}° to {target:.1f}° (delta_stepper_deg={delta_stepper_angle:.2f}, est_ms={estimated_ms}, timeout_ms={timeout_ms})"
        )
        self.stepper.move_degrees_blocking(delta_stepper_angle, timeout_ms=timeout_ms)
        return estimated_ms

    def moveToBinBlocking(self, address: BinAddress, timeout_buffer_ms: int = 0) -> int:
        target = self.getAngleForBin(address)
        if target is None:
            self.logger.error(f"Chute: bin {address} is unreachable")
            return 0
        return self.moveToAngleBlocking(target, timeout_buffer_ms=timeout_buffer_ms)

    def _backoffToFirstBin(self) -> bool:
        backoff_angle = self.angleForVirtualBin(
            0, 0, self._binsInFirstSection(), unclamped=True
        )
        if backoff_angle is None or backoff_angle <= 0.0:
            return True
        try:
            self.moveToAngleBlocking(backoff_angle, timeout_buffer_ms=1500)
            self.logger.info(f"Chute: backed off to bin 1 ({backoff_angle:.2f}°)")
            return True
        except Exception as exc:
            self.logger.error(f"Chute: backoff to bin 1 failed: {exc}")
            return False

    def home(self) -> bool:
        self.logger.info("Chute: homing via sensor")
        self.stepper.home(
            HOME_SPEED_MICROSTEPS_PER_SEC,
            self.home_pin,
            home_pin_active_high=self.endstop_active_high,
        )
        start = time.monotonic()
        while not self.stepper.stopped:
            if (time.monotonic() - start) * 1000 > HOME_TIMEOUT_MS:
                self.logger.error("Chute: homing timed out")
                return False
            time.sleep(0.01)
        if not self.endstop_triggered:
            self.logger.warning("Chute: homing stopped before the endstop triggered")
            return False
        if not self._backoffToFirstBin():
            return False
        self.logger.info("Chute: homed successfully")
        self._homed = True
        return True
