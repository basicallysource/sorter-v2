"""The board's side of the host framing (the firmware's message.cpp).

A message is a 4-byte header (address, command, channel, payload length), the
payload and a CRC32 of both, COBS encoded and ended by a 0x00 byte. The host's
side of the same framing is `hardware/bus.py`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from zlib import crc32

from hardware import cobs

MAX_PAYLOAD_SIZE = 254 - 4 - 4  # the firmware's MAX_PAYLOAD_SIZE
RX_BUFFER_SIZE = 255  # the firmware's rx_buffer


@dataclass(frozen=True)
class Message:
    address: int
    command: int
    channel: int
    payload: bytes


def decode(encoded: bytes) -> Message | None:
    """One received frame (without its 0x00), or None where the firmware drops
    it silently: too short, a framing error or a CRC error."""
    if len(encoded) < 8:
        return None
    try:
        raw = bytes(cobs.decode(encoded))
    except (cobs.DecodeError, IndexError):
        return None
    if len(raw) < 8:
        return None
    body, crc = raw[:-4], struct.unpack("<I", raw[-4:])[0]
    if crc32(body) != crc:
        return None
    address, command, channel, length = body[0], body[1], body[2], body[3]
    return Message(address, command, channel, body[4 : 4 + length])


def encode(message: Message) -> bytes:
    body = bytes([message.address, message.command, message.channel, len(message.payload)]) + message.payload
    body += struct.pack("<I", crc32(body))
    return bytes(cobs.encode(body)) + b"\x00"


class FrameReader:
    """Splits the byte stream from the host into frames at each 0x00."""

    def __init__(self):
        self._buffer = bytearray()
        self._overflowed = False

    def feed(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        for byte in data:
            if byte == 0:
                if not self._overflowed:
                    frames.append(bytes(self._buffer))
                self._buffer.clear()
                self._overflowed = False
            elif len(self._buffer) < RX_BUFFER_SIZE:
                self._buffer.append(byte)
            else:
                # The firmware drops a frame that outgrows its buffer.
                self._buffer.clear()
                self._overflowed = True
        return frames
