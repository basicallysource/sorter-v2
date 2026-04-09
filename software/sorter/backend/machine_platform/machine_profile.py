from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from machine_platform.control_board import ControlBoard


@dataclass(frozen=True)
class BoardSummary:
    family: str
    role: str
    device_name: str
    port: str
    address: int
    logical_steppers: tuple[str, ...]
    input_aliases: Mapping[str, int]


@dataclass(frozen=True)
class MachineCapabilities:
    split_feeder: bool
    servo_feedback: bool
    servo_calibration: bool
    multiple_control_boards: bool


@dataclass(frozen=True)
class MachineProfile:
    camera_layout: str
    feeding_mode: str
    servo_backend: str
    stepper_bindings: Mapping[str, str]
    stepper_direction_inverts: Mapping[str, bool]
    boards: tuple[BoardSummary, ...]
    capabilities: MachineCapabilities


def build_machine_profile(
    *,
    camera_layout: str,
    feeding_mode: str,
    servo_backend: str,
    stepper_bindings: Mapping[str, str],
    stepper_direction_inverts: Mapping[str, bool],
    control_boards: Sequence[ControlBoard],
) -> MachineProfile:
    boards = tuple(
        BoardSummary(
            family=board.identity.family,
            role=board.identity.role,
            device_name=board.identity.device_name,
            port=board.identity.port,
            address=board.identity.address,
            logical_steppers=tuple(board.logical_stepper_names),
            input_aliases=dict(board.input_aliases),
        )
        for board in control_boards
    )

    return MachineProfile(
        camera_layout=camera_layout,
        feeding_mode=feeding_mode,
        servo_backend=servo_backend,
        stepper_bindings=dict(stepper_bindings),
        stepper_direction_inverts=dict(stepper_direction_inverts),
        boards=boards,
        capabilities=MachineCapabilities(
            split_feeder=camera_layout == "split_feeder",
            servo_feedback=servo_backend == "waveshare",
            servo_calibration=servo_backend == "waveshare",
            multiple_control_boards=len(boards) > 1,
        ),
    )
