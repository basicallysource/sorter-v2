from dataclasses import dataclass
from typing import TYPE_CHECKING
from global_config import GlobalConfig
from hardware_settings.chute import (
    DEFAULT_FIRST_SECTION_OFFSET_DEG,
    DEFAULT_NUM_SECTIONS,
    DEFAULT_OPERATING_SPEED_MICROSTEPS_PER_SEC,
    DEFAULT_POSITION_CHECK,
    DEFAULT_POSITION_CHECK_EVERY,
    DEFAULT_SECTION_WIDTH_DEG,
)
from irl.bin_layout import DistributionLayout

from .chute_homing import homeOnMagnet, homeOnSwitch
from .chute_variants import DEFAULT_VARIANT, HOME_ON_MAGNET, ChuteVariant

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor, DigitalInputPin
    from .position_check import PositionCheck

# Chute aiming geometry.
#
# Angles are measured from home, in the direction the chute turns away from it.
# A chute with a travel limit (chute_variants.py) turns within [0, travel] and
# can neither cross zero nor pass its far stop, so every reachable bin angle
# must stay inside that arc. A chute that turns without limit reaches every
# angle and takes the short way round.
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
# routine that measures theta0 and W. The defaults are in hardware_settings/chute.py.

# The chute's moves start and end at this speed; they cruise at the operating speed.
MIN_SPEED_MICROSTEPS_PER_SEC = 16


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
        operating_speed_microsteps_per_second: int = DEFAULT_OPERATING_SPEED_MICROSTEPS_PER_SEC,
        position_check: bool = DEFAULT_POSITION_CHECK,
        position_check_every: int = DEFAULT_POSITION_CHECK_EVERY,
        variant: ChuteVariant = DEFAULT_VARIANT,
        gear_ratio: float | None = None,
        discard_bin: tuple[int, int, int] | None = None,
    ):
        self.gc = gc
        self.logger = gc.logger
        self.stepper = stepper
        self.home_pin = home_pin
        self.layout = layout
        self.variant = variant
        # Motor turns for one turn of the chute: this machine's own measured
        # ratio when it has one, else the ratio its kind of chute is built with.
        self.gear_ratio = float(gear_ratio) if gear_ratio else variant.gear_ratio
        self.discard_bin: BinAddress | None = None
        self.setDiscardBin(discard_bin)
        self.num_sections = max(1, int(num_sections))
        self.section_width_deg = float(section_width_deg)
        self.first_section_offset_deg = float(first_section_offset_deg)
        self.endstop_active_high = endstop_active_high
        self.operating_speed_microsteps_per_second = operating_speed_microsteps_per_second
        self._homed: bool = False
        # The position check (position_check.py): whether it runs, every how
        # many pieces, how many have gone since, and whether one is running.
        self.position_check = position_check
        self.position_check_every = max(1, int(position_check_every))
        self.pieces_since_check = 0
        self.checking = False

    @property
    def homed(self) -> bool:
        return self._homed

    def markUnhomed(self, reason: str = "") -> None:
        """Drop the home reference. A stall means lost steps -> the recorded position
        is no longer trustworthy, so force a re-home before the next precise move."""
        if self._homed:
            self.logger.warning(
                f"Chute: home reference invalidated{f' ({reason})' if reason else ''}; re-home required."
            )
        self._homed = False

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

    def setPositionCheck(self, enabled: bool, every: int) -> None:
        self.position_check = bool(enabled)
        self.position_check_every = max(1, int(every))

    def positionCheckDue(self) -> bool:
        return (
            self.position_check
            and self._homed
            and not self.checking
            and not self.gc.disable_chute
            and self.pieces_since_check >= self.position_check_every
        )

    def checkPosition(self) -> "PositionCheck":
        """Find the home switch and say how far the chute had drifted, putting
        it back on its true position (position_check.py). Blocks for about two
        seconds, so a caller on the main loop runs it on a thread."""
        from .position_check import checkPosition, recordCheck

        self.checking = True
        try:
            check = checkPosition(self)
        finally:
            self.checking = False
            self.pieces_since_check = 0
        if not check.ok:
            self.logger.error(f"Chute: position check failed: {check.error}; the chute needs homing.")
        elif check.beyond_range:
            self.logger.error(
                f"Chute: position check found the switch at once: off by {check.drift_deg:g}° or more. "
                "The chute is back on its true position."
            )
        elif check.lost_steps:
            self.logger.warning(
                f"Chute: position check found {check.drift_deg:+.2f}° ({check.drift_steps:+d} µsteps) of drift "
                "since the last check: it lost steps. The chute is back on its true position."
            )
        else:
            self.logger.info(
                f"Chute: position check: {check.drift_deg:+.2f}° ({check.drift_steps:+d} µsteps), "
                f"read to {check.precision_deg}°, in {check.duration_s} s."
            )
        try:
            recordCheck(check)
        except Exception as e:
            self.logger.warning(f"Chute: could not record the position check: {e}")
        return check

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
        angle = self.stepper.position_degrees / self.gear_ratio
        # A chute that turns without limit keeps counting turns; where it points
        # is the angle within one.
        return angle % 360.0 if self.variant.turns_freely else angle

    def setGearRatio(self, gear_ratio: float | None) -> None:
        self.gear_ratio = float(gear_ratio) if gear_ratio else self.variant.gear_ratio

    def setDiscardBin(self, discard_bin: tuple[int, int, int] | None) -> None:
        """The bin that takes the pieces no other bin wants. A chute pieces fall
        out of the bottom of needs none: they land in the tray under it."""
        self.discard_bin = BinAddress(*discard_bin) if discard_bin else None

    def isDiscardBin(self, address: BinAddress) -> bool:
        return self.discard_bin is not None and self.discard_bin == address

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
        # Wrap the bin onto the circle. A chute with a travel limit can never
        # cross its home stop, so the bin is reachable iff its wrapped position
        # lands inside the travel: the arc between the far stop and home is the
        # only dead wedge. Wrapping is what lets a section that home cut through
        # still serve the bins sitting just clockwise of home — reached the long
        # way round, never across the stop.
        norm = angle % 360.0
        travel = self.variant.travel_deg
        if travel is not None and norm > travel:
            return None
        return norm

    def getAngleForBin(self, address: BinAddress) -> float | None:
        num_bins = self._binsInSection(address.layer_index, address.section_index)
        return self.angleForVirtualBin(
            address.section_index, address.bin_index, num_bins
        )

    def setSpeed(self, speed: int) -> None:
        # The board keeps the last speed limits any caller sent (start-up's, a
        # jog's, a sweep's), so every chute move sets its own.
        self.stepper.set_speed_limits(MIN_SPEED_MICROSTEPS_PER_SEC, speed)

    def travelTo(self, target: float) -> float:
        """How far the chute turns to point at `target`, in chute degrees, signed.
        A chute with a travel limit goes straight there between its stops; one
        that turns without limit takes the short way round."""
        if self.variant.turns_freely:
            return (target - self.current_angle + 180.0) % 360.0 - 180.0
        target = max(0.0, min(360.0, target))
        return target - self.current_angle

    def moveToAngle(self, target: float, max_speed: int | None = None) -> int | None:
        """Start a move at the operating speed, or at `max_speed` when given; the
        estimated duration in ms, or None if the board refused it."""
        current = self.current_angle
        delta_stepper_angle = self.travelTo(target) * self.gear_ratio
        speed = int(max_speed or self.operating_speed_microsteps_per_second)
        estimated_ms = self.stepper.estimateMoveDegreesMs(delta_stepper_angle, max_speed=speed)

        if self.gc.disable_chute:
            self.logger.info(
                f"Chute: [DISABLED] would move from {current:.1f}° to {target:.1f}° (delta_stepper_deg={delta_stepper_angle:.2f}, est_ms={estimated_ms})"
            )
            return estimated_ms

        self.setSpeed(speed)
        self.logger.info(
            f"Chute: moving from {current:.1f}° to {target:.1f}° at {speed} µsteps/s (delta_stepper_deg={delta_stepper_angle:.2f}, est_ms={estimated_ms})"
        )
        if not self.stepper.move_degrees(delta_stepper_angle):
            return None
        return estimated_ms

    def isBinReachable(self, address: BinAddress) -> bool:
        return self.getAngleForBin(address) is not None

    def moveToBin(self, address: BinAddress) -> int | None:
        target = self.getAngleForBin(address)
        if target is None:
            self.logger.error(f"Chute: bin {address} is unreachable")
            return None
        self.logger.info(
            f"Chute: moveToBin layer={address.layer_index} section={address.section_index} bin={address.bin_index} -> {target:.2f}°"
        )
        estimated_ms = self.moveToAngle(target)
        if estimated_ms is not None:
            self.pieces_since_check += 1
        return estimated_ms

    def moveToAngleBlocking(self, target: float, timeout_buffer_ms: int = 0) -> int | None:
        """Move and wait; the estimated duration in ms, or None if it was refused or did not finish."""
        current = self.current_angle
        delta_stepper_angle = self.travelTo(target) * self.gear_ratio
        speed = int(self.operating_speed_microsteps_per_second)
        estimated_ms = self.stepper.estimateMoveDegreesMs(delta_stepper_angle, max_speed=speed)
        timeout_ms = max(1, estimated_ms + timeout_buffer_ms)

        if self.gc.disable_chute:
            self.logger.info(
                f"Chute: [DISABLED] would move from {current:.1f}° to {target:.1f}° (delta_stepper_deg={delta_stepper_angle:.2f}, est_ms={estimated_ms}, timeout_ms={timeout_ms})"
            )
            return estimated_ms

        self.setSpeed(speed)
        self.logger.info(
            f"Chute: moving(blocking) from {current:.1f}° to {target:.1f}° at {speed} µsteps/s (delta_stepper_deg={delta_stepper_angle:.2f}, est_ms={estimated_ms}, timeout_ms={timeout_ms})"
        )
        if not self.stepper.move_degrees_blocking(delta_stepper_angle, timeout_ms=timeout_ms):
            return None
        return estimated_ms

    def backoffToFirstBin(self) -> bool:
        backoff_angle = self.angleForVirtualBin(
            0, 0, self._binsInFirstSection(), unclamped=True
        )
        if backoff_angle is None or backoff_angle <= 0.0:
            return True
        try:
            if self.moveToAngleBlocking(backoff_angle, timeout_buffer_ms=1500) is None:
                self.logger.error("Chute: backoff to bin 1 did not finish")
                return False
            self.logger.info(f"Chute: backed off to bin 1 ({backoff_angle:.2f}°)")
            return True
        except Exception as exc:
            self.logger.error(f"Chute: backoff to bin 1 failed: {exc}")
            return False

    def home(self) -> bool:
        """Find home the way this kind of chute does (chute_homing.py)."""
        find_home = homeOnMagnet if self.variant.home_on == HOME_ON_MAGNET else homeOnSwitch
        if not find_home(self):
            return False
        self.logger.info("Chute: homed successfully")
        self._homed = True
        self.pieces_since_check = 0
        return True
