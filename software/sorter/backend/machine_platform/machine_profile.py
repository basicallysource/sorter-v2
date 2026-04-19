from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from machine_platform.control_board import ControlBoard
from machine_setup import get_machine_setup_definition


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
    automatic_feeder: bool
    carousel_transport: bool
    classification_channel: bool
    carousel_endstop_required: bool
    runtime_supported: bool


@dataclass(frozen=True)
class MachineProfile:
    camera_layout: str
    feeding_mode: str
    machine_setup: str
    servo_backend: str
    stepper_bindings: Mapping[str, str]
    stepper_direction_inverts: Mapping[str, bool]
    boards: tuple[BoardSummary, ...]
    capabilities: MachineCapabilities


def build_machine_profile(
    *,
    camera_layout: str,
    feeding_mode: str,
    machine_setup: str,
    servo_backend: str,
    stepper_bindings: Mapping[str, str],
    stepper_direction_inverts: Mapping[str, bool],
    control_boards: Sequence[ControlBoard],
) -> MachineProfile:
    machine_setup_definition = get_machine_setup_definition(machine_setup)
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
        machine_setup=machine_setup_definition.key,
        servo_backend=servo_backend,
        stepper_bindings=dict(stepper_bindings),
        stepper_direction_inverts=dict(stepper_direction_inverts),
        boards=boards,
        capabilities=MachineCapabilities(
            split_feeder=camera_layout == "split_feeder",
            servo_feedback=servo_backend == "waveshare",
            servo_calibration=servo_backend == "waveshare",
            multiple_control_boards=len(boards) > 1,
            automatic_feeder=machine_setup_definition.automatic_feeder,
            carousel_transport=machine_setup_definition.uses_carousel_transport,
            classification_channel=machine_setup_definition.uses_classification_channel,
            carousel_endstop_required=machine_setup_definition.requires_carousel_endstop,
            runtime_supported=machine_setup_definition.runtime_supported,
        ),
    )
