from dataclasses import dataclass
from typing import TYPE_CHECKING
from global_config import GlobalConfig
from .bin_layout import DistributionLayout

if TYPE_CHECKING:
    from irl.stepper import Stepper

GEAR_RATIO = 5
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
        self.current_angle: float = 0.0

    def getAngleForBin(self, address: BinAddress) -> float:
        layer = self.layout.layers[address.layer_index]
        section = layer.sections[address.section_index]
        num_bins = len(section.bins)

        section_start = address.section_index * DEG_PER_SECTION + PILLAR_WIDTH_DEG / 2
        bin_offset = (address.bin_index + 0.5) * (USABLE_DEG_PER_SECTION / num_bins)
        return section_start + bin_offset

    def moveToAngle(self, target: float) -> None:
        delta = target - self.current_angle
        if delta > 180:
            delta -= 360
        elif delta < -180:
            delta += 360

        stepper_deg = delta * GEAR_RATIO
        self.logger.info(
            f"Chute: moving from {self.current_angle:.1f}° to {target:.1f}° (delta={delta:.1f}°)"
        )
        self.stepper.rotate(stepper_deg)
        self.current_angle = target

    def moveToBin(self, address: BinAddress) -> None:
        target = self.getAngleForBin(address)
        self.moveToAngle(target)

    def home(self) -> None:
        self.logger.info("Chute: homing (stub)")
        self.current_angle = 0.0
