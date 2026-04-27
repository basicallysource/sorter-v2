#!/usr/bin/env python3
"""Capture a batch of C4 camera frames for wall-detector training.

Drives the C4 platter through a slow continuous rotation via the
existing ``sample_transport`` maintenance path while pulling frames
off the ``/ws/camera-preview/0`` websocket every few hundred
milliseconds. The result is a directory of timestamped JPEGs at
varied platter rotations — exactly what
``scripts/wall_detector_collect.py`` expects as input.

The script handles its own safety checks so it can be run unattended
during the rotor install:

* refuses to start if hardware isn't ``ready`` (no homed → no run)
* sets ``c1.feed_inhibit = true`` for the duration so no LEGO pieces
  enter the line and obscure the walls
* cancels the in-flight ``sample_transport`` when interrupted
  (Ctrl-C or wall-clock timeout) before exiting

Usage::

    uv run --with websockets python scripts/wall_detector_capture.py \\
        --output-dir captures/c4_walls_2026-04-27 \\
        --duration-s 90 \\
        --frame-period-s 0.5 \\
        --c4-rpm 1.0

After the capture, hand the output directory to
``scripts/wall_detector_collect.py`` for Gemini-based YOLO labeling.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

import websockets


DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = 8000
DEFAULT_ORIGIN = "http://127.0.0.1:5173"
DEFAULT_DURATION_S = 90.0
DEFAULT_FRAME_PERIOD_S = 0.5
DEFAULT_C4_RPM = 1.0
DEFAULT_BASE_INTERVAL_S = 2.0
DEFAULT_C4_CAMERA_INDEX = 0    # ``classification_channel`` per cameras/config


def _http_post_json(url: str, payload: dict[str, Any], origin: str, *, timeout: float = 5.0) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Origin": origin},
    )
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw or b"{}")


def _http_get_json(url: str, *, timeout: float = 3.0) -> dict[str, Any]:
    with urllib_request.urlopen(url, timeout=timeout) as resp:
        raw = resp.read()
    return json.loads(raw or b"{}")


@contextmanager
def _hold_c1_feed_inhibit(*, host: str, port: int, origin: str):
    """Set ``c1.feed_inhibit = true`` for the duration of the with-block.

    The capture must not race against new pieces flowing in — we want
    a clean view of the platter walls. The inhibit is restored to its
    prior value when the block exits, success or failure.
    """
    base = f"http://{host}:{port}"
    try:
        snap = _http_get_json(f"{base}/api/rt/tuning")
    except Exception:
        snap = {}
    prior = bool(
        ((snap.get("tuning") or {}).get("channels") or {}).get("c1", {}).get("feed_inhibit", False)
    )

    def _set(value: bool) -> None:
        try:
            _http_post_json(
                f"{base}/api/rt/tuning",
                {"channels": {"c1": {"feed_inhibit": value}}},
                origin=origin,
            )
        except Exception as exc:
            print(f"[capture] feed_inhibit toggle failed: {exc}", file=sys.stderr)

    if not prior:
        _set(True)
    try:
        yield
    finally:
        if not prior:
            _set(False)


def _start_c4_sample_transport(
    *,
    host: str,
    port: int,
    origin: str,
    duration_s: float,
    rpm: float,
    base_interval_s: float,
) -> None:
    payload = {
        "base_interval_s": base_interval_s,
        "channels": ["c4"],
        "channel_rpm": {"c4": rpm},
        "duration_s": duration_s,
    }
    _http_post_json(
        f"http://{host}:{port}/api/rt/sample-transport",
        payload,
        origin=origin,
    )


def _cancel_c4_sample_transport(*, host: str, port: int, origin: str) -> None:
    try:
        _http_post_json(
            f"http://{host}:{port}/api/rt/sample-transport/cancel",
            {},
            origin=origin,
        )
    except Exception as exc:
        print(f"[capture] sample_transport cancel failed: {exc}", file=sys.stderr)


def _hardware_ready(host: str, port: int) -> tuple[bool, str]:
    try:
        snap = _http_get_json(f"http://{host}:{port}/api/system/status")
    except Exception as exc:
        return False, f"system status check failed: {exc}"
    state = snap.get("hardware_state")
    if state != "ready":
        return False, f"hardware_state is {state!r} (need 'ready'; home first)"
    return True, "ok"


async def _capture_loop(
    *,
    host: str,
    port: int,
    origin: str,
    camera_index: int,
    duration_s: float,
    frame_period_s: float,
    output_dir: Path,
) -> int:
    uri = f"ws://{host}:{port}/ws/camera-preview/{camera_index}"
    saved = 0
    output_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + duration_s
    next_save = time.monotonic()
    async with websockets.connect(uri, origin=origin) as ws:
        while time.monotonic() < deadline:
            try:
                frame = await asyncio.wait_for(
                    ws.recv(), timeout=max(0.5, frame_period_s * 4.0)
                )
            except asyncio.TimeoutError:
                continue
            if isinstance(frame, str):
                frame = frame.encode()
            now = time.monotonic()
            if now < next_save:
                continue
            next_save = now + frame_period_s
            wall_ts = int(time.time() * 1000)
            target = output_dir / f"c4_{wall_ts}.jpg"
            target.write_bytes(frame)
            saved += 1
            print(f"[capture] {target.name} ({len(frame)} B, total {saved})")
    return saved


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture C4 platter frames for wall-detector training.",
        epilog=(
            "Hand the resulting directory to scripts/wall_detector_collect.py "
            "for Gemini labeling."
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, default=DEFAULT_DURATION_S)
    parser.add_argument("--frame-period-s", type=float, default=DEFAULT_FRAME_PERIOD_S)
    parser.add_argument("--c4-rpm", type=float, default=DEFAULT_C4_RPM)
    parser.add_argument(
        "--base-interval-s",
        type=float,
        default=DEFAULT_BASE_INTERVAL_S,
        help="Sample-transport base step interval (default 2.0s).",
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=DEFAULT_C4_CAMERA_INDEX,
        help=(
            f"Camera index for the C4 view (default {DEFAULT_C4_CAMERA_INDEX} = "
            "classification_channel)."
        ),
    )
    parser.add_argument("--host", default=DEFAULT_BACKEND_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument(
        "--skip-hardware-check",
        action="store_true",
        help=(
            "Bypass the hardware-ready check. Useful for capturing "
            "frames from a recorded backend without homing."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.duration_s <= 0:
        print("--duration-s must be > 0", file=sys.stderr)
        return 1
    if args.frame_period_s <= 0:
        print("--frame-period-s must be > 0", file=sys.stderr)
        return 1

    if not args.skip_hardware_check:
        ok, reason = _hardware_ready(args.host, args.port)
        if not ok:
            print(f"[capture] {reason}", file=sys.stderr)
            return 1

    output_dir: Path = args.output_dir
    started_at = time.time()
    saved = 0
    try:
        with _hold_c1_feed_inhibit(host=args.host, port=args.port, origin=args.origin):
            print(
                f"[capture] starting C4 sample_transport at {args.c4_rpm} rpm "
                f"for {args.duration_s} s; saving frames to {output_dir}"
            )
            _start_c4_sample_transport(
                host=args.host,
                port=args.port,
                origin=args.origin,
                duration_s=args.duration_s,
                rpm=args.c4_rpm,
                base_interval_s=args.base_interval_s,
            )
            try:
                saved = asyncio.run(
                    _capture_loop(
                        host=args.host,
                        port=args.port,
                        origin=args.origin,
                        camera_index=args.camera_index,
                        duration_s=args.duration_s,
                        frame_period_s=args.frame_period_s,
                        output_dir=output_dir,
                    )
                )
            finally:
                _cancel_c4_sample_transport(
                    host=args.host, port=args.port, origin=args.origin
                )
    except KeyboardInterrupt:
        print("[capture] interrupted by user", file=sys.stderr)
        _cancel_c4_sample_transport(host=args.host, port=args.port, origin=args.origin)
    elapsed = time.time() - started_at
    summary = {
        "saved_frames": saved,
        "duration_s": round(elapsed, 2),
        "output_dir": str(output_dir),
        "camera_index": args.camera_index,
        "c4_rpm": args.c4_rpm,
    }
    summary_path = output_dir / "capture_run.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if saved > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
