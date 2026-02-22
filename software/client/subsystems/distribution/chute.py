from dataclasses import dataclass
from typing import TYPE_CHECKING
from global_config import GlobalConfig
from irl.bin_layout import DistributionLayout

if TYPE_CHECKING:
    from irl.stepper import Stepper

GEAR_RATIO = 4
SECTIONS_PER_LAYER = 6
DEG_PER_SECTION = 60
PILLAR_WIDTH_DEG = 2.5
USABLE_DEG_PER_SECTION = DEG_PER_SECTION - PILLAR_WIDTH_DEG


@dataclass
class BinAddress:
    layer_index: int
    section_index: int
    bin_index: int


class Chute:
    def __init__(
        self, gc: GlobalConfig, stepper: "Stepper", layout: DistributionLayout
    ):
        self.gc = gc
        self.logger = gc.logger
        self.stepper = stepper
        self.layout = layout

    @property
    def current_angle(self) -> float:
        stepper_angle = (
            self.stepper.current_position_steps / self.stepper.total_steps_per_rev
        ) * 360.0
        return stepper_angle / GEAR_RATIO

    def getAngleForBin(self, address: BinAddress) -> float:
        layer = self.layout.layers[address.layer_index]
        section = layer.sections[address.section_index]
        num_bins = len(section.bins)

        section_start = address.section_index * DEG_PER_SECTION + PILLAR_WIDTH_DEG / 2
        bin_offset = (address.bin_index + 0.5) * (USABLE_DEG_PER_SECTION / num_bins)
        angle = section_start + bin_offset

        # convert to -180 to +180 range
        if angle > 180:
            angle -= 360
        return angle

    def moveToAngle(self, target: float) -> int:
        current = self.current_angle
        target_stepper_angle = target * GEAR_RATIO
        target_steps = round(
            (target_stepper_angle / 360.0) * self.stepper.total_steps_per_rev
        )
        delta_steps = target_steps - self.stepper.current_position_steps
        estimated_ms = self.stepper.estimateMoveStepsMs(delta_steps)

        if self.gc.disable_chute:
            self.logger.info(
                f"Chute: [DISABLED] would move from {current:.1f}° to {target:.1f}° (current_steps={self.stepper.current_position_steps}, target_steps={target_steps}, delta_steps={delta_steps}, est_ms={estimated_ms})"
            )
            return estimated_ms

        self.logger.info(
            f"Chute: moving from {current:.1f}° to {target:.1f}° (current_steps={self.stepper.current_position_steps}, target_steps={target_steps}, delta_steps={delta_steps}, est_ms={estimated_ms})"
        )
        self.stepper.moveSteps(delta_steps)
        return estimated_ms

    def moveToBin(self, address: BinAddress) -> int:
        target = self.getAngleForBin(address)
        return self.moveToAngle(target)

    def moveToAngleBlocking(self, target: float, timeout_buffer_ms: int = 0) -> int:
        current = self.current_angle
        target_stepper_angle = target * GEAR_RATIO
        target_steps = round(
            (target_stepper_angle / 360.0) * self.stepper.total_steps_per_rev
        )
        delta_steps = target_steps - self.stepper.current_position_steps
        estimated_ms = self.stepper.estimateMoveStepsMs(delta_steps)
        timeout_ms = max(1, estimated_ms + timeout_buffer_ms)

        if self.gc.disable_chute:
            self.logger.info(
                f"Chute: [DISABLED] would move from {current:.1f}° to {target:.1f}° (current_steps={self.stepper.current_position_steps}, target_steps={target_steps}, delta_steps={delta_steps}, est_ms={estimated_ms}, timeout_ms={timeout_ms})"
            )
            return estimated_ms

        self.logger.info(
            f"Chute: moving(blocking) from {current:.1f}° to {target:.1f}° (current_steps={self.stepper.current_position_steps}, target_steps={target_steps}, delta_steps={delta_steps}, est_ms={estimated_ms}, timeout_ms={timeout_ms})"
        )
        self.stepper.moveStepsBlocking(delta_steps, timeout_ms=timeout_ms)
        return estimated_ms

    def moveToBinBlocking(self, address: BinAddress, timeout_buffer_ms: int = 0) -> int:
        target = self.getAngleForBin(address)
        return self.moveToAngleBlocking(target, timeout_buffer_ms=timeout_buffer_ms)

    def home(self) -> int:
        self.logger.info("Chute: homing to zero")
        return self.moveToAngle(0.0)
