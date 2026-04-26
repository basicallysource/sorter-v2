#!/usr/bin/env python3
"""Grab one preview frame from a sorter camera and save it as JPEG.

Connects to the backend's ``/ws/camera-preview/{index}`` websocket,
receives the first binary frame (already JPEG-encoded), and writes it
to disk. Used by operator scripts and by Claude during live tests to
visually verify tray state without opening a browser.

Camera index map (current default config):

* ``0``: classification chamber / C4 (Insta360 Link 2)
* ``1``: c_channel_3 (5MP USB)
* ``2``: c_channel_2 (USB-Kamera)

The exact mapping is in ``/api/cameras/config``.

Usage::

    uv run --with websockets python scripts/grab_camera_frame.py 0 /tmp/c4.jpg
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import websockets


DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_ORIGIN = "http://127.0.0.1:5173"
DEFAULT_TIMEOUT_S = 10.0


async def grab(
    index: int,
    out_path: Path,
    *,
    host: str = DEFAULT_BACKEND_HOST,
    port: int = DEFAULT_BACKEND_PORT,
    origin: str = DEFAULT_ORIGIN,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> int:
    uri = f"ws://{host}:{port}/ws/camera-preview/{index}"
    async with websockets.connect(uri, origin=origin) as ws:
        frame = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
    if isinstance(frame, str):
        frame = frame.encode()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(frame)
    return len(frame)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("index", type=int, help="Camera index (0=classification_channel, 1=c3, 2=c2).")
    parser.add_argument("out", type=Path, help="Output JPEG path.")
    parser.add_argument("--host", default=DEFAULT_BACKEND_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        n = asyncio.run(
            grab(
                args.index,
                args.out,
                host=args.host,
                port=args.port,
                origin=args.origin,
                timeout_s=args.timeout_s,
            )
        )
    except Exception as exc:
        print(f"grab_camera_frame: {exc}", file=sys.stderr)
        return 1
    print(f"saved {n} bytes to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
