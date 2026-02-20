"""Consistent Overhead Byte Stuffing (COBS) encoding and decoding functions."""

# Copyright (c) 2017-2026 Jose I. Romero
#
# Licensed under the MIT License. See LICENSE file in the project root for full license information.


class DecodeError(Exception):
    """Raised when a COBS packet cannot be decoded."""

    pass


def encode(message: bytearray) -> bytearray:
    """Encode a message using COBS."""
    outbuf = bytearray(b"\x01")
    counter_idx = 0
    for mb in message:
        if mb == 0:
            counter_idx = len(outbuf)
        outbuf.append(mb)
        outbuf[counter_idx] += 1
    return outbuf


def decode(buff: bytearray) -> bytearray:
    """Decode a COBS-encoded message."""
    msgbuf = bytearray()
    s = buff.pop(0)
    while buff:
        c = buff.pop(0)
        if c == 0:
            raise DecodeError("Packet contains zeroes")
        if s == 1:
            msgbuf.append(0)
            s = c
        else:
            msgbuf.append(c)
            s -= 1
    if s > 1:
        raise DecodeError("Corrupted count")

    return msgbuf
