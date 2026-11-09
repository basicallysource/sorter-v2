"""The guard in Python against pretend servos: the same scenarios, the same
pretend servo and the same numbers as the firmware's desk test
(software/firmware/sorter_interface_firmware/test/servo_guard_test.cpp), so the
two implementations are held to the same behaviour.

Each pretend servo is a position that chases its goal, held by an optional hard
stop, with a load that grows with how far it is from its goal."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import pytest

from hardware.feetech import registers
from hardware.feetech.guard import INST_READ, INST_WRITE, SLOTS, ServoGuard
from hardware.feetech.link import (
    FLAG_RELEASE_AFTER_BACKOFF,
    FLAG_RELEASE_ON_ARRIVAL,
    FLAG_SC,
    GuardFull,
    GuardMove,
    GuardProbe,
    GuardReport,
    GuardState,
    NoReply,
)


@dataclass
class PretendServo:
    sc: bool = True  # SC series (big endian, 0 to 1023), else STS
    answers: bool = True
    torque: bool = False
    position: float = 500
    goal: int = 500
    speed: float = 600  # counts a second at full effort
    stop_above: float = 1e9  # a hard stop: the position cannot pass it going up
    stop_below: float = -1e9  # and one going down
    load: int = 0
    goal_writes: int = 0

    def step(self, seconds: float) -> None:
        if not self.torque:
            self.load = 0
            return
        error = self.goal - self.position
        # Effort is proportional to the error, as a servo's own control is.
        effort = max(-1.0, min(1.0, error / 20.0))
        nxt = self.position + effort * self.speed * seconds
        if (error > 0 and nxt > self.goal) or (error < 0 and nxt < self.goal):
            nxt = self.goal
        self.position = max(self.stop_below, min(self.stop_above, nxt))
        self.load = int(_round(effort * 1000.0))


def _round(value: float) -> int:
    """C's lround: halves away from zero."""
    return int(math.floor(abs(value) + 0.5)) * (1 if value >= 0 else -1)


class PretendWire:
    def __init__(self):
        self.servos: dict[int, PretendServo] = {}
        self.transactions = 0

    def transact(self, servo_id: int, instruction: int, params: bytes, data_len: int) -> tuple[int, bytes]:
        self.transactions += 1
        if servo_id == registers.BROADCAST_ID:
            for servo in self.servos.values():
                self._apply(servo, instruction, params, 0)
            return 0, b""
        servo = self.servos.get(servo_id)
        if servo is None or not servo.answers:
            raise NoReply(f"No reply from servo {servo_id}")
        return self._apply(servo, instruction, params, data_len)

    @staticmethod
    def _apply(servo: PretendServo, instruction: int, params: bytes, data_len: int) -> tuple[int, bytes]:
        if instruction == INST_WRITE:
            address = params[0]
            if address == 40:
                servo.torque = params[1] != 0
            elif address == 42 and servo.sc and len(params) >= 3:
                servo.goal = (params[1] << 8) | params[2]
                servo.goal_writes += 1
            elif address == 41 and not servo.sc and len(params) >= 4:
                servo.goal = params[2] | (params[3] << 8)
                servo.goal_writes += 1
            return 0, b""
        if instruction == INST_READ and params[0] == 56 and data_len == 6:
            position = _round(servo.position)
            load_word = (abs(servo.load) & 0x3FF) | (0x400 if servo.load < 0 else 0)
            order = "big" if servo.sc else "little"
            data = position.to_bytes(2, order) + b"\x00\x00" + load_word.to_bytes(2, order)
            return 0, data
        return 0, bytes(data_len)


class Bench:
    """The whole bench: the wire, the guard and a clock that both live on."""

    def __init__(self):
        self.wire = PretendWire()
        self.guard = ServoGuard(self.wire)
        self.now_us = 4_000_000_000  # near the 32-bit wrap, which the guard must survive

    def servo(self, servo_id: int) -> PretendServo:
        return self.wire.servos.setdefault(servo_id, PretendServo())

    def run(self, milliseconds: int) -> None:
        for _ in range(milliseconds):
            for servo in self.wire.servos.values():
                servo.step(0.001)
            self.now_us = (self.now_us + 1000) & 0xFFFFFFFF
            self.guard.tick(self.now_us)

    def state(self, servo_id: int) -> GuardState:
        return self.guard.report(servo_id, self.now_us).state

    def report(self, servo_id: int) -> GuardReport:
        return self.guard.report(servo_id, self.now_us)


def move_to(goal: int, flags: int = FLAG_SC) -> GuardMove:
    return GuardMove(
        flags=flags, goal=goal, stall_load=400, stall_ms=150, flat=3, arrived=8, backoff=30, timeout_ms=4000
    )


def probe_toward(direction: int, limit: int, flags: int = FLAG_SC) -> GuardProbe:
    return GuardProbe(
        flags=flags, direction=direction, limit=limit, step=3, period_ms=20, lag=12, load=700, backoff=15
    )


def test_a_free_move_arrives_and_lets_go():
    bench = Bench()
    bench.servo(1).position = 300
    bench.guard.move(1, move_to(640, FLAG_SC | FLAG_RELEASE_ON_ARRIVAL), bench.now_us)
    assert bench.state(1) == GuardState.MOVING
    bench.run(2500)
    assert bench.state(1) == GuardState.ARRIVED
    assert not bench.servo(1).torque, "let go on arrival"
    assert abs(bench.servo(1).position - 640) <= 8


def test_a_move_into_a_stop_stalls_and_backs_off():
    bench = Bench()
    servo = bench.servo(2)
    servo.position = 300
    servo.stop_above = 520
    bench.guard.move(2, move_to(700), bench.now_us)
    bench.run(700)
    # 220 counts at 600 a second, then 150 ms held: inside 700 ms.
    assert bench.state(2) == GuardState.STALLED
    report = bench.report(2)
    assert abs(report.mark - 520) <= 2, "stall marked at the stop"
    assert report.peak_load >= 400
    assert servo.goal == 490, "goal set back 30 counts toward the start"
    bench.run(300)
    assert abs(servo.position - 490) <= 2, "backed off"
    assert servo.torque, "holds after backing off unless asked to let go"


def test_a_stall_can_let_go_after_backing_off():
    bench = Bench()
    servo = bench.servo(3)
    servo.position = 600
    servo.stop_below = 450
    bench.guard.move(3, move_to(200, FLAG_SC | FLAG_RELEASE_AFTER_BACKOFF), bench.now_us)
    bench.run(500)
    assert bench.state(3) == GuardState.STALLED
    assert servo.goal == 480, "backed off upward"
    assert servo.torque, "still driving while it backs off"
    bench.run(300)
    assert not servo.torque, "let go once backed off"


def test_a_back_off_never_passes_the_start():
    bench = Bench()
    servo = bench.servo(4)
    servo.position = 500
    servo.stop_above = 510
    bench.guard.move(4, move_to(700), bench.now_us)
    bench.run(500)
    assert bench.state(4) == GuardState.STALLED
    assert servo.goal == 500, "backs off to the start, no further"


def test_a_probe_finds_a_stop():
    bench = Bench()
    servo = bench.servo(5)
    servo.position = 400
    servo.stop_above = 655
    bench.guard.probe(5, probe_toward(1, 1023), bench.now_us)
    assert servo.torque and servo.goal == 400, "probe starts holding where it is"
    bench.run(4000)
    assert bench.state(5) == GuardState.CONTACT
    report = bench.report(5)
    assert abs(report.mark - 655) <= 2, "contact marked at the stop"
    assert report.peak_load < 1000, "never pushed with everything it has"
    assert abs(servo.position - 640) <= 3, "came back 15 counts"


def test_a_probe_downward_finds_a_stop():
    bench = Bench()
    servo = bench.servo(6)
    servo.position = 400
    servo.stop_below = 210
    bench.guard.probe(6, probe_toward(-1, 0), bench.now_us)
    bench.run(4000)
    assert bench.state(6) == GuardState.CONTACT
    assert abs(bench.report(6).mark - 210) <= 2


def test_a_probe_with_nothing_in_its_way_reaches_its_limit():
    bench = Bench()
    servo = bench.servo(7)
    servo.position = 400
    bench.guard.probe(7, probe_toward(1, 520), bench.now_us)
    bench.run(3000)
    assert bench.state(7) == GuardState.NO_CONTACT
    assert abs(servo.position - 520) <= 3, "stopped at the limit"


def test_a_servo_that_stops_answering_is_lost():
    bench = Bench()
    bench.servo(8).position = 300
    bench.guard.move(8, move_to(700), bench.now_us)
    bench.run(50)
    bench.servo(8).answers = False
    goal_writes = bench.servo(8).goal_writes
    bench.run(200)
    assert bench.state(8) == GuardState.LOST
    assert bench.servo(8).goal_writes == goal_writes, "nothing written to a lost servo"


def test_a_servo_that_is_not_there_is_refused():
    bench = Bench()
    with pytest.raises(NoReply):
        bench.guard.move(9, move_to(500), bench.now_us)
    assert bench.state(9) == GuardState.IDLE, "absent servo is not watched"


def test_a_too_slow_move_times_out_where_it_is():
    bench = Bench()
    servo = bench.servo(10)
    servo.position = 100
    servo.speed = 300  # moving all the while, but 900 counts take three seconds
    move = replace(move_to(1000), timeout_ms=1000)
    bench.guard.move(10, move, bench.now_us)
    bench.run(1200)
    assert bench.state(10) == GuardState.TIMED_OUT
    assert abs(servo.goal - _round(servo.position)) <= 2, "held where it was"


def test_the_host_taking_over_ends_the_watch():
    bench = Bench()
    bench.servo(11).position = 300
    bench.guard.move(11, move_to(700), bench.now_us)
    bench.guard.forget(11)
    assert bench.state(11) == GuardState.IDLE
    transactions = bench.wire.transactions
    bench.run(100)
    assert bench.wire.transactions == transactions, "a forgotten servo is not read"


def test_stop_lets_go_or_holds():
    bench = Bench()
    held = bench.servo(12)
    held.position = 300
    bench.guard.move(12, move_to(900), bench.now_us)
    bench.run(200)
    bench.guard.stop(12, False, bench.now_us)
    assert abs(held.goal - _round(held.position)) <= 1, "held where it stopped"
    assert held.torque, "still holding"
    bench.guard.stop(registers.BROADCAST_ID, True, bench.now_us)
    assert not held.torque, "stop all lets every servo go"


def test_the_other_series_reads_the_other_way():
    bench = Bench()
    servo = bench.servo(13)
    servo.sc = False
    servo.position = 1000
    servo.speed = 3000
    servo.stop_above = 2600
    move = replace(move_to(3000, 0), speed=2000, accel=50, backoff=100)
    bench.guard.move(13, move, bench.now_us)
    bench.run(1500)
    assert bench.state(13) == GuardState.STALLED
    assert abs(bench.report(13).mark - 2600) <= 2
    assert servo.goal == 2500, "STS backed off"


def test_more_servos_than_slots_are_refused_only_while_all_move():
    bench = Bench()
    for servo_id in range(20, 20 + SLOTS + 1):
        bench.servo(servo_id).position = 100
        bench.servo(servo_id).speed = 50
    for servo_id in range(20, 20 + SLOTS):
        bench.guard.move(servo_id, move_to(900), bench.now_us)
    extra = 20 + SLOTS
    with pytest.raises(GuardFull):
        bench.guard.move(extra, move_to(900), bench.now_us)
    bench.guard.stop(20, True, bench.now_us)
    bench.guard.move(extra, move_to(900), bench.now_us)
    # All eight are read in turn: none starves.
    bench.run(100)
    for servo_id in range(21, extra + 1):
        assert bench.report(servo_id).position > 100, f"servo {servo_id} is read"


def test_the_payloads_parse_as_documented():
    move_bytes = bytes([0x03, 0x34, 0x02, 0xE8, 0x03, 0x00, 0x00, 0x07, 0x90, 0x01, 0x96, 0x00, 3, 8, 30, 0, 0xA0, 0x0F])
    move = GuardMove.unpack(move_bytes)
    assert (move.flags, move.goal, move.time_ms, move.speed, move.accel) == (3, 0x234, 1000, 0, 7)
    assert (move.stall_load, move.stall_ms, move.flat, move.arrived, move.backoff, move.timeout_ms) == (
        400,
        150,
        3,
        8,
        30,
        4000,
    )
    probe = GuardProbe.unpack(bytes([0x01, 0xFF, 3, 20, 0x00, 0x00, 12, 0, 0xBC, 0x02, 15, 0]))
    assert (probe.direction, probe.step, probe.period_ms, probe.limit, probe.lag, probe.load, probe.backoff) == (
        -1,
        3,
        20,
        0,
        12,
        700,
        15,
    )
    packed = GuardReport(GuardState.STALLED, 520, -431, 519, 1000, 345).pack()
    assert len(packed) == 11
    assert (packed[0], packed[1], packed[2], packed[3], packed[4], packed[9], packed[10]) == (
        3,
        0x08,
        0x02,
        0x51,
        0xFE,
        0x59,
        0x01,
    )
