from __future__ import annotations

import logging
from dataclasses import dataclass

from rt.hardware.channel_callables import (
    build_c2_callables,
    build_c3_callables,
    build_c4_callables,
    build_chute_callables,
)
from rt.hardware.motion_profiles import MotionDiagnostics


class _Stepper:
    stopped = True


@dataclass
class _AddressSnapshot:
    layer_index: int
    section_index: int
    bin_index: int


class _Chute:
    first_bin_center = 8.25

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.stepper = _Stepper()

    def getAngleForBin(self, address) -> float | None:
        return 42.0

    def moveToBin(self, address) -> int:
        snap = _AddressSnapshot(
            address.layer_index,
            address.section_index,
            address.bin_index,
        )
        self.events.append(
            f"move-bin:{snap.layer_index}-{snap.section_index}-{snap.bin_index}"
        )
        return 100

    def moveToAngle(self, angle: float) -> int:
        self.events.append(f"move-angle:{angle:.2f}")
        return 100


class _Servo:
    def __init__(self, index: int, events: list[str], *, is_open: bool = False) -> None:
        self.index = index
        self.events = events
        self._is_open = is_open

    def isOpen(self) -> bool:
        return self._is_open

    def close(self) -> None:
        self.events.append(f"close:{self.index}")
        self._is_open = False

    def open(self) -> None:
        self.events.append(f"open:{self.index}")
        self._is_open = True


class _Rules:
    def reject_bin_id(self) -> str:
        return "reject"


class _CarouselStepper:
    def __init__(self) -> None:
        self.accelerations: list[int] = []
        self.speed_limits: list[tuple[int, int]] = []
        self.moves: list[float] = []

    def set_acceleration(self, acceleration: int) -> None:
        self.accelerations.append(acceleration)

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits.append((min_speed, max_speed))

    def degrees_for_microsteps(self, steps: int) -> float:
        return float(steps) / 10.0

    def microsteps_for_degrees(self, degrees: float) -> int:
        return int(round(float(degrees) * 10.0))

    def move_degrees(self, degrees: float) -> bool:
        self.moves.append(degrees)
        return True


class _CarouselConfig:
    default_steps_per_second = 100


@dataclass
class _RotorPulseConfig:
    steps_per_pulse: int
    microsteps_per_second: int
    delay_between_pulse_ms: int = 0
    acceleration_microsteps_per_second_sq: int | None = None


class _RotorStepper:
    def __init__(self) -> None:
        self.accelerations: list[int] = []
        self.speed_limits: list[tuple[int, int]] = []
        self.moves: list[float] = []

    def set_acceleration(self, acceleration: int) -> None:
        self.accelerations.append(acceleration)

    def set_speed_limits(self, min_speed: int, max_speed: int) -> None:
        self.speed_limits.append((min_speed, max_speed))

    def degrees_for_microsteps(self, steps: int) -> float:
        return float(steps) / 10.0

    def microsteps_for_degrees(self, degrees: float) -> int:
        return int(round(float(degrees) * 10.0))

    def move_degrees(self, degrees: float) -> bool:
        self.moves.append(degrees)
        return True


def test_c2_callable_applies_configured_motion_profile() -> None:
    irl = type("Irl", (), {})()
    irl.c_channel_2_rotor_stepper = _RotorStepper()
    irl.feeder_config = type(
        "Feeder",
        (),
        {
            "second_rotor_normal": _RotorPulseConfig(
                steps_per_pulse=1000,
                microsteps_per_second=5000,
                acceleration_microsteps_per_second_sq=2500,
            )
        },
    )()

    pulse, _ = build_c2_callables(irl, logging.getLogger("test"))

    assert pulse(250.0) is True

    assert irl.c_channel_2_rotor_stepper.accelerations == [2500]
    assert irl.c_channel_2_rotor_stepper.speed_limits == [(16, 5000)]
    assert irl.c_channel_2_rotor_stepper.moves == [100.0]


def test_c3_callable_uses_normal_and_precise_profiles() -> None:
    irl = type("Irl", (), {})()
    irl.c_channel_3_rotor_stepper = _RotorStepper()
    irl.feeder_config = type(
        "Feeder",
        (),
        {
            "third_rotor_normal": _RotorPulseConfig(
                steps_per_pulse=2500,
                microsteps_per_second=12000,
            ),
            "third_rotor_precision": _RotorPulseConfig(
                steps_per_pulse=300,
                microsteps_per_second=3000,
            ),
        },
    )()

    pulse, _ = build_c3_callables(irl, logging.getLogger("test"))

    assert pulse("normal", 120.0) is True
    assert pulse("precise", 1000.0) is True

    assert irl.c_channel_3_rotor_stepper.accelerations == [10000, 10000]
    assert irl.c_channel_3_rotor_stepper.speed_limits == [(16, 12000), (16, 3000)]
    assert irl.c_channel_3_rotor_stepper.moves == [250.0, 30.0]


def test_c4_callables_restore_default_speed_for_slow_moves() -> None:
    irl = type("Irl", (), {})()
    irl.carousel_stepper = _CarouselStepper()
    irl.irl_config = type("Config", (), {"carousel_stepper": _CarouselConfig()})()

    carousel_move, transport_move, *_ = build_c4_callables(
        irl,
        logging.getLogger("test"),
        transport_speed_scale=2.4,
    )

    assert transport_move(6.0) is True
    assert carousel_move(3.0) is True

    assert irl.carousel_stepper.accelerations == [10000, 9000]
    assert irl.carousel_stepper.speed_limits == [(16, 240), (16, 100)]
    assert irl.carousel_stepper.moves == [6.0, 3.0]


def test_c4_eject_applies_classification_pulse_profile() -> None:
    irl = type("Irl", (), {})()
    irl.carousel_stepper = _CarouselStepper()
    irl.irl_config = type("Config", (), {"carousel_stepper": _CarouselConfig()})()
    irl.feeder_config = type(
        "Feeder",
        (),
        {
            "classification_channel_eject": _RotorPulseConfig(
                steps_per_pulse=1000,
                microsteps_per_second=3400,
                acceleration_microsteps_per_second_sq=2500,
            )
        },
    )()

    _carousel, _transport, _continuous, _purge, _mode, eject, *_rest = build_c4_callables(
        irl,
        logging.getLogger("test"),
        transport_speed_scale=2.4,
    )

    assert eject() is True

    assert irl.carousel_stepper.accelerations == [2500]
    assert irl.carousel_stepper.speed_limits == [(16, 3400)]
    assert irl.carousel_stepper.moves == [100.0]


def test_c4_continuous_move_uses_named_continuous_profile() -> None:
    irl = type("Irl", (), {})()
    irl.carousel_stepper = _CarouselStepper()
    irl.irl_config = type("Config", (), {"carousel_stepper": _CarouselConfig()})()
    diagnostics = MotionDiagnostics(warn_throttle_s=0.0)

    _carousel, _transport, continuous_move, *_ = build_c4_callables(
        irl,
        logging.getLogger("test"),
        transport_speed_scale=2.4,
        motion_diagnostics=diagnostics,
    )

    assert continuous_move(6.0) is True

    motion = diagnostics.status_snapshot()["last_by_channel"]["c4"]
    assert motion["profile"] == "continuous"
    assert motion["source"] == "c4_continuous"
    assert irl.carousel_stepper.speed_limits == [(16, 240)]


def test_c4_motion_diagnostics_records_named_profile_warning() -> None:
    irl = type("Irl", (), {})()
    irl.carousel_stepper = _CarouselStepper()
    irl.irl_config = type("Config", (), {"carousel_stepper": _CarouselConfig()})()
    diagnostics = MotionDiagnostics(warn_throttle_s=0.0)

    _carousel_move, transport_move, *_ = build_c4_callables(
        irl,
        logging.getLogger("test"),
        transport_speed_scale=24.0,
        motion_diagnostics=diagnostics,
    )

    assert transport_move(6.0) is True

    motion = diagnostics.status_snapshot()["last_by_channel"]["c4"]
    assert motion["profile"] == "transport"
    assert motion["source"] == "c4_transport"
    assert motion["distance_usteps"] == 60
    assert motion["max_speed_usteps_per_s"] == 2400
    assert motion["reaches_cruise"] is False
    assert motion["warnings"] == ["target_speed_unreachable"]


def test_chute_callable_moves_bin_and_opens_target_layer() -> None:
    events: list[str] = []
    irl = type("Irl", (), {})()
    irl.chute = _Chute(events)
    irl.servos = [
        _Servo(0, events, is_open=True),
        _Servo(1, events, is_open=False),
    ]
    move, position_query = build_chute_callables(
        irl,
        _Rules(),
        logging.getLogger("test"),
    )

    assert move("L1-S2-B3") is True

    assert events == ["close:0", "move-bin:1-2-3", "open:1"]
    assert position_query() == "L1-S2-B3"


def test_chute_callable_reject_closes_layers_without_opening_one() -> None:
    events: list[str] = []
    irl = type("Irl", (), {})()
    irl.chute = _Chute(events)
    irl.servos = [
        _Servo(0, events, is_open=True),
        _Servo(1, events, is_open=True),
    ]
    move, position_query = build_chute_callables(
        irl,
        _Rules(),
        logging.getLogger("test"),
    )

    assert move("reject") is True

    assert events == ["close:0", "close:1", "move-angle:8.25"]
    assert position_query() == "reject"
