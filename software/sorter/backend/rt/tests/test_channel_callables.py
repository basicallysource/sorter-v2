from __future__ import annotations

import logging
from dataclasses import dataclass

from rt.hardware.channel_callables import build_c4_callables, build_chute_callables


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
        self.speed_limits: list[tuple[int, int]] = []
        self.moves: list[float] = []

    def set_speed_limits(self, accel: int, speed: int) -> None:
        self.speed_limits.append((accel, speed))

    def move_degrees(self, degrees: float) -> bool:
        self.moves.append(degrees)
        return True


class _CarouselConfig:
    default_steps_per_second = 100


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

    assert irl.carousel_stepper.speed_limits == [(16, 240), (16, 100)]
    assert irl.carousel_stepper.moves == [6.0, 3.0]


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
