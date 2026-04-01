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


class OfflineServoMotor:
    def __init__(
        self,
        *,
        servo_id: int,
        invert: bool,
        error: str,
        layer_index: int,
    ):
        self.channel = servo_id
        self._invert = invert
        self._error = error
        self._layer_index = layer_index
        self._name = f"layer_{layer_index}_servo"

    @property
    def available(self) -> bool:
        return False

    @property
    def stopped(self) -> bool:
        return True

    @property
    def enabled(self) -> bool:
        return False

    @enabled.setter
    def enabled(self, _value: bool) -> None:
        return

    def set_name(self, name: str) -> None:
        self._name = name

    def set_invert(self, invert: bool) -> None:
        self._invert = invert

    def feedback(self) -> dict[str, Any]:
        return {
            "available": False,
            "channel": self.channel,
            "position": None,
            "is_open": None,
            "open_position": None,
            "closed_position": None,
            "min_limit": None,
            "max_limit": None,
            "error": self._error,
            "name": self._name,
            "layer_index": self._layer_index,
            "invert": self._invert,
        }

    def open(self, _open_angle: int | None = None) -> None:
        raise RuntimeError(self._error)

    def close(self, _closed_angle: int | None = None) -> None:
        raise RuntimeError(self._error)

    def toggle(self) -> None:
        raise RuntimeError(self._error)

    def recalibrate(self) -> tuple[int, int]:
        raise RuntimeError(self._error)

    def isOpen(self) -> bool:
        return False

    def isClosed(self) -> bool:
        return False


class ServoController(ABC):
    backend_name: str
    supports_feedback: bool = False
    supports_calibration: bool = False
    issues: list[dict[str, Any]]

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
        self.issues = []

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
        self.issues = []

    def create_layer_servos(self, distribution_layout: Any) -> list[Any]:
        from hardware.waveshare_servo import ScServoBus, WaveshareServoMotor

        port = self._resolve_port()
        if port is None:
            error = "Waveshare servo backend configured but no serial port found. Set servo.port in config."
            self._gc.logger.warning(error)
            return [
                self._make_offline_servo(index, assignment, error)
                for index, assignment in self._iter_layer_assignments(distribution_layout)
            ]

        self._gc.logger.info(f"Using Waveshare SC servo bus on {port}")
        try:
            bus = ScServoBus(port)
        except Exception as exc:
            error = f"Failed to open Waveshare SC servo bus on {port}: {exc}"
            self._gc.logger.warning(error)
            return [
                self._make_offline_servo(index, assignment, error)
                for index, assignment in self._iter_layer_assignments(distribution_layout)
            ]
        layer_servos: list[Any] = []
        for index, assignment in self._iter_layer_assignments(distribution_layout):
            servo = WaveshareServoMotor(bus, assignment.id, invert=assignment.invert)
            try:
                servo.initialize()
            except Exception as exc:
                error = f"Cannot communicate with servo {assignment.id}: {exc}"
                self._gc.logger.warning(
                    f"Waveshare servo layer {index + 1} id={assignment.id} unavailable: {exc}"
                )
                layer_servos.append(self._make_offline_servo(index, assignment, error))
                continue
            servo.set_name(f"layer_{index}_servo")
            layer_servos.append(servo)
            self._gc.logger.info(
                f"Initialized Waveshare servo 'layer_{index}_servo' id={assignment.id}, "
                f"invert={assignment.invert}"
            )
        return layer_servos

    def _iter_layer_assignments(self, distribution_layout: Any) -> list[tuple[int, LayerServoAssignment]]:
        assignments: list[tuple[int, LayerServoAssignment]] = []
        for index, _layer in enumerate(distribution_layout.layers):
            if index >= len(self._assignments):
                raise IndexError(
                    f"Layer {index} servo not configured. Only {len(self._assignments)} servo.channels defined."
                )
            assignments.append((index, self._assignments[index]))
        return assignments

    def _make_offline_servo(
        self,
        index: int,
        assignment: LayerServoAssignment,
        error: str,
    ) -> OfflineServoMotor:
        issue = {
            "kind": "servo",
            "backend": self.backend_name,
            "layer_index": index,
            "servo_id": assignment.id,
            "message": error,
        }
        self.issues.append(issue)
        offline = OfflineServoMotor(
            servo_id=assignment.id,
            invert=assignment.invert,
            error=error,
            layer_index=index,
        )
        offline.set_name(f"layer_{index}_servo")
        return offline

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
