"""A servo bus on a USB serial adapter: raw Feetech packets over a serial port.

The adapter only carries bytes (1 Mbps, half duplex), so there is no board to
watch a moving servo. This link runs the board's guard itself (`guard.py`) on a
thread of its own, ticking every couple of milliseconds, so `move`, `probe`,
`state` and `stop` behave as they do through a control board. The thread and
direct calls share one lock: one conversation on the bus at a time.

Some adapters hear what they send (their transmit and receive share the line)
and some do not. By default an exact copy of the request in front of the reply
is taken to be that echo; `echo=True` requires it, `echo=False` expects none.

Packets (Feetech's protocol manual): FF FF ID LEN INSTRUCTION PARAMS... CHECKSUM,
LEN being the parameters plus two, the checksum the inverted low byte of the sum
from ID on. A reply carries the servo's status byte where a request carries its
instruction.
"""

from __future__ import annotations

import threading
import time

import serial

from . import registers
from .guard import INST_PING, INST_READ, INST_WRITE, MAX_DATA, ServoGuard
from .link import (
    GarbledReply,
    GuardMove,
    GuardProbe,
    GuardReport,
    LineStuck,
    LinkDown,
    NoReply,
    ServoLink,
)

BAUDRATE = 1_000_000
HEADER = b"\xff\xff"
PACKET_OVERHEAD = 6  # FF FF ID LEN INSTRUCTION/STATUS CHECKSUM


def checksum(body: bytes) -> int:
    return (~sum(body)) & 0xFF


def instruction_packet(servo_id: int, instruction: int, params: bytes = b"") -> bytes:
    body = bytes([servo_id, len(params) + 2, instruction]) + bytes(params)
    return HEADER + body + bytes([checksum(body)])


def status_packet(servo_id: int, status: int, data: bytes = b"") -> bytes:
    """What a servo sends back (the same shape as a request)."""
    return instruction_packet(servo_id, status, data)


def reply_length(buffer: bytes) -> int | None:
    """How many bytes the packet at the start of `buffer` takes, once its header
    and length have arrived; None before that. Leading bytes before the header
    and extra FF bytes after it count toward the length."""
    start = buffer.find(HEADER)
    if start < 0:
        return None
    index = start + 2
    while index < len(buffer) and buffer[index] == 0xFF:
        index += 1
    if index + 1 >= len(buffer):
        return None
    return index + 2 + buffer[index + 1]


def parse_reply(buffer: bytes, servo_id: int, data_len: int) -> tuple[int, bytes]:
    """The status byte and data of one servo's reply, read the way the board's
    firmware reads it (ServoBus::receive). Nothing at all is NoReply; bytes that
    are not this servo's packet with `data_len` data bytes are GarbledReply."""
    if not buffer:
        raise NoReply(f"No reply from servo {servo_id}")
    garbled = GarbledReply(f"Garbled reply from servo {servo_id}")
    start = buffer.find(HEADER)
    if start < 0:
        raise garbled
    index = start + 2
    while index < len(buffer) and buffer[index] == 0xFF:
        index += 1
    end = index + 2 + data_len + 2
    if len(buffer) < end:
        raise garbled
    reply_id, length, status = buffer[index], buffer[index + 1], buffer[index + 2]
    if length != data_len + 2:
        raise garbled
    data = bytes(buffer[index + 3 : index + 3 + data_len])
    if buffer[index + 3 + data_len] != checksum(bytes([reply_id, length, status]) + data):
        raise garbled
    if reply_id != servo_id and servo_id != registers.BROADCAST_ID:
        raise garbled
    return status, data


class _PortWire:
    """One instruction and its answer on the port. The caller holds the lock."""

    def __init__(self, port: serial.Serial, *, echo: bool | None, reply_timeout_s: float, byte_timeout_s: float):
        self._port = port
        self._echo = echo
        self._reply_timeout_s = reply_timeout_s
        self._byte_timeout_s = byte_timeout_s

    def transact(self, servo_id: int, instruction: int, params: bytes, data_len: int) -> tuple[int, bytes]:
        packet = instruction_packet(servo_id, instruction, params)
        try:
            self._port.reset_input_buffer()
            self._port.write(packet)
            self._port.flush()
            if self._echo:
                self._take_echo(servo_id, packet)
            if servo_id == registers.BROADCAST_ID and instruction == INST_WRITE:
                if self._echo is None:
                    time.sleep(self._byte_timeout_s)  # let an echo arrive, to be dropped next time
                return 0, b""
            buffer = self._read_reply(b"")
            if self._echo is None and buffer.startswith(packet):
                buffer = self._read_reply(buffer[len(packet) :])
        except (serial.SerialException, OSError, TypeError, AttributeError) as exc:
            # pyserial raises TypeError or AttributeError from a port closed under it.
            raise LinkDown(f"The servo adapter failed: {exc}") from exc
        return parse_reply(buffer, servo_id, data_len)

    def _take_echo(self, servo_id: int, packet: bytes) -> None:
        heard = bytearray()
        give_up_at = time.monotonic() + self._reply_timeout_s + len(packet) * self._byte_timeout_s
        while len(heard) < len(packet) and time.monotonic() < give_up_at:
            heard += self._port.read(len(packet) - len(heard))
        if bytes(heard) != packet:
            raise LineStuck(f"Servo bus line is stuck (servo {servo_id})")

    def _read_reply(self, start: bytes) -> bytes:
        """Every byte of one reply, after `start`: nothing if the first does not
        come in time, else until the packet is whole or the bytes stop coming."""
        buffer = bytearray(start)
        give_up_at = time.monotonic() + self._reply_timeout_s
        while not buffer:
            buffer += self._port.read(max(1, self._port.in_waiting))
            if not buffer and time.monotonic() >= give_up_at:
                return b""
        last_byte_at = time.monotonic()
        while True:
            wanted = reply_length(buffer)
            if wanted is not None and len(buffer) >= wanted:
                return bytes(buffer)
            chunk = self._port.read(max(1, self._port.in_waiting))
            now = time.monotonic()
            if chunk:
                buffer += chunk
                last_byte_at = now
            elif now - last_byte_at >= self._byte_timeout_s:
                return bytes(buffer)


class AdapterServoLink(ServoLink):
    label = "servo adapter"

    def __init__(
        self,
        port: str,
        *,
        baudrate: int = BAUDRATE,
        echo: bool | None = None,
        reply_timeout_s: float = 0.03,
        byte_timeout_s: float = 0.005,
        tick_s: float = 0.002,
    ):
        """`reply_timeout_s` is how long silence lasts before it is NoReply. USB
        adapters add their own latency (an FTDI chip waits up to 16 ms by default),
        so it is longer than the board's 2 ms."""
        try:
            self._port = serial.Serial(port, baudrate=baudrate, timeout=0.002, exclusive=True)
        except (serial.SerialException, OSError) as exc:
            raise LinkDown(f"The servo adapter could not be opened: {exc}") from exc
        self._lock = threading.Lock()
        self._wire = _PortWire(self._port, echo=echo, reply_timeout_s=reply_timeout_s, byte_timeout_s=byte_timeout_s)
        self._guard = ServoGuard(self._wire)
        self._tick_s = tick_s
        self._closing = threading.Event()
        self._thread = threading.Thread(target=self._watch, name="servo-guard", daemon=True)
        self._thread.start()

    @staticmethod
    def _now_us() -> int:
        return (time.monotonic_ns() // 1000) & 0xFFFFFFFF

    def _watch(self) -> None:
        while not self._closing.is_set():
            with self._lock:
                if self._closing.is_set():
                    return
                self._guard.tick(self._now_us())
            self._closing.wait(self._tick_s)

    def _transact(self, servo_id: int, instruction: int, params: bytes, data_len: int) -> tuple[int, bytes]:
        with self._lock:
            if self._closing.is_set():
                raise LinkDown("The servo adapter link is closed.")
            return self._wire.transact(servo_id, instruction, params, data_len)

    def ping(self, servo_id: int) -> int:
        return self._transact(servo_id, INST_PING, b"", 0)[0]

    def read(self, servo_id: int, address: int, count: int) -> tuple[int, bytes]:
        if not 1 <= count <= MAX_DATA:
            raise ValueError(f"A read takes 1 to {MAX_DATA} bytes, not {count}.")
        return self._transact(servo_id, INST_READ, bytes([address, count]), count)

    def write(self, servo_id: int, address: int, data: bytes) -> None:
        if not 1 <= len(data) <= MAX_DATA:
            raise ValueError(f"A write takes 1 to {MAX_DATA} bytes, not {len(data)}.")
        with self._lock:
            if self._closing.is_set():
                raise LinkDown("The servo adapter link is closed.")
            # A servo the host writes to itself is no longer the guard's to judge.
            self._guard.forget(servo_id)
            self._wire.transact(servo_id, INST_WRITE, bytes([address]) + bytes(data), 0)

    def move(self, servo_id: int, move: GuardMove) -> None:
        with self._lock:
            self._guard.move(servo_id, move, self._now_us())

    def probe(self, servo_id: int, probe: GuardProbe) -> None:
        with self._lock:
            self._guard.probe(servo_id, probe, self._now_us())

    def state(self, servo_id: int) -> GuardReport:
        with self._lock:
            return self._guard.report(servo_id, self._now_us())

    def stop(self, servo_id: int, *, release: bool) -> None:
        if servo_id == registers.BROADCAST_ID and not release:
            raise ValueError("Every servo at once can only be let go, not held.")
        with self._lock:
            self._guard.stop(servo_id, release, self._now_us())

    def close(self) -> None:
        self._closing.set()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        with self._lock:
            try:
                self._port.close()
            except Exception:
                pass
