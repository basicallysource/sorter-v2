"""The two kinds of chute: what each can reach, which way it turns, and how it
finds home. The stepper here is a pretend one that turns a pretend chute past a
pretend switch or magnet, with the firmware's own homing rule: run until the
input reads the level asked for, stop at once, and make that step 0."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from subsystems.distribution import chute_homing
from subsystems.distribution.chute import BinAddress, Chute
from subsystems.distribution.chute_homing import measureTurn
from subsystems.distribution.chute_variants import CABLE_CAGE, SLIP_RING

MICROSTEPS = 8
STEPS_PER_MOTOR_TURN = 200 * MICROSTEPS


class _Logger:
    def info(self, *a, **k) -> None: ...
    def warning(self, *a, **k) -> None: ...
    def error(self, *a, **k) -> None: ...


class _World:
    """A chute at a true angle, its stepper's count, and what its home input reads."""

    def __init__(self, *, gear_ratio: float, angle: float, magnet: tuple[float, float] | None = None) -> None:
        self.gear_ratio = gear_ratio
        self.angle = angle  # where the chute really is, in degrees, unbounded
        self.count = 0  # the stepper's microsteps
        self.magnet = magnet  # (from, to) in degrees: the input reads high there
        self.homes: list[tuple[int, bool]] = []

    @property
    def per_degree(self) -> float:
        return STEPS_PER_MOTOR_TURN * self.gear_ratio / 360.0

    def input_high(self) -> bool:
        if self.magnet is None:
            return self.angle <= 0.0  # a switch at the end of the travel
        low, high = self.magnet
        return low <= self.angle % 360.0 <= high

    def turn(self, steps: int) -> None:
        self.count += steps
        self.angle += steps / self.per_degree


class _Stepper:
    def __init__(self, world: _World) -> None:
        self._world = world
        self.total_steps_per_rev = STEPS_PER_MOTOR_TURN
        self._running = 0  # microsteps a poll while at speed
        # A homing run, as its caller sees it: still moving at the first look,
        # and its count just before the firmware zeroed it, read once.
        self._looks_while_homing = 0
        self._count_before_zero: int | None = None

    @property
    def stopped(self) -> bool:
        if self._looks_while_homing > 0:
            self._looks_while_homing -= 1
            return False
        return True

    def home(self, speed: int, _pin, home_pin_active_high: bool = True) -> None:
        self._world.homes.append((speed, home_pin_active_high))
        step = 1 if speed > 0 else -1
        for _ in range(int(self._world.per_degree * 800)):
            if self._world.input_high() == home_pin_active_high:
                break
            self._world.turn(step)
        self._count_before_zero = self._world.count
        self._looks_while_homing = 1
        self._world.count = 0

    def move_degrees(self, motor_degrees: float) -> bool:
        self._world.turn(round(motor_degrees / 360.0 * STEPS_PER_MOTOR_TURN))
        return True

    def move_degrees_blocking(self, motor_degrees: float, timeout_ms: int = 0) -> bool:
        return self.move_degrees(motor_degrees)

    def move_at_speed(self, speed: int, force: bool = False) -> bool:
        self._running = 40 if speed > 0 else (-40 if speed < 0 else 0)
        return True

    @property
    def position(self) -> int:
        if self._count_before_zero is not None:
            count, self._count_before_zero = self._count_before_zero, None
            return count
        # Each read lets the chute run on a little, as it does between polls.
        self._world.turn(self._running)
        return self._world.count

    @position.setter
    def position(self, value: int) -> None:
        self._world.count = value

    @property
    def position_degrees(self) -> float:
        return self._world.count / STEPS_PER_MOTOR_TURN * 360.0

    def microsteps_for_degrees(self, degrees: float) -> int:
        return round(degrees / 360.0 * STEPS_PER_MOTOR_TURN)

    def estimateMoveDegreesMs(self, degrees: float, max_speed: int = 5000) -> int:
        return 10

    def set_speed_limits(self, _low: int, _high: int) -> None: ...


class _Pin:
    def __init__(self, world: _World) -> None:
        self._world = world

    @property
    def value(self) -> bool:
        return self._world.input_high()


def _chute(world: _World, variant, **settings) -> Chute:
    gc = SimpleNamespace(logger=_Logger(), disable_chute=False)
    return Chute(
        gc,
        stepper=_Stepper(world),
        home_pin=_Pin(world),
        layout=SimpleNamespace(layers=[]),
        variant=variant,
        **settings,
    )


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    monkeypatch.setattr(chute_homing, "START_GRACE_S", 0.0)
    monkeypatch.setattr(chute_homing, "POLL_S", 0.0)


def test_a_cable_cage_chute_cannot_reach_the_wedge_before_home():
    chute = _chute(_World(gear_ratio=CABLE_CAGE.gear_ratio, angle=0.0), CABLE_CAGE, first_section_offset_deg=320.0)
    assert chute.angleForVirtualBin(0, 0, 1) == pytest.approx(345.875)
    # 355 degrees is past the far stop.
    chute.setAimingCalibration(6, 51.75, 329.125)
    assert chute.angleForVirtualBin(0, 0, 1) is None


def test_a_slip_ring_chute_reaches_every_angle():
    chute = _chute(_World(gear_ratio=6.0, angle=0.0), SLIP_RING, first_section_offset_deg=329.125)
    assert chute.angleForVirtualBin(0, 0, 1) == pytest.approx(355.0)
    assert chute.isBinReachable(BinAddress(0, 5, 0))


def test_a_cable_cage_chute_goes_straight_there_between_its_stops():
    world = _World(gear_ratio=CABLE_CAGE.gear_ratio, angle=0.0)
    chute = _chute(world, CABLE_CAGE)
    chute.moveToAngle(300.0)
    assert world.angle == pytest.approx(300.0, abs=0.1)
    chute.moveToAngle(10.0)
    assert world.angle == pytest.approx(10.0, abs=0.1)  # all the way back: 290 degrees
    assert chute.travelTo(340.0) == pytest.approx(330.0, abs=0.1)


def test_a_slip_ring_chute_takes_the_short_way_round():
    world = _World(gear_ratio=6.0, angle=0.0)
    chute = _chute(world, SLIP_RING)
    chute.moveToAngle(300.0)
    assert world.angle == pytest.approx(-60.0, abs=0.1)  # 60 degrees back, not 300 forward
    assert chute.current_angle == pytest.approx(300.0, abs=0.1)
    chute.moveToAngle(10.0)
    assert world.angle == pytest.approx(10.0, abs=0.1)  # across home, 70 degrees
    assert chute.travelTo(200.0) == pytest.approx(-170.0, abs=0.1)


def test_a_machines_own_gear_ratio_is_used_when_it_has_one():
    world = _World(gear_ratio=5.0, angle=0.0)
    chute = _chute(world, SLIP_RING, gear_ratio=5.0)
    chute.moveToAngle(90.0)
    assert world.angle == pytest.approx(90.0, abs=0.1)
    chute.setGearRatio(None)
    assert chute.gear_ratio == SLIP_RING.gear_ratio


def test_homing_on_a_switch_runs_to_it_and_backs_off_to_the_first_bin():
    world = _World(gear_ratio=CABLE_CAGE.gear_ratio, angle=200.0)
    chute = _chute(world, CABLE_CAGE)
    assert chute.home()
    assert chute.homed
    assert world.homes == [(chute_homing.HOME_SPEED_MICROSTEPS_PER_SEC, True)]
    # At the first section's start: the layout here is empty, so one bin's midpoint.
    assert world.angle == pytest.approx(chute.angleForVirtualBin(0, 0, 1, unclamped=True), abs=0.2)


@pytest.mark.parametrize("start", [200.0, 45.0, 30.0])
def test_homing_on_a_magnet_ends_on_the_same_edge_from_the_same_side(start):
    # The magnet reads from 20 to 38 degrees; homing runs toward lower angles,
    # so home is the window's upper edge, wherever the chute started (outside
    # the window, just above it, or inside it).
    world = _World(gear_ratio=6.0, angle=start, magnet=(20.0, 38.0))
    chute = _chute(world, SLIP_RING)
    assert chute.home()
    assert world.angle % 360.0 == pytest.approx(38.0, abs=0.1)
    assert world.count == 0
    # The last run was the crawl, toward lower angles, until the magnet read.
    assert world.homes[-1] == (chute_homing.MAGNET_CRAWL_SPEED, True)


def test_homing_on_a_magnet_fails_when_there_is_none():
    world = _World(gear_ratio=6.0, angle=100.0, magnet=(400.0, 401.0))  # never read
    chute = _chute(world, SLIP_RING)
    assert not chute.home()
    assert not chute.homed


def test_a_slip_ring_chutes_turn_can_be_measured():
    # A chute built with a 5.2:1 drive, on a machine that assumes 6:1.
    world = _World(gear_ratio=5.2, angle=100.0, magnet=(20.0, 38.0))
    chute = _chute(world, SLIP_RING)
    assert chute.home()
    ratio = measureTurn(chute)
    # To a microstep or two of the 8,320 in this chute's turn.
    assert ratio == pytest.approx(5.2, abs=0.002)
    assert chute.gear_ratio == SLIP_RING.gear_ratio  # measuring changes nothing: saving it does
    assert not chute.homed  # it must be homed again before it is used
