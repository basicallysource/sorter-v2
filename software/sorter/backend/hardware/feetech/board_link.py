"""The servo bus on a control board, reached through the board's firmware.

The board carries the bytes and runs the guard itself (`SERVO_BUS` in the
firmware's README), so a guarded move keeps being watched while this process is
busy with something else.
"""

from __future__ import annotations

from hardware.bus import MCUBusError, MCUDevice, MCUDeviceError

from . import registers
from .link import (
    GarbledReply,
    GuardFull,
    GuardMove,
    GuardProbe,
    GuardReport,
    LineStuck,
    LinkDown,
    NoReply,
    ServoLink,
    ServoLinkError,
)

PING = 0x50
READ = 0x51
WRITE = 0x52
MOVE = 0x53
STATE = 0x54
PROBE = 0x55
STOP = 0x56

# How the board's refusals begin (the firmware's servo_bus_failed).
_REFUSALS: tuple[tuple[str, type[ServoLinkError]], ...] = (
    ("No reply", NoReply),
    ("Garbled reply", GarbledReply),
    ("Servo bus line is stuck", LineStuck),
    ("Servo guard is full", GuardFull),
)


def _sentence(text: str) -> str:
    """The board's refusal as a sentence: it sends them without a full stop."""
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


class BoardServoLink(ServoLink):
    label = "control board"

    def __init__(self, device: MCUDevice):
        self._device = device

    def _send(self, command: int, servo_id: int, payload: bytes = b"") -> bytes:
        try:
            return self._device.send_command(command, servo_id, payload).payload
        except MCUDeviceError as exc:
            for prefix, error in _REFUSALS:
                if exc.detail.startswith(prefix):
                    raise error(_sentence(exc.detail)) from None
            raise ServoLinkError(_sentence(exc.detail)) from None
        except MCUBusError as exc:
            raise LinkDown(f"The control board did not answer: {exc}") from exc

    def ping(self, servo_id: int) -> int:
        return self._send(PING, servo_id)[0]

    def read(self, servo_id: int, address: int, count: int) -> tuple[int, bytes]:
        reply = self._send(READ, servo_id, bytes([address, count]))
        return reply[0], reply[1 : 1 + count]

    def write(self, servo_id: int, address: int, data: bytes) -> None:
        self._send(WRITE, servo_id, bytes([address]) + bytes(data))

    def move(self, servo_id: int, move: GuardMove) -> None:
        self._send(MOVE, servo_id, move.pack())

    def probe(self, servo_id: int, probe: GuardProbe) -> None:
        self._send(PROBE, servo_id, probe.pack())

    def state(self, servo_id: int) -> GuardReport:
        return GuardReport.unpack(self._send(STATE, servo_id))

    def stop(self, servo_id: int, *, release: bool) -> None:
        if servo_id == registers.BROADCAST_ID and not release:
            raise ValueError("Every servo at once can only be let go, not held.")
        self._send(STOP, servo_id, bytes([1 if release else 0]))
