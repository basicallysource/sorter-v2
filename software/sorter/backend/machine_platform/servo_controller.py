from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Sequence

import serial.tools.list_ports

from global_config import GlobalConfig
from hardware.serial_identity import canonical_port_path, stable_port_path
from irl.parse_user_toml import ServoChannelConfig, WaveshareServoConfig
from machine_platform.control_board import ControlBoard

_RPI_PICO_VID = 0x2E8A  # Feeder / Distribution MCUs — never a servo bus


@dataclass(frozen=True)
class LayerServoAssignment:
    id: int | None
    invert: bool = False


class UnassignedServoMotor:
    def __init__(self, *, invert: bool, layer_index: int):
        self.channel = None
        self._invert = invert
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
            "error": None,
            "name": self._name,
            "layer_index": self._layer_index,
            "invert": self._invert,
        }

    def open(self, _open_angle: int | None = None) -> None:
        raise RuntimeError("No servo assigned to this layer.")

    def close(self, _closed_angle: int | None = None) -> None:
        raise RuntimeError("No servo assigned to this layer.")

    def toggle(self) -> None:
        raise RuntimeError("No servo assigned to this layer.")

    def recalibrate(self) -> tuple[int, int]:
        raise RuntimeError("No servo assigned to this layer.")

    def isOpen(self) -> bool:
        return False

    def isClosed(self) -> bool:
        return False


class OfflineServoMotor:
    def __init__(
        self,
        *,
        servo_id: int | None,
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

    def shutdown(self) -> None:
        return


class Pca9685ServoController(ServoController):
    backend_name = "pca9685"

    def __init__(
        self,
        gc: GlobalConfig,
        source_board: ControlBoard,
        assignments: Sequence[LayerServoAssignment],
    ):
        self._gc = gc
        self._source_board = source_board
        self._assignments = tuple(assignments)
        self.issues = []

    def create_layer_servos(self, distribution_layout: Any) -> list[Any]:
        layer_servos: list[Any] = []
        for index, layer in enumerate(distribution_layout.layers):
            assignment = (
                self._assignments[index]
                if index < len(self._assignments)
                else LayerServoAssignment(id=index)
            )
            if assignment.id is None:
                if bool(getattr(layer, "enabled", True)):
                    raise IndexError(f"Layer {index} has no servo configured.")
                servo = UnassignedServoMotor(invert=assignment.invert, layer_index=index)
                servo.set_name(f"layer_{index}_servo")
                layer_servos.append(servo)
                continue
            if assignment.id < 0 or assignment.id >= len(self._source_board.servos):
                raise IndexError(
                    f"Layer {index} servo channel {assignment.id} not available. "
                    f"Only {len(self._source_board.servos)} servos are configured."
                )

            servo = self._source_board.servos[assignment.id]
            servo.set_name(f"layer_{index}_servo")
            # No default angles are injected here. A PCA servo stays uncalibrated
            # (open/closed = None) until per-layer angles are locked in via the
            # UI; config.py applies any saved per-layer angles after this.
            layer_servos.append(servo)
            self._gc.logger.info(
                f"Initialized PCA9685 servo 'layer_{index}_servo' on channel {assignment.id}, "
                f"invert={assignment.invert}"
            )
        return layer_servos


class WaveshareServoController(ServoController):
    """Layer servos on a Waveshare SC bus.

    Port binding contract: the bus is always addressed via its stable
    /dev/serial/by-id symlink when one exists — both for a configured port and
    for auto-detection — so kernel re-numbering of /dev/ttyACM* across
    replug/reboot cannot rebind the controller to a different device.
    """

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
        self._bus_service = None
        self.issues = []

    @property
    def bus_service(self):
        return self._bus_service

    def create_layer_servos(self, distribution_layout: Any) -> list[Any]:
        from hardware.waveshare_bus_service import get_waveshare_bus_service
        from hardware.waveshare_servo import WaveshareServoMotor

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
            service = get_waveshare_bus_service(port)
            service.attach_persistent()
            self._bus_service = service
        except Exception as exc:
            error = f"Failed to open Waveshare SC servo bus on {port}: {exc}"
            self._gc.logger.warning(error)
            return [
                self._make_offline_servo(index, assignment, error)
                for index, assignment in self._iter_layer_assignments(distribution_layout)
            ]
        layer_servos: list[Any] = []
        for index, assignment in self._iter_layer_assignments(distribution_layout):
            layer = distribution_layout.layers[index]
            if assignment.id is None:
                if bool(getattr(layer, "enabled", True)):
                    error = "No servo configured for enabled layer."
                    layer_servos.append(self._make_offline_servo(index, assignment, error))
                else:
                    servo = UnassignedServoMotor(invert=assignment.invert, layer_index=index)
                    servo.set_name(f"layer_{index}_servo")
                    layer_servos.append(servo)
                continue
            servo = WaveshareServoMotor(service, assignment.id, invert=assignment.invert)
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
        assigned_ids = [
            assignment.id
            for _, assignment in self._iter_layer_assignments(distribution_layout)
            if assignment.id is not None
        ]
        if assigned_ids:
            service.set_recovery_probe_ids(assigned_ids)
        return layer_servos

    def shutdown(self) -> None:
        if self._bus_service is None:
            return
        try:
            self._bus_service.detach_persistent()
        finally:
            self._bus_service = None

    def _iter_layer_assignments(self, distribution_layout: Any) -> list[tuple[int, LayerServoAssignment]]:
        assignments: list[tuple[int, LayerServoAssignment]] = []
        for index, _layer in enumerate(distribution_layout.layers):
            assignment = (
                self._assignments[index]
                if index < len(self._assignments)
                else LayerServoAssignment(id=None)
            )
            assignments.append((index, assignment))
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
            "message": error,
        }
        if assignment.id is not None:
            issue["servo_id"] = assignment.id
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
            port = stable_port_path(self._port)
            if not os.path.exists(port):
                self._gc.logger.info(
                    f"Configured Waveshare servo port {port} does not currently exist."
                )
            return port

        mcu_ports = {canonical_port_path(port) for port in self._mcu_ports}
        candidates = sorted(
            stable_port_path(entry.device)
            for entry in serial.tools.list_ports.comports()
            if entry.vid is not None
            and entry.vid != _RPI_PICO_VID
            and canonical_port_path(entry.device) not in mcu_ports
        )
        if not candidates:
            return None
        chosen = candidates[0]
        if len(candidates) > 1:
            self._gc.logger.warning(
                f"Multiple Waveshare servo bus candidates {candidates}; using {chosen}. "
                "Set servo.port in config to pin one."
            )
        return chosen


def build_servo_controller(
    gc: GlobalConfig,
    *,
    control_boards: Sequence[ControlBoard],
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
    )


def _select_pca_servo_source(control_boards: Sequence[ControlBoard]) -> ControlBoard | None:
    distribution_board = next(
        (board for board in control_boards if board.identity.role == "distribution" and board.servos),
        None,
    )
    if distribution_board is not None:
        return distribution_board

    return next((board for board in control_boards if board.servos), None)
