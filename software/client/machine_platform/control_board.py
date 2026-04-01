from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import time
from typing import Mapping, Sequence

from global_config import GlobalConfig
from hardware.bus import MCUBus
from hardware.sorter_interface import DigitalInputPin, ServoMotor, SorterInterface, StepperMotor


@dataclass(frozen=True)
class BoardIdentity:
    family: str
    role: str
    device_name: str
    port: str
    address: int


@dataclass(frozen=True)
class DiscoveredStepper:
    canonical_name: str
    physical_name: str
    stepper: StepperMotor


@dataclass(frozen=True)
class BoardProfile:
    family: str
    role: str
    physical_to_canonical_stepper_names: Mapping[str, str]
    input_aliases: Mapping[str, int]


SKR_PICO_FEEDER_PROFILE = BoardProfile(
    family="skr_pico",
    role="feeder",
    physical_to_canonical_stepper_names={
        "c_channel_1_rotor": "c_channel_1_rotor",
        "c_channel_2_rotor": "c_channel_2_rotor",
        "c_channel_3_rotor": "c_channel_3_rotor",
        "carousel": "carousel",
    },
    input_aliases={"carousel_home": 2},
)

SKR_PICO_DISTRIBUTION_PROFILE = BoardProfile(
    family="skr_pico",
    role="distribution",
    physical_to_canonical_stepper_names={
        "chute_stepper": "chute_stepper",
        "distribution_aux_1": "distribution_aux_1",
        "distribution_aux_2": "distribution_aux_2",
        "distribution_aux_3": "distribution_aux_3",
    },
    input_aliases={"chute_home": 3},
)

BASICALLY_FEEDER_PROFILE = BoardProfile(
    family="basically_rp2040",
    role="feeder",
    physical_to_canonical_stepper_names={
        "first_c_channel_rotor": "c_channel_1_rotor",
        "second_c_channel_rotor": "c_channel_2_rotor",
        "third_c_channel_rotor": "c_channel_3_rotor",
        "carousel": "carousel",
    },
    input_aliases={},
)

BASICALLY_DISTRIBUTION_PROFILE = BoardProfile(
    family="basically_rp2040",
    role="distribution",
    physical_to_canonical_stepper_names={
        "chute_stepper": "chute_stepper",
        "distribution_aux_1": "distribution_aux_1",
        "distribution_aux_2": "distribution_aux_2",
        "distribution_aux_3": "distribution_aux_3",
    },
    input_aliases={},
)

GENERIC_PROFILE = BoardProfile(
    family="generic_sorter_interface",
    role="unknown",
    physical_to_canonical_stepper_names={},
    input_aliases={},
)

_SKR_PICO_FEEDER_NAMES = frozenset(SKR_PICO_FEEDER_PROFILE.physical_to_canonical_stepper_names)
_BASICALLY_FEEDER_NAMES = frozenset(BASICALLY_FEEDER_PROFILE.physical_to_canonical_stepper_names)


class ControlBoard(ABC):
    @property
    @abstractmethod
    def identity(self) -> BoardIdentity:
        raise NotImplementedError

    @property
    @abstractmethod
    def interface(self) -> SorterInterface:
        raise NotImplementedError

    @property
    @abstractmethod
    def logical_stepper_names(self) -> tuple[str, ...]:
        raise NotImplementedError

    @property
    @abstractmethod
    def servos(self) -> Sequence[ServoMotor]:
        raise NotImplementedError

    @property
    @abstractmethod
    def input_aliases(self) -> Mapping[str, int]:
        raise NotImplementedError

    @abstractmethod
    def iter_steppers(self) -> tuple[DiscoveredStepper, ...]:
        raise NotImplementedError

    @abstractmethod
    def get_input(self, alias_or_channel: str | int) -> DigitalInputPin | None:
        raise NotImplementedError

    @property
    def board_key(self) -> str:
        identity = self.identity
        return f"{identity.family}:{identity.role}:{identity.device_name}"


class SorterInterfaceControlBoard(ControlBoard):
    def __init__(
        self,
        sorter_interface: SorterInterface,
        gc: GlobalConfig,
        port: str,
        address: int,
    ):
        self._interface = sorter_interface
        self._gc = gc
        self._profile = _detect_board_profile(sorter_interface)
        self._identity = BoardIdentity(
            family=self._profile.family,
            role=self._profile.role,
            device_name=sorter_interface.name,
            port=port,
            address=address,
        )

        physical_stepper_names = _reported_stepper_names(sorter_interface)
        discovered: list[DiscoveredStepper] = []
        for channel, physical_name in enumerate(physical_stepper_names):
            if channel >= len(sorter_interface.steppers):
                break
            canonical_name = self._profile.physical_to_canonical_stepper_names.get(
                physical_name, physical_name
            )
            discovered.append(
                DiscoveredStepper(
                    canonical_name=canonical_name,
                    physical_name=physical_name,
                    stepper=sorter_interface.steppers[channel],
                )
            )
        self._discovered_steppers = tuple(discovered)

    @property
    def identity(self) -> BoardIdentity:
        return self._identity

    @property
    def interface(self) -> SorterInterface:
        return self._interface

    @property
    def logical_stepper_names(self) -> tuple[str, ...]:
        return tuple(stepper.canonical_name for stepper in self._discovered_steppers)

    @property
    def servos(self) -> Sequence[ServoMotor]:
        return self._interface.servos

    @property
    def input_aliases(self) -> Mapping[str, int]:
        return self._profile.input_aliases

    def iter_steppers(self) -> tuple[DiscoveredStepper, ...]:
        return self._discovered_steppers

    def get_input(self, alias_or_channel: str | int) -> DigitalInputPin | None:
        if isinstance(alias_or_channel, str):
            channel = self._profile.input_aliases.get(alias_or_channel)
            if channel is None:
                return None
        else:
            channel = alias_or_channel

        if channel < 0 or channel >= len(self._interface.digital_inputs):
            return None
        return self._interface.digital_inputs[channel]


def discover_control_boards(
    gc: GlobalConfig,
    required_stepper_names: Sequence[str] = (),
    *,
    attempts: int = 8,
    retry_delay_s: float = 0.75,
) -> list[SorterInterfaceControlBoard]:
    ports = MCUBus.enumerate_buses()
    if not ports:
        raise RuntimeError("No MCU buses found.")

    discovered_boards: list[SorterInterfaceControlBoard] = []
    for attempt in range(1, attempts + 1):
        attempt_buses: list[MCUBus] = []
        attempt_boards: list[SorterInterfaceControlBoard] = []

        for port in ports:
            gc.logger.info(f"Scanning SorterInterface devices on {port}")
            try:
                bus = MCUBus(port=port)
            except Exception as exc:
                gc.logger.warning(f"Failed to open MCU bus on {port}: {exc}")
                continue

            attempt_buses.append(bus)
            devices = bus.scan_devices()
            if not devices:
                gc.logger.warning(f"No SorterInterface devices found on {port}")
                continue

            for address in devices:
                try:
                    sorter_interface = SorterInterface(bus, address, gc)
                    board = SorterInterfaceControlBoard(
                        sorter_interface=sorter_interface,
                        gc=gc,
                        port=port,
                        address=address,
                    )
                    attempt_boards.append(board)
                    gc.logger.info(
                        "Detected control board "
                        f"{board.identity.device_name} family={board.identity.family} "
                        f"role={board.identity.role} steppers={list(board.logical_stepper_names)}"
                    )
                except Exception as exc:
                    gc.logger.warning(
                        f"Failed to initialize SorterInterface on {port} addr {address}: {exc}"
                    )

        if not attempt_boards:
            _close_mcu_buses(attempt_buses)
            if attempt == attempts:
                raise RuntimeError(f"No SorterInterface devices found on buses: {ports}")
            gc.logger.warning(
                "No SorterInterface devices fully initialized on attempt "
                f"{attempt}/{attempts}. Retrying in {retry_delay_s:.2f}s..."
            )
            time.sleep(retry_delay_s)
            continue

        missing_stepper_names = [
            stepper_name
            for stepper_name in required_stepper_names
            if stepper_name
            not in {name for board in attempt_boards for name in board.logical_stepper_names}
        ]
        if not missing_stepper_names:
            discovered_boards = attempt_boards
            break

        _close_mcu_buses(attempt_buses)
        if attempt == attempts:
            raise RuntimeError(
                "Incomplete hardware discovery after "
                f"{attempts} attempts. Missing required steppers: {missing_stepper_names}"
            )
        gc.logger.warning(
            f"Incomplete hardware discovery on attempt {attempt}/{attempts}. "
            f"Missing required steppers: {missing_stepper_names}. "
            f"Retrying in {retry_delay_s:.2f}s..."
        )
        time.sleep(retry_delay_s)

    return discovered_boards


def _reported_stepper_names(sorter_interface: SorterInterface) -> tuple[str, ...]:
    board_info = sorter_interface._board_info
    stepper_names = board_info.get("stepper_names", [])
    available_stepper_count = len(sorter_interface.steppers)

    if not stepper_names:
        device_name = board_info.get("device_name", sorter_interface.name)
        stepper_names = [
            f"{device_name.lower().replace(' ', '_')}_ch{i}"
            for i in range(available_stepper_count)
        ]

    if len(stepper_names) > available_stepper_count:
        stepper_names = stepper_names[:available_stepper_count]

    return tuple(stepper_names)


def _detect_board_profile(sorter_interface: SorterInterface) -> BoardProfile:
    physical_names = frozenset(_reported_stepper_names(sorter_interface))
    digital_output_count = len(sorter_interface.digital_outputs)

    if physical_names == _SKR_PICO_FEEDER_NAMES:
        return SKR_PICO_FEEDER_PROFILE
    if physical_names == _BASICALLY_FEEDER_NAMES:
        return BASICALLY_FEEDER_PROFILE
    if "chute_stepper" in physical_names:
        if digital_output_count >= 5:
            return SKR_PICO_DISTRIBUTION_PROFILE
        if digital_output_count <= 2:
            return BASICALLY_DISTRIBUTION_PROFILE

    return BoardProfile(
        family=GENERIC_PROFILE.family,
        role="distribution" if "chute_stepper" in physical_names else GENERIC_PROFILE.role,
        physical_to_canonical_stepper_names={
            name: name for name in _reported_stepper_names(sorter_interface)
        },
        input_aliases={},
    )


def _close_mcu_buses(buses: list[MCUBus]) -> None:
    for bus in buses:
        try:
            bus._serial.close()
        except Exception:
            pass
