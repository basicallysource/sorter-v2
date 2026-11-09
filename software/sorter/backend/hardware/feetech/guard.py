"""The guard a control board runs in its firmware, in Python.

A faithful port of the firmware's `ServoGuard.cpp`: the same states, decisions,
constants and timing, with names kept parallel so the two can be read side by
side. It is for links that have no board to run it (a USB adapter), and for a
pretend board.

The guard talks to servos through a wire (`ServoWire`): one instruction to one
servo and its answer, raising `NoReply`, `GarbledReply` or `LineStuck` from
`link.py` when no good answer came. Time comes in as microseconds, an argument
to every call, and wraps at 32 bits as the board's clock does.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from . import registers
from .link import (
    FLAG_RELEASE_AFTER_BACKOFF,
    FLAG_RELEASE_ON_ARRIVAL,
    FLAG_SC,
    GuardFull,
    GuardMove,
    GuardProbe,
    GuardReport,
    GuardState,
    ServoLinkError,
)

INST_PING = 0x01
INST_READ = 0x02
INST_WRITE = 0x03
MAX_DATA = 64  # most data bytes in one read or write


class ServoWire(Protocol):
    def transact(self, servo_id: int, instruction: int, params: bytes, data_len: int) -> tuple[int, bytes]:
        """Send one instruction and return the servo's status byte and `data_len`
        data bytes. A write to `registers.BROADCAST_ID` waits for no answer and
        returns status 0. Raises NoReply, GarbledReply or LineStuck."""
        ...


SLOTS = 8  # servos watched at once

# Registers both Feetech series share. They differ in byte order, in the range of
# a position, and in how a goal is written.
REG_TORQUE = registers.TORQUE
REG_STS_GOAL = registers.STS_GOAL  # acceleration, then position, time and speed
REG_SC_GOAL = registers.SC_GOAL  # position, time and speed
REG_PRESENT = registers.PRESENT  # position, speed and load, two bytes each
PRESENT_BYTES = 6
STATUS_OVERLOAD = registers.STATUS_OVERLOAD

SC_MAX_RAW = 1023
STS_MAX_RAW = 4095

SAMPLE_PERIOD_US = 10_000
LOST_AFTER_MISSES = 3
# A back-off's time to finish before the servo is let go.
RELEASE_DELAY_US = 250_000
# Samples in a row that must say a probing servo is held: one alone can be its
# own start-up friction.
PROBE_HELD_SAMPLES = 2
# Periods a probe waits at its limit for the servo to catch up or be held.
PROBE_SETTLE_SAMPLES = 10
PROBE_SHORTEST_PERIOD_US = 5_000

_U32 = 0xFFFFFFFF


def _u32(value: int) -> int:
    return value & _U32


def _reached(now_us: int, when_us: int) -> bool:
    """`(int32_t)(now_us - when_us) >= 0`: true across the 32-bit wrap."""
    return _u32(now_us - when_us) < 0x80000000


def _get16(data: bytes) -> int:
    return data[0] | (data[1] << 8)


@dataclass
class _Slot:
    used: bool = False
    id: int = 0
    state: GuardState = GuardState.IDLE
    flags: int = 0
    goal: int = 0
    start: int = 0
    position: int = 0
    load: int = 0
    mark: int = 0
    peak_load: int = 0
    stall_load: int = 0
    backoff: int = 0
    flat: int = 0
    arrived: int = 0
    misses: int = 0
    stall_us: int = 0
    timeout_us: int = 0
    stall_ref: int = 0
    stall_timing: bool = False
    stall_since_us: int = 0
    began_us: int = 0
    ended_us: int = 0
    next_sample_us: int = 0
    release_pending: bool = False
    release_at_us: int = 0
    # A probe
    direction: int = 0
    step: int = 0
    period_us: int = 0
    limit: int = 0
    lag: int = 0
    held_samples: int = 0
    at_limit_samples: int = 0


class ServoGuard:
    """Watches serial bus servos while they move, and stops one that meets resistance.

    Each servo sent through move() is read every 10 ms; one that is loaded and no
    longer moving, short of its goal, is sent back the way it came and reported
    stalled. probe() finds an end of travel without ever pushing hard: the goal
    creeps a few counts at a time, and the servo is taken to be held as soon as
    it falls behind its goal or its load rises.

    move(), probe() and stop() return nothing, or raise GuardFull or the wire's
    error if the servo did not take it. Not thread safe: the caller keeps one
    conversation on the wire at a time.
    """

    def __init__(self, wire: ServoWire):
        self._wire = wire
        self._slots = [_Slot() for _ in range(SLOTS)]
        self._next_slot = 0

    # -- slots ----------------------------------------------------------------

    @staticmethod
    def _active(slot: _Slot) -> bool:
        return slot.used and slot.state in (GuardState.MOVING, GuardState.PROBING)

    @staticmethod
    def _max_raw(slot: _Slot) -> int:
        return SC_MAX_RAW if slot.flags & FLAG_SC else STS_MAX_RAW

    def _find(self, servo_id: int) -> _Slot | None:
        for slot in self._slots:
            if slot.used and slot.id == servo_id:
                return slot
        return None

    def _claim(self, servo_id: int) -> _Slot | None:
        """The slot a new move of this servo takes: its own if it has one, a free
        one, or one whose servo has finished. A servo still moving, or waiting to
        be let go, keeps its slot."""
        own = self._find(servo_id)
        if own is not None:
            return own
        for slot in self._slots:
            if not slot.used:
                return slot
        for slot in self._slots:
            if not self._active(slot) and not slot.release_pending:
                return slot
        return None

    @staticmethod
    def _reset(slot: _Slot) -> None:
        slot.__dict__.update(_Slot().__dict__)

    # -- the wire -------------------------------------------------------------

    def _read_present(self, slot: _Slot) -> int:
        """Read where the servo is and how hard it is working. Returns the
        status byte; raises the wire's error."""
        status, data = self._wire.transact(slot.id, INST_READ, bytes([REG_PRESENT, PRESENT_BYTES]), PRESENT_BYTES)
        if slot.flags & FLAG_SC:
            position = ((data[0] << 8) | data[1]) & 0x3FF
            load_word = (data[4] << 8) | data[5]
        else:
            position = _get16(data)
            # Bit 15 is the sign, in a multi-turn mode a guarded servo is not in.
            position = 0 if position & 0x8000 else min(position, STS_MAX_RAW)
            load_word = _get16(data[4:6])
        # 0 to 1000, with bit 10 the direction.
        load = load_word & 0x3FF
        if load_word & 0x400:
            load = -load
        slot.position = position
        slot.load = load
        if abs(load) > slot.peak_load:
            slot.peak_load = abs(load)
        return status

    def _write_goal(self, slot: _Slot, position: int, time_ms: int, speed: int, accel: int) -> None:
        if slot.flags & FLAG_SC:
            params = bytes([REG_SC_GOAL]) + position.to_bytes(2, "big") + time_ms.to_bytes(2, "big") + speed.to_bytes(2, "big")
        else:
            params = (
                bytes([REG_STS_GOAL, accel])
                + position.to_bytes(2, "little")
                + (0).to_bytes(2, "little")
                + speed.to_bytes(2, "little")
            )
        self._wire.transact(slot.id, INST_WRITE, params, 0)

    def _write_torque(self, servo_id: int, on: bool) -> None:
        self._wire.transact(servo_id, INST_WRITE, bytes([REG_TORQUE, 1 if on else 0]), 0)

    # The firmware drops the result of these writes: a servo that missed one is
    # read again on the next sample.
    def _write_goal_quietly(self, slot: _Slot, position: int) -> None:
        try:
            self._write_goal(slot, position, 0, 0, 0)
        except ServoLinkError:
            pass

    def _write_torque_quietly(self, servo_id: int, on: bool) -> None:
        try:
            self._write_torque(servo_id, on)
        except ServoLinkError:
            pass

    # -- what the host asks ---------------------------------------------------

    def move(self, servo_id: int, move: GuardMove, now_us: int) -> None:
        """Send a servo to a position and watch it until it gets there or cannot.

        The goal is written before the torque comes on, so a servo that was let
        go starts toward this goal and not toward an older one."""
        now_us = _u32(now_us)
        slot = self._claim(servo_id)
        if slot is None:
            raise GuardFull(f"Servo guard is full (servo {servo_id})")
        self._reset(slot)
        slot.id = servo_id
        slot.flags = move.flags
        self._read_present(slot)
        slot.goal = min(move.goal, self._max_raw(slot))
        self._write_goal(slot, slot.goal, move.time_ms, move.speed, move.accel)
        self._write_torque(servo_id, True)
        slot.used = True
        slot.state = GuardState.MOVING
        slot.start = slot.position
        slot.stall_ref = slot.position
        slot.peak_load = 0
        slot.stall_load = move.stall_load
        slot.stall_us = move.stall_ms * 1000
        slot.flat = move.flat
        slot.arrived = move.arrived
        slot.backoff = move.backoff
        slot.timeout_us = move.timeout_ms * 1000
        slot.began_us = now_us
        slot.next_sample_us = _u32(now_us + SAMPLE_PERIOD_US)

    def probe(self, servo_id: int, probe: GuardProbe, now_us: int) -> None:
        """Creep toward a limit until something holds the servo.

        The torque comes on with the goal where the servo already is, so nothing
        jumps. From there the goal moves one step each period."""
        now_us = _u32(now_us)
        slot = self._claim(servo_id)
        if slot is None:
            raise GuardFull(f"Servo guard is full (servo {servo_id})")
        self._reset(slot)
        slot.id = servo_id
        slot.flags = probe.flags
        self._read_present(slot)
        self._write_goal(slot, slot.position, 0, 0, 0)
        self._write_torque(servo_id, True)
        slot.used = True
        slot.state = GuardState.PROBING
        slot.start = slot.position
        slot.goal = slot.position
        slot.peak_load = 0
        slot.direction = -1 if probe.direction < 0 else 1
        slot.step = 1 if probe.step == 0 else probe.step
        slot.period_us = max(probe.period_ms * 1000, PROBE_SHORTEST_PERIOD_US)
        slot.limit = min(probe.limit, self._max_raw(slot))
        slot.lag = probe.lag
        slot.stall_load = probe.load
        slot.backoff = probe.backoff
        slot.began_us = now_us
        slot.next_sample_us = _u32(now_us + slot.period_us)

    def stop(self, servo_id: int, release: bool, now_us: int) -> None:
        """Stop watching and stop the servo: let it go, or hold it where it is.
        `registers.BROADCAST_ID` is every servo, and only lets go."""
        if servo_id == registers.BROADCAST_ID:
            for slot in self._slots:
                self._reset(slot)
            self._write_torque(registers.BROADCAST_ID, False)
            return
        slot = self._find(servo_id)
        watched = slot is not None
        was = replace(slot) if slot is not None else _Slot()
        if slot is not None:
            self._reset(slot)
        if release:
            self._write_torque(servo_id, False)
            return
        if not watched:
            return  # not moving through the guard: nothing of its to stop
        self._read_present(was)
        self._write_goal(was, was.position, 0, 0, 0)

    def forget(self, servo_id: int) -> None:
        """The host wrote to this servo itself: it is no longer the guard's to judge."""
        for slot in self._slots:
            if servo_id == registers.BROADCAST_ID or (slot.used and slot.id == servo_id):
                self._reset(slot)

    def report(self, servo_id: int, now_us: int) -> GuardReport:
        slot = self._find(servo_id)
        if slot is None:
            return GuardReport(GuardState.IDLE, 0, 0, 0, 0, 0)
        end_us = _u32(now_us) if self._active(slot) else slot.ended_us
        elapsed_ms = _u32(end_us - slot.began_us) // 1000
        return GuardReport(slot.state, slot.position, slot.load, slot.mark, slot.peak_load, min(elapsed_ms, 0xFFFF))

    # -- watching -------------------------------------------------------------

    def _end(self, slot: _Slot, state: GuardState, now_us: int) -> None:
        slot.state = state
        slot.ended_us = now_us
        slot.stall_timing = False
        if state not in (GuardState.ARRIVED, GuardState.LOST) and slot.flags & FLAG_RELEASE_AFTER_BACKOFF:
            slot.release_pending = True
            slot.release_at_us = _u32(now_us + RELEASE_DELAY_US)

    def _back_off(self, slot: _Slot, toward: int, state: GuardState, now_us: int) -> None:
        """Send a held servo back the way it came, and say why it ended.
        `toward` is +1 or -1: the direction away from what holds it."""
        target = slot.position + toward * slot.backoff
        # A move never backs off past where it began.
        if state == GuardState.STALLED and slot.start != slot.position:
            if (toward > 0 and target > slot.start) or (toward < 0 and target < slot.start):
                target = slot.start
        target = max(0, min(self._max_raw(slot), target))
        slot.mark = slot.position
        self._write_goal_quietly(slot, target)
        self._end(slot, state, now_us)

    def _hold_here(self, slot: _Slot, state: GuardState, now_us: int) -> None:
        self._write_goal_quietly(slot, slot.position)
        self._end(slot, state, now_us)

    def _sample_move(self, slot: _Slot, now_us: int) -> None:
        try:
            status = self._read_present(slot)
        except ServoLinkError:
            slot.misses += 1
            if slot.misses >= LOST_AFTER_MISSES:
                self._end(slot, GuardState.LOST, now_us)
            return
        slot.misses = 0
        if abs(slot.position - slot.goal) <= slot.arrived:
            self._end(slot, GuardState.ARRIVED, now_us)
            if slot.flags & FLAG_RELEASE_ON_ARRIVAL:
                self._write_torque_quietly(slot.id, False)
            return
        # The servo's own overload flag is a stall already. Short of that: loaded
        # and not moving for long enough.
        held = bool(status & STATUS_OVERLOAD)
        loaded = abs(slot.load) >= slot.stall_load
        still = abs(slot.position - slot.stall_ref) < slot.flat
        if loaded and still:
            if not slot.stall_timing:
                slot.stall_timing = True
                slot.stall_since_us = now_us
            elif _reached(now_us, slot.stall_since_us + slot.stall_us):
                held = True
        else:
            slot.stall_timing = False
            slot.stall_ref = slot.position
        if held:
            if slot.start != slot.position:
                toward = 1 if slot.start > slot.position else -1
            else:
                toward = -1 if slot.goal > slot.position else 1
            self._back_off(slot, toward, GuardState.STALLED, now_us)
            return
        if slot.timeout_us != 0 and _reached(now_us, slot.began_us + slot.timeout_us):
            self._hold_here(slot, GuardState.TIMED_OUT, now_us)

    def _sample_probe(self, slot: _Slot, now_us: int) -> None:
        try:
            status = self._read_present(slot)
        except ServoLinkError:
            slot.misses += 1
            if slot.misses >= LOST_AFTER_MISSES:
                self._end(slot, GuardState.LOST, now_us)
            return
        slot.misses = 0
        # Held: behind its creeping goal by more than a free servo ever is, or
        # working hard. Either can come first, depending on what holds it.
        behind = slot.goal - slot.position if slot.direction > 0 else slot.position - slot.goal
        behind = max(0, behind)
        held = (
            bool(status & STATUS_OVERLOAD)
            or behind >= slot.lag
            or (slot.stall_load != 0 and abs(slot.load) >= slot.stall_load)
        )
        slot.held_samples = slot.held_samples + 1 if held else 0
        if slot.held_samples >= PROBE_HELD_SAMPLES:
            self._back_off(slot, -slot.direction, GuardState.CONTACT, now_us)
            return
        if slot.goal == slot.limit:
            slot.at_limit_samples += 1
            if slot.at_limit_samples >= PROBE_SETTLE_SAMPLES:
                self._hold_here(slot, GuardState.NO_CONTACT, now_us)
            return
        next_goal = slot.goal + slot.direction * slot.step
        if (slot.direction > 0 and next_goal > slot.limit) or (slot.direction < 0 and next_goal < slot.limit):
            next_goal = slot.limit
        slot.goal = next_goal
        self._write_goal_quietly(slot, slot.goal)

    def tick(self, now_us: int) -> None:
        """Call often. Reads at most one servo a call."""
        now_us = _u32(now_us)
        for offset in range(SLOTS):
            index = (self._next_slot + offset) % SLOTS
            slot = self._slots[index]
            if not slot.used:
                continue
            if slot.release_pending and _reached(now_us, slot.release_at_us):
                slot.release_pending = False
                self._write_torque_quietly(slot.id, False)
            elif self._active(slot) and _reached(now_us, slot.next_sample_us):
                if slot.state == GuardState.PROBING:
                    slot.next_sample_us = _u32(now_us + slot.period_us)
                    self._sample_probe(slot, now_us)
                else:
                    slot.next_sample_us = _u32(now_us + SAMPLE_PERIOD_US)
                    self._sample_move(slot, now_us)
            else:
                continue
            self._next_slot = (index + 1) % SLOTS
            return
