from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence

import serial.tools.list_ports

from global_config import GlobalConfig
from irl.parse_user_toml import ServoChannelConfig, WaveshareServoConfig
from machine_platform.control_board import ControlBoard


@dataclass(frozen=True)
class LayerServoAssignment:
    id: int
    invert: bool = False


class ServoController(ABC):
    backend_name: str
    supports_feedback: bool = False
    supports_calibration: bool = False

    @abstractmethod
    def create_layer_servos(self, distribution_layout: Any) -> list[Any]:
        raise NotImplementedError


class Pca9685ServoController(ServoController):
    backend_name = "pca9685"

    def __init__(
        self,
        gc: GlobalConfig,
        source_board: ControlBoard,
        assignments: Sequence[LayerServoAssignment],
        *,
        open_angle: int,
        closed_angle: int,
    ):
        self._gc = gc
        self._source_board = source_board
        self._assignments = tuple(assignments)
        self._open_angle = open_angle
        self._closed_angle = closed_angle

    def create_layer_servos(self, distribution_layout: Any) -> list[Any]:
        layer_servos: list[Any] = []
        for index, _layer in enumerate(distribution_layout.layers):
            assignment = (
                self._assignments[index]
                if index < len(self._assignments)
                else LayerServoAssignment(id=index)
            )
            if assignment.id < 0 or assignment.id >= len(self._source_board.servos):
                raise IndexError(
                    f"Layer {index} servo channel {assignment.id} not available. "
                    f"Only {len(self._source_board.servos)} servos are configured."
                )

            servo = self._source_board.servos[assignment.id]
            servo.set_name(f"layer_{index}_servo")
            if assignment.invert:
                servo.set_preset_angles(self._closed_angle, self._open_angle)
            else:
                servo.set_preset_angles(self._open_angle, self._closed_angle)
            layer_servos.append(servo)
            self._gc.logger.info(
                f"Initialized PCA9685 servo 'layer_{index}_servo' on channel {assignment.id}, "
                f"invert={assignment.invert}"
            )
        return layer_servos


class WaveshareServoController(ServoController):
    backend_name = "waveshare"
    supports_feedback = True
    supports_calibration = True

    def __init__(
        self,
        gc: GlobalConfig,
        *,
        port: str | None,
        assignments: Sequence[LayerServoAssignment],
        mcu_ports: Sequence[str],
    ):
        self._gc = gc
        self._port = port
        self._assignments = tuple(assignments)
        self._mcu_ports = tuple(mcu_ports)

    def create_layer_servos(self, distribution_layout: Any) -> list[Any]:
        from hardware.waveshare_servo import ScServoBus, WaveshareServoMotor

        port = self._resolve_port()
        if port is None:
            raise RuntimeError(
                "Waveshare servo backend configured but no serial port found. Set servo.port in config."
            )

        self._gc.logger.info(f"Using Waveshare SC servo bus on {port}")
        bus = ScServoBus(port)
        layer_servos: list[Any] = []
        for index, _layer in enumerate(distribution_layout.layers):
            if index >= len(self._assignments):
                raise IndexError(
                    f"Layer {index} servo not configured. Only {len(self._assignments)} servo.channels defined."
                )
            assignment = self._assignments[index]
            servo = WaveshareServoMotor(bus, assignment.id, invert=assignment.invert)
            servo.initialize()
            servo.set_name(f"layer_{index}_servo")
            layer_servos.append(servo)
            self._gc.logger.info(
                f"Initialized Waveshare servo 'layer_{index}_servo' id={assignment.id}, "
                f"invert={assignment.invert}"
            )
        return layer_servos

    def _resolve_port(self) -> str | None:
        if self._port is not None:
            return self._port

        mcu_ports = set(self._mcu_ports)
        for port in serial.tools.list_ports.comports():
            if port.device not in mcu_ports and port.vid is not None:
                return port.device
        return None


def build_servo_controller(
    gc: GlobalConfig,
    *,
    control_boards: Sequence[ControlBoard],
    open_angle: int,
    closed_angle: int,
    servo_channel_config: Sequence[ServoChannelConfig],
    waveshare_config: WaveshareServoConfig | None,
    mcu_ports: Sequence[str],
) -> ServoController:
    assignments = [
        LayerServoAssignment(id=channel.id, invert=channel.invert)
        for channel in servo_channel_config
    ]

    if waveshare_config is not None:
        return WaveshareServoController(
            gc,
            port=waveshare_config.port,
            assignments=assignments,
            mcu_ports=mcu_ports,
        )

    servo_source = _select_pca_servo_source(control_boards)
    if servo_source is None:
        raise RuntimeError("No servo-capable control board detected.")

    return Pca9685ServoController(
        gc,
        source_board=servo_source,
        assignments=assignments,
        open_angle=open_angle,
        closed_angle=closed_angle,
    )


def _select_pca_servo_source(control_boards: Sequence[ControlBoard]) -> ControlBoard | None:
    distribution_board = next(
        (board for board in control_boards if board.identity.role == "distribution" and board.servos),
        None,
    )
    if distribution_board is not None:
        return distribution_board

    return next((board for board in control_boards if board.servos), None)
