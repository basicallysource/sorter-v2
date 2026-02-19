from typing import TYPE_CHECKING
from global_config import GlobalConfig
from blob_manager import getServoPosition, setServoPosition

if TYPE_CHECKING:
    from .mcu import MCU

CLOSED_ANGLE = 72
OPEN_ANGLE = 0


class Servo:
    def __init__(
        self,
        gc: GlobalConfig,
        mcu: "MCU",
        pin: int,
        name: str,
    ):
        self.gc = gc
        self.mcu = mcu
        self.pin = pin
        self.name = name
        self.current_angle = getServoPosition(name)

        logger = gc.logger
        logger.info(
            f"Initialized Servo '{name}' on pin {pin}, position={self.current_angle}°"
        )

        mcu.command("S", pin, self.current_angle)

    def setAngle(self, angle: int) -> None:
        self.gc.logger.info(f"Servo '{self.name}' moving to {angle}°")
        self.mcu.command("S", self.pin, angle)
        self.current_angle = angle
        setServoPosition(self.name, angle)

    def open(self) -> None:
        self.setAngle(OPEN_ANGLE)

    def close(self) -> None:
        self.setAngle(CLOSED_ANGLE)

    def toggle(self) -> None:
        if self.current_angle == OPEN_ANGLE:
            self.close()
        else:
            self.open()

    def isOpen(self) -> bool:
        return self.current_angle == OPEN_ANGLE

    def isClosed(self) -> bool:
        return self.current_angle == CLOSED_ANGLE
