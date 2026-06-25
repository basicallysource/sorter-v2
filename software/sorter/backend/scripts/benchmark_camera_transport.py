#!/usr/bin/env python3
"""Benchmark legacy camera streaming against RKMPP encoder paths.

The benchmark is intentionally split into two layers:

* ``legacy-app`` opens MJPEG clients against the running Sorter backend and
  measures backend process CPU/RSS while those clients are alive.
* ``ffmpeg-synthetic`` runs equivalent synthetic 720p/1080p encodes through
  FFmpeg to isolate encoder cost without the application stack.
* ``ffmpeg-camera-rkmpp`` is optional and tries to capture a real /dev/videoN
  source with FFmpeg/RKMPP. It will fail cleanly when the backend already owns
  the camera, which is the normal runtime state.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any


DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
BACKEND_SERVICE = "sorter-backend-dev.service"


@dataclass
class StreamClientResult:
    index: int
    url: str
    connected: bool = False
    bytes_read: int = 0
    error: str | None = None
    ready: threading.Event = field(default_factory=threading.Event)


def _json_request(url: str, *, timeout_s: float = 5.0) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    return payload if isinstance(payload, dict) else {"ok": False, "error": "non-object JSON"}


def _backend_pid() -> int | None:
    patterns = (
        "/home/orangepi/sorter-v2/software/sorter/backend/main.py",
        "software/sorter/backend/main.py",
    )
    for pattern in patterns:
        try:
            output = subprocess.check_output(["pgrep", "-f", pattern], text=True).strip()
        except Exception:
            continue
        for line in output.splitlines():
            try:
                pid = int(line.strip())
            except ValueError:
                continue
            if pid > 0:
                return pid
    try:
        output = subprocess.check_output(
            ["systemctl", "show", "-p", "MainPID", "--value", BACKEND_SERVICE],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        pid = int(output or "0")
        if pid > 0:
            return pid
    except Exception:
        pass
    return None


def _process_cpu_seconds(pid: int) -> float:
    with open(f"/proc/{pid}/stat", "r", encoding="utf-8") as handle:
        parts = handle.read().split()
    ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
    return float(int(parts[13]) + int(parts[14])) / float(ticks)


def _process_rss_kb(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except OSError:
        return None
    return None


def _stream_url(base_url: str, role: str, *, index: int) -> str:
    params = {
        "annotated": "1",
        "layer": "annotated",
        "dashboard": "1",
        "direct": "0",
        "show_regions": "1",
        "benchmark": f"{int(time.time())}-{index}",
    }
    return (
        f"{base_url.rstrip('/')}/api/cameras/feed/{urllib.parse.quote(role)}?"
        f"{urllib.parse.urlencode(params)}"
    )


def _stream_client(result: StreamClientResult, *, duration_s: float, chunk_size: int) -> None:
    deadline = time.monotonic() + max(0.1, float(duration_s))
    try:
        request = urllib.request.Request(result.url, method="GET")
        with urllib.request.urlopen(request, timeout=5.0) as response:
            result.connected = True
            result.ready.set()
            while time.monotonic() < deadline:
                chunk = response.read(max(1, int(chunk_size)))
                if not chunk:
                    break
                result.bytes_read += len(chunk)
    except Exception as exc:
        result.error = str(exc)
        result.ready.set()


def _legacy_clients_from_media_plane(payload: dict[str, Any]) -> int | None:
    try:
        return int(payload.get("legacy_transports", {}).get("mjpeg", {}).get("active_clients", 0) or 0)
    except Exception:
        return None


def run_legacy_app(args: argparse.Namespace) -> dict[str, Any]:
    base_url = args.backend_url.rstrip("/")
    pid = _backend_pid()
    if pid is None:
        return {"ok": False, "mode": "legacy-app", "error": "Could not find backend process."}

    before_media = _json_request(f"{base_url}/api/cameras/media-plane")
    idle_start_cpu = _process_cpu_seconds(pid)
    idle_start_wall = time.monotonic()
    time.sleep(max(0.0, float(args.idle_sample_s)))
    idle_cpu_s = _process_cpu_seconds(pid) - idle_start_cpu
    idle_wall_s = time.monotonic() - idle_start_wall

    clients = [
        StreamClientResult(index=index, url=_stream_url(base_url, args.role, index=index))
        for index in range(max(0, int(args.clients)))
    ]
    threads = [
        threading.Thread(
            target=_stream_client,
            kwargs={
                "result": client,
                "duration_s": float(args.duration_s),
                "chunk_size": int(args.chunk_size),
            },
            daemon=True,
        )
        for client in clients
    ]
    for thread in threads:
        thread.start()

    ready_deadline = time.monotonic() + max(1.0, float(args.ready_timeout_s))
    for client in clients:
        client.ready.wait(max(0.0, ready_deadline - time.monotonic()))

    time.sleep(max(0.0, float(args.settle_s)))
    during_media = _json_request(f"{base_url}/api/cameras/media-plane")
    start_cpu = _process_cpu_seconds(pid)
    start_wall = time.monotonic()
    start_rss = _process_rss_kb(pid)
    for thread in threads:
        thread.join(timeout=max(0.1, float(args.duration_s) + 3.0))
    end_wall = time.monotonic()
    end_cpu = _process_cpu_seconds(pid)
    end_rss = _process_rss_kb(pid)
    after_media = _json_request(f"{base_url}/api/cameras/media-plane")

    elapsed_s = max(0.001, end_wall - start_wall)
    client_bytes = sum(client.bytes_read for client in clients)
    return {
        "ok": True,
        "mode": "legacy-app",
        "role": args.role,
        "backend_pid": pid,
        "clients_requested": max(0, int(args.clients)),
        "clients_connected": sum(1 for client in clients if client.connected),
        "duration_s": round(elapsed_s, 3),
        "idle_sample_s": round(idle_wall_s, 3),
        "backend_idle_cpu_pct_one_core": round(100.0 * idle_cpu_s / max(0.001, idle_wall_s), 2),
        "backend_cpu_seconds": round(end_cpu - start_cpu, 3),
        "backend_cpu_pct_one_core": round(100.0 * (end_cpu - start_cpu) / elapsed_s, 2),
        "backend_rss_kb_before": start_rss,
        "backend_rss_kb_after": end_rss,
        "client_bytes_total": client_bytes,
        "client_mbps_total": round((client_bytes * 8.0) / (elapsed_s * 1_000_000.0), 3),
        "legacy_clients_before": _legacy_clients_from_media_plane(before_media),
        "legacy_clients_during": _legacy_clients_from_media_plane(during_media),
        "legacy_clients_after": _legacy_clients_from_media_plane(after_media),
        "clients": [
            {
                "index": client.index,
                "connected": client.connected,
                "bytes_read": client.bytes_read,
                "error": client.error,
            }
            for client in clients
        ],
    }


def _run_ffmpeg_case(name: str, command: list[str], *, duration_s: float) -> dict[str, Any]:
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic()
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    wall_s = max(0.001, time.monotonic() - start)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu_s = (after.ru_utime - before.ru_utime) + (after.ru_stime - before.ru_stime)
    return {
        "name": name,
        "returncode": completed.returncode,
        "wall_s": round(wall_s, 3),
        "cpu_s": round(cpu_s, 3),
        "user_s": round(after.ru_utime - before.ru_utime, 3),
        "system_s": round(after.ru_stime - before.ru_stime, 3),
        "cpu_pct_one_core": round(100.0 * cpu_s / wall_s, 1),
        "speed_vs_realtime": round(float(duration_s) / wall_s, 2),
        "stderr_tail": completed.stderr.strip().splitlines()[-5:],
    }


def run_ffmpeg_synthetic(args: argparse.Namespace) -> dict[str, Any]:
    size = f"{int(args.width)}x{int(args.height)}"
    duration_s = float(args.duration_s)
    common = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc2=size={size}:rate={int(args.fps)}",
        "-t",
        str(duration_s),
        "-an",
    ]
    cases = [
        (
            "software_mjpeg",
            [*common, "-c:v", "mjpeg", "-q:v", "5", "-f", "null", "-"],
        ),
        (
            "software_libx264",
            [*common, "-c:v", "libx264", "-preset", "veryfast", "-b:v", str(args.bitrate), "-f", "null", "-"],
        ),
        (
            "hardware_h264_rkmpp",
            [*common, "-vf", "format=nv12", "-c:v", "h264_rkmpp", "-b:v", str(args.bitrate), "-f", "null", "-"],
        ),
    ]
    return {
        "ok": True,
        "mode": "ffmpeg-synthetic",
        "width": int(args.width),
        "height": int(args.height),
        "fps": int(args.fps),
        "duration_s": duration_s,
        "cases": [_run_ffmpeg_case(name, command, duration_s=duration_s) for name, command in cases],
    }


def _role_source_from_media_plane(base_url: str, role: str) -> str | None:
    payload = _json_request(f"{base_url.rstrip('/')}/api/cameras/media-plane")
    role_info = payload.get("roles", {}).get(role)
    if isinstance(role_info, dict) and isinstance(role_info.get("physical_source"), str):
        return str(role_info["physical_source"])
    return None


def run_ffmpeg_camera_rkmpp(args: argparse.Namespace) -> dict[str, Any]:
    source = args.device
    if not source:
        role_source = _role_source_from_media_plane(args.backend_url, args.role)
        if isinstance(role_source, str) and role_source.startswith("video:"):
            source = f"/dev/video{role_source.split(':', 1)[1]}"
    if not source:
        return {
            "ok": False,
            "mode": "ffmpeg-camera-rkmpp",
            "error": "Pass --device or use a role that maps to video:N in /api/cameras/media-plane.",
        }
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-f",
        "v4l2",
        "-input_format",
        str(args.input_format),
        "-video_size",
        f"{int(args.width)}x{int(args.height)}",
        "-framerate",
        str(int(args.fps)),
        "-i",
        source,
        "-t",
        str(float(args.duration_s)),
        "-an",
        "-vf",
        "format=nv12",
        "-c:v",
        "h264_rkmpp",
        "-b:v",
        str(args.bitrate),
        "-f",
        "null",
        "-",
    ]
    result = _run_ffmpeg_case("camera_h264_rkmpp", command, duration_s=float(args.duration_s))
    return {
        "ok": result["returncode"] == 0,
        "mode": "ffmpeg-camera-rkmpp",
        "role": args.role,
        "device": source,
        "width": int(args.width),
        "height": int(args.height),
        "fps": int(args.fps),
        "input_format": args.input_format,
        "case": result,
    }


def run_all(args: argparse.Namespace) -> dict[str, Any]:
    results = [run_legacy_app(args), run_ffmpeg_synthetic(args)]
    if args.include_camera_rkmpp:
        results.append(run_ffmpeg_camera_rkmpp(args))
    return {"ok": all(bool(item.get("ok")) for item in results), "mode": "all", "results": results}


def _print_text(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark camera transport CPU and throughput.")
    parser.add_argument(
        "--mode",
        choices=("all", "legacy-app", "ffmpeg-synthetic", "ffmpeg-camera-rkmpp"),
        default="all",
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--role", default="c_channel_2")
    parser.add_argument("--clients", type=int, default=3)
    parser.add_argument("--duration-s", type=float, default=8.0)
    parser.add_argument("--idle-sample-s", type=float, default=2.0)
    parser.add_argument("--settle-s", type=float, default=1.0)
    parser.add_argument("--ready-timeout-s", type=float, default=4.0)
    parser.add_argument("--chunk-size", type=int, default=65536)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--bitrate", default="2500k")
    parser.add_argument("--device", default="")
    parser.add_argument("--input-format", default="mjpeg")
    parser.add_argument("--include-camera-rkmpp", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.mode == "legacy-app":
        payload = run_legacy_app(args)
    elif args.mode == "ffmpeg-synthetic":
        payload = run_ffmpeg_synthetic(args)
    elif args.mode == "ffmpeg-camera-rkmpp":
        payload = run_ffmpeg_camera_rkmpp(args)
    else:
        payload = run_all(args)
    _print_text(payload)
    return 0 if payload.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
