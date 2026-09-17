"""MCUBus must read a whole reply that has arrived, however slowly its thread runs.

The MCU writes each reply with a single write, so its bytes normally arrive
together. The old read went byte by byte against one 100 ms deadline. A busy
backend paid several ms per call waiting for the CPU and the GIL, cut intact
replies short ("Partial response (missing terminator)"), then retried,
re-sending commands the MCU had already executed.
"""

from __future__ import annotations

import struct
import time
from threading import Lock
from zlib import crc32

import pytest
from serial.serialutil import SerialBase

from hardware import cobs
from hardware.bus import MCUBus, MCUBusError

GET_STALL_STATUS = 0x1B


def _frame(command: int, channel: int, payload: bytes, address: int = 0) -> bytes:
    message = struct.pack("<BBBB", address, command, channel, len(payload)) + payload
    message += struct.pack("<I", crc32(message))
    return bytes(cobs.encode(message)) + b"\x00"


class _ScriptedPort(SerialBase):
    """Stands in for the MCU's CDC port. After each write, the reply becomes
    readable in chunks at the given offsets, and every read call first costs
    ``read_call_s`` (what a GIL-starved thread pays per call)."""

    def __init__(self, chunks, *, read_call_s: float = 0.0, timeout: float = 0.1) -> None:
        super().__init__(timeout=timeout)
        self._chunks = chunks
        self._read_call_s = read_call_s
        self._written_at: float | None = None
        self._consumed = 0
        self.writes: list[bytes] = []

    def _arrived(self) -> bytes:
        if self._written_at is None:
            return b""
        elapsed = time.monotonic() - self._written_at
        return b"".join(chunk for offset_s, chunk in self._chunks if elapsed >= offset_s)

    @property
    def in_waiting(self) -> int:
        return len(self._arrived()) - self._consumed

    def reset_input_buffer(self) -> None:
        self._consumed = len(self._arrived())

    def write(self, data) -> int:
        self.writes.append(bytes(data))
        self._written_at = time.monotonic()
        self._consumed = 0
        return len(data)

    def read(self, size: int = 1) -> bytes:
        if self._read_call_s:
            time.sleep(self._read_call_s)
        deadline = time.monotonic() + (self.timeout or 0.0)
        while self.in_waiting < size and time.monotonic() < deadline:
            time.sleep(0.001)
        data = self._arrived()[self._consumed : self._consumed + size]
        self._consumed += len(data)
        return data


def _mkBus(port: _ScriptedPort) -> MCUBus:
    bus = MCUBus.__new__(MCUBus)
    bus._serial = port
    bus._lock = Lock()
    bus._port = "scripted"
    return bus


def test_whole_reply_is_read_even_when_each_read_call_is_slow() -> None:
    reply = _frame(GET_STALL_STATUS, 0, b"\x00")
    assert len(reply) == 11
    port = _ScriptedPort([(0.002, reply)], read_call_s=0.015)

    message = _mkBus(port).send_command(0, GET_STALL_STATUS, 0, b"")

    assert message.command == GET_STALL_STATUS
    assert message.payload == b"\x00"
    assert len(port.writes) == 1  # no retry, so the command reached the MCU once


def test_reply_split_across_transfers_is_reassembled() -> None:
    reply = _frame(GET_STALL_STATUS, 0, b"\x05")
    port = _ScriptedPort([(0.002, reply[:4]), (0.05, reply[4:])])

    message = _mkBus(port).send_command(0, GET_STALL_STATUS, 0, b"")

    assert message.payload == b"\x05"
    assert len(port.writes) == 1


def test_trailing_terminators_after_the_frame_are_ignored() -> None:
    reply = _frame(GET_STALL_STATUS, 0, b"\x01") + b"\x00\x00"
    port = _ScriptedPort([(0.002, reply)])

    message = _mkBus(port).send_command(0, GET_STALL_STATUS, 0, b"")

    assert message.payload == b"\x01"


def test_silent_mcu_still_times_out() -> None:
    port = _ScriptedPort([])
    started = time.monotonic()

    with pytest.raises(MCUBusError, match="Timeout waiting for response terminator"):
        _mkBus(port).send_command(0, GET_STALL_STATUS, 0, b"", retries=0)

    assert time.monotonic() - started < 0.5


def test_reply_that_never_finishes_is_reported_as_partial() -> None:
    reply = _frame(GET_STALL_STATUS, 0, b"\x00")
    port = _ScriptedPort([(0.002, reply[:6])])

    with pytest.raises(MCUBusError, match="Partial response"):
        _mkBus(port).send_command(0, GET_STALL_STATUS, 0, b"", retries=0)
