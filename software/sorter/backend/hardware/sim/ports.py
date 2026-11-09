"""Pseudo-terminals the host opens as if they were serial ports.

`BoardPort` carries the host framing to the pretend firmware and its replies
back. `AdapterPort` is a pretend USB servo adapter: raw Feetech packets to and
from a servo line, optionally hearing (echoing) what the host sends, as an
adapter whose transmit and receive share the line does.

Each keeps its own end of the terminal open, so the host can open and close
the port as often as it likes. A stable symlink can point at it.
"""

from __future__ import annotations

import os
import select
import sys
import threading
import time
import traceback
import tty
from pathlib import Path
from typing import Callable

from . import framing
from .firmware import Firmware
from .servos import ServoBus
from .world import World

# A packet the adapter has half heard is dropped after this long, as a servo
# drops one whose bytes stop coming.
PACKET_GAP_S = 0.02


class PseudoTerminal:
    def __init__(self, name: str, link: str | None = None):
        self.name = name
        self._master, self._slave = os.openpty()
        tty.setraw(self._slave)
        self.path = os.ttyname(self._slave)
        self.link = link
        if link is not None:
            _point(Path(link), self.path)
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, on_bytes: Callable[[bytes], None]) -> None:
        self._thread = threading.Thread(target=self._serve, args=(on_bytes,), name=f"sim-{self.name}", daemon=True)
        self._thread.start()

    def _serve(self, on_bytes: Callable[[bytes], None]) -> None:
        while not self._stopping.is_set():
            ready, _, _ = select.select([self._master], [], [], 0.05)
            data = b""  # nothing came: the callee can drop a half-heard packet
            if ready:
                try:
                    data = os.read(self._master, 4096)
                except OSError:
                    time.sleep(0.01)  # no reader on the other end for a moment
                    continue
            try:
                on_bytes(data)
            except Exception:
                # A fault in the pretend board is reported, and it keeps serving.
                traceback.print_exc(file=sys.stderr)

    def send(self, data: bytes) -> None:
        if data:
            os.write(self._master, data)

    def close(self) -> None:
        self._stopping.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if self.link is not None:
            link = Path(self.link)
            try:
                if link.is_symlink() and os.readlink(link) == self.path:
                    link.unlink()
            except OSError:
                pass
        for fd in (self._master, self._slave):
            try:
                os.close(fd)
            except OSError:
                pass


def _point(link: Path, target: str) -> None:
    """Make `link` a symlink to `target`, replacing an older symlink there."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() and not link.is_symlink():
        raise FileExistsError(f"{link} exists and is not a symlink; not replacing it.")
    temporary = link.with_name(f".{link.name}.{os.getpid()}")
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(target)
    os.replace(temporary, link)


class BoardPort:
    """The board's USB or header UART: host frames in, replies out."""

    def __init__(self, firmware: Firmware, link: str | None = None):
        self.firmware = firmware
        self.terminal = PseudoTerminal("board", link)
        self._reader = framing.FrameReader()

    @property
    def path(self) -> str:
        return self.terminal.path

    def start(self) -> None:
        self.terminal.start(self._on_bytes)

    def _on_bytes(self, data: bytes) -> None:
        for frame in self._reader.feed(data):
            message = framing.decode(frame)
            if message is None:
                continue
            reply = self.firmware.handle(message)
            if reply is not None:
                self.terminal.send(framing.encode(reply))

    def close(self) -> None:
        self.terminal.close()


class AdapterPort:
    """A USB serial adapter on a servo line: Feetech packets in, the line's answer out."""

    def __init__(self, world: World, bus: ServoBus, *, echo: bool = False, link: str | None = None):
        self.world = world
        self.bus = bus
        self.echo = echo
        self.terminal = PseudoTerminal("adapter", link)
        self._buffer = bytearray()
        self._last_byte_at = 0.0

    @property
    def path(self) -> str:
        return self.terminal.path

    def start(self) -> None:
        self.terminal.start(self._on_bytes)

    def _on_bytes(self, data: bytes) -> None:
        now = time.monotonic()
        if not data:
            if self._buffer and now - self._last_byte_at > PACKET_GAP_S:
                self._buffer.clear()
            return
        if self.echo:
            self.terminal.send(data)
        if self._buffer and now - self._last_byte_at > PACKET_GAP_S:
            self._buffer.clear()
        self._last_byte_at = now
        self._buffer += data
        while True:
            packet = self._take_packet()
            if packet is None:
                return
            with self.world.lock:
                reply = self.bus.exchange(packet)
            self.terminal.send(reply)

    def _take_packet(self) -> bytes | None:
        buffer = self._buffer
        start = buffer.find(b"\xff\xff")
        if start < 0:
            del buffer[: max(0, len(buffer) - 1)]
            return None
        index = start + 2
        while index < len(buffer) and buffer[index] == 0xFF:
            index += 1
        if index + 1 >= len(buffer):
            return None
        end = index + 2 + buffer[index + 1]
        if len(buffer) < end:
            return None
        packet = b"\xff\xff" + bytes(buffer[index:end])
        del buffer[:end]
        return packet

    def close(self) -> None:
        self.terminal.close()
