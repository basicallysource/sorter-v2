import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from global_config import GlobalConfig
from irl.bin_layout import DistributionLayout

if TYPE_CHECKING:
    from hardware.sorter_interface import StepperMotor, DigitalInputPin

GEAR_RATIO = 120 / 25  # 25T motor gear -> 25T idle gear -> 120T chute gear
DEG_PER_SECTION = 60
FIRST_BIN_CENTER = 8.4
PILLAR_WIDTH_DEG = 1.9
USABLE_DEG_PER_SECTION = DEG_PER_SECTION - PILLAR_WIDTH_DEG

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
    ):
        self.gc = gc
        self.logger = gc.logger
        self.stepper = stepper
        self.home_pin = home_pin
        self.layout = layout

    @property
    def current_angle(self) -> float:
        stepper_angle = self.stepper.position_degrees
        return stepper_angle / GEAR_RATIO

    def getAngleForBin(self, address: BinAddress) -> float:
        layer = self.layout.layers[address.layer_index]
        section = layer.sections[address.section_index]
        num_bins = len(section.bins)
        bin_width = USABLE_DEG_PER_SECTION / num_bins
        angle = FIRST_BIN_CENTER + address.section_index * DEG_PER_SECTION + address.bin_index * bin_width
        return angle

    def moveToAngle(self, target: float) -> int:
        target = max(0.0, min(360.0, target))
        current = self.current_angle
        target_stepper_angle = target * GEAR_RATIO
        current_stepper_angle = current * GEAR_RATIO
        delta_stepper_angle = target_stepper_angle - current_stepper_angle
        estimated_ms = self.stepper.estimateMoveDegreesMs(delta_stepper_angle)

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

    def moveToBin(self, address: BinAddress) -> int:
        target = self.getAngleForBin(address)
        return self.moveToAngle(target)

    def moveToAngleBlocking(self, target: float, timeout_buffer_ms: int = 0) -> int:
        target = max(0.0, min(360.0, target))
        current = self.current_angle
        target_stepper_angle = target * GEAR_RATIO
        current_stepper_angle = current * GEAR_RATIO
        delta_stepper_angle = target_stepper_angle - current_stepper_angle
        estimated_ms = self.stepper.estimateMoveDegreesMs(delta_stepper_angle)
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
        return self.moveToAngleBlocking(target, timeout_buffer_ms=timeout_buffer_ms)

    def home(self) -> None:
        self.logger.info("Chute: homing via sensor")
        self.stepper.home(HOME_SPEED_MICROSTEPS_PER_SEC, self.home_pin, home_pin_active_high=True)
        start = time.monotonic()
        while not self.stepper.stopped:
            if (time.monotonic() - start) * 1000 > HOME_TIMEOUT_MS:
                self.logger.error("Chute: homing timed out")
                return
            time.sleep(0.01)
        self.logger.info("Chute: homed successfully")
