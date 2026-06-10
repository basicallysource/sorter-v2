#!/usr/bin/env python3
"""A/B-compare the legacy and RKMPP camera pipelines on the same device.

Runs the backend alternately in two modes and measures both under an
identical, sequential workload:

* ``legacy`` — OpenCV capture + per-client MJPEG streaming (main-branch
  behaviour; all RKMPP/GStreamer env switches off).
* ``rkmpp``  — GStreamer MPP capture + librga NV12 + h264_rkmpp hardware
  encode + WebRTC (the sorthive target pipeline).

Mode switching appends a marked env block to ``software/.env`` (the systemd
unit sources that file last, so the block overrides the firstboot contract
env) and restarts the backend service. The original ``.env`` is restored on
exit — including on SIGINT.

Per mode the workload is: settle → idle baseline → streaming load
(``--clients`` viewers on every benchmarked role; MJPEG HTTP clients in
legacy mode, aiortc WebRTC consumers in rkmpp mode). A 1 Hz sampler records
the backend *process tree* (the encoder children must not escape the bill),
this benchmark process itself (the WebRTC consumers decode H.264 in
software, which costs client-side CPU on the same box — reported
separately), total system CPU, thermal zones, CPU frequencies, and NPU load.

Glass-to-glass latency is intentionally out of scope; client-side FPS and
bitrate are the stream-quality proxies.

Usage (on the device, as root):
    .venv/bin/python scripts/ab_compare_camera_pipelines.py \
        --duration-s 120 --idle-s 60 --clients 3
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import benchmark_camera_transport as bct  # noqa: E402  (sibling script import)

ENV_BLOCK_BEGIN = "# >>> ab-benchmark (managed by ab_compare_camera_pipelines.py)"
ENV_BLOCK_END = "# <<< ab-benchmark"

MODES: dict[str, dict[str, str]] = {
    "legacy": {
        "SORTER_CAMERA_CAPTURE_BACKEND": "opencv",
        "SORTER_ENABLE_GSTREAMER_MPP_CAPTURE": "0",
        "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "0",
    },
    "rkmpp": {
        "SORTER_CAMERA_CAPTURE_BACKEND": "gstreamer_mpp",
        "SORTER_ENABLE_GSTREAMER_MPP_CAPTURE": "1",
        "SORTER_ENABLE_FFMPEG_RKMPP_WEBRTC": "1",
    },
}


# ---------------------------------------------------------------------------
# .env block management
# ---------------------------------------------------------------------------

def strip_env_block(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    inside = False
    for line in lines:
        if line.strip() == ENV_BLOCK_BEGIN:
            inside = True
            continue
        if line.strip() == ENV_BLOCK_END:
            inside = False
            continue
        if not inside:
            out.append(line)
    result = "\n".join(out)
    if text.endswith("\n") and result and not result.endswith("\n"):
        result += "\n"
    return result


def render_env_block(env: dict[str, str]) -> str:
    body = "\n".join(f"{key}={value}" for key, value in sorted(env.items()))
    return f"{ENV_BLOCK_BEGIN}\n{body}\n{ENV_BLOCK_END}\n"


def apply_env_block(env_file: Path, env: dict[str, str]) -> None:
    text = env_file.read_text() if env_file.exists() else ""
    text = strip_env_block(text)
    if text and not text.endswith("\n"):
        text += "\n"
    env_file.write_text(text + render_env_block(env))


# ---------------------------------------------------------------------------
# Process-tree and system sampling
# ---------------------------------------------------------------------------

def _descendant_pids(root_pid: int) -> list[int]:
    pids = [root_pid]
    seen = {root_pid}
    queue = [root_pid]
    while queue:
        pid = queue.pop()
        task_dir = Path(f"/proc/{pid}/task")
        try:
            children_files = list(task_dir.glob("*/children"))
        except OSError:
            continue
        for child_file in children_files:
            try:
                child_pids = [int(p) for p in child_file.read_text().split()]
            except (OSError, ValueError):
                continue
            for child in child_pids:
                if child not in seen:
                    seen.add(child)
                    pids.append(child)
                    queue.append(child)
    return pids


def _tree_cpu_seconds(root_pid: int) -> float:
    total = 0.0
    for pid in _descendant_pids(root_pid):
        try:
            total += bct._process_cpu_seconds(pid)
        except OSError:
            continue
    return total


def _tree_rss_kb(root_pid: int) -> int:
    total = 0
    for pid in _descendant_pids(root_pid):
        rss = bct._process_rss_kb(pid)
        if rss:
            total += rss
    return total


def _system_cpu_ticks() -> tuple[int, int]:
    """Return (busy_ticks, total_ticks) across all CPUs."""
    with open("/proc/stat", "r", encoding="utf-8") as handle:
        fields = handle.readline().split()[1:]
    values = [int(v) for v in fields]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return total - idle, total


def _thermal_zones() -> dict[str, float]:
    zones: dict[str, float] = {}
    for zone in sorted(Path("/sys/class/thermal").glob("thermal_zone*")):
        try:
            zone_type = (zone / "type").read_text().strip()
            temp = int((zone / "temp").read_text().strip()) / 1000.0
        except (OSError, ValueError):
            continue
        zones[f"{zone.name}:{zone_type}"] = temp
    return zones


def _cpu_freqs_mhz() -> list[float]:
    freqs: list[float] = []
    for path in sorted(Path("/sys/devices/system/cpu").glob("cpu[0-9]*/cpufreq/scaling_cur_freq")):
        try:
            freqs.append(int(path.read_text().strip()) / 1000.0)
        except (OSError, ValueError):
            continue
    return freqs


def _npu_load() -> str | None:
    try:
        return Path("/sys/kernel/debug/rknpu/load").read_text().strip()
    except OSError:
        return None


@dataclass
class SamplerStats:
    samples: int = 0
    backend_cpu_pct_sum: float = 0.0
    backend_cpu_pct_max: float = 0.0
    self_cpu_pct_sum: float = 0.0
    system_cpu_pct_sum: float = 0.0
    system_cpu_pct_max: float = 0.0
    backend_rss_kb_max: int = 0
    temp_max_c: float = 0.0
    temp_max_zone: str = ""
    cpu_freq_min_mhz: float = float("inf")
    npu_loads: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        n = max(1, self.samples)
        return {
            "samples": self.samples,
            "backend_tree_cpu_pct_mean": round(self.backend_cpu_pct_sum / n, 1),
            "backend_tree_cpu_pct_max": round(self.backend_cpu_pct_max, 1),
            "benchmark_client_cpu_pct_mean": round(self.self_cpu_pct_sum / n, 1),
            "system_cpu_pct_mean": round(self.system_cpu_pct_sum / n, 1),
            "system_cpu_pct_max": round(self.system_cpu_pct_max, 1),
            "backend_tree_rss_mb_max": round(self.backend_rss_kb_max / 1024.0, 1),
            "temp_max_c": round(self.temp_max_c, 1),
            "temp_max_zone": self.temp_max_zone,
            "cpu_freq_min_mhz": None if self.cpu_freq_min_mhz == float("inf") else round(self.cpu_freq_min_mhz),
            "npu_load_last": self.npu_loads[-1] if self.npu_loads else None,
        }


class Sampler:
    """1 Hz background sampler over the backend process tree + system."""

    def __init__(self, backend_pid: int, interval_s: float = 1.0) -> None:
        self.backend_pid = backend_pid
        self.interval_s = interval_s
        self.stats = SamplerStats()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> "Sampler":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=self.interval_s * 3)

    def _run(self) -> None:
        prev_backend = _tree_cpu_seconds(self.backend_pid)
        prev_self = bct._process_cpu_seconds(os.getpid())
        prev_busy, prev_total = _system_cpu_ticks()
        prev_wall = time.monotonic()
        cpu_count = os.cpu_count() or 1
        while not self._stop.wait(self.interval_s):
            wall = time.monotonic()
            elapsed = max(0.001, wall - prev_wall)
            try:
                backend = _tree_cpu_seconds(self.backend_pid)
                self_cpu = bct._process_cpu_seconds(os.getpid())
                busy, total = _system_cpu_ticks()
            except OSError:
                continue
            stats = self.stats
            stats.samples += 1
            backend_pct = 100.0 * (backend - prev_backend) / elapsed
            stats.backend_cpu_pct_sum += backend_pct
            stats.backend_cpu_pct_max = max(stats.backend_cpu_pct_max, backend_pct)
            stats.self_cpu_pct_sum += 100.0 * (self_cpu - prev_self) / elapsed
            tick_delta = max(1, total - prev_total)
            system_pct = 100.0 * (busy - prev_busy) / tick_delta * cpu_count
            stats.system_cpu_pct_sum += system_pct
            stats.system_cpu_pct_max = max(stats.system_cpu_pct_max, system_pct)
            stats.backend_rss_kb_max = max(stats.backend_rss_kb_max, _tree_rss_kb(self.backend_pid))
            for zone, temp in _thermal_zones().items():
                if temp > stats.temp_max_c:
                    stats.temp_max_c = temp
                    stats.temp_max_zone = zone
            freqs = _cpu_freqs_mhz()
            if freqs:
                stats.cpu_freq_min_mhz = min(stats.cpu_freq_min_mhz, min(freqs))
            npu = _npu_load()
            if npu:
                stats.npu_loads.append(npu)
            prev_backend, prev_self = backend, self_cpu
            prev_busy, prev_total, prev_wall = busy, total, wall


# ---------------------------------------------------------------------------
# Workloads
# ---------------------------------------------------------------------------

def run_mjpeg_stream_phase(
    backend_url: str, roles: list[str], clients_per_role: int, duration_s: float
) -> dict[str, Any]:
    clients: list[bct.StreamClientResult] = []
    threads: list[threading.Thread] = []
    for role in roles:
        for index in range(clients_per_role):
            client = bct.StreamClientResult(
                index=index, url=bct._stream_url(backend_url, role, index=index)
            )
            clients.append(client)
            threads.append(
                threading.Thread(
                    target=bct._stream_client,
                    kwargs={"result": client, "duration_s": duration_s, "chunk_size": 65536},
                    daemon=True,
                )
            )
    start = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=duration_s + 10.0)
    elapsed = max(0.001, time.monotonic() - start)
    total_bytes = sum(c.bytes_read for c in clients)
    return {
        "transport": "mjpeg",
        "clients_requested": len(clients),
        "clients_connected": sum(1 for c in clients if c.connected),
        "client_errors": sorted({c.error for c in clients if c.error}),
        "mbps_total": round(total_bytes * 8.0 / (elapsed * 1_000_000.0), 3),
        # MJPEG has no frame counter on the byte stream; bitrate is the
        # throughput evidence, FPS is backend-side (one capture per role).
        "fps_total": None,
    }


@dataclass
class _WebRtcViewer:
    role: str
    index: int
    frames: int = 0
    connected: bool = False
    error: str | None = None
    bytes_received: int = 0


async def _consume_webrtc_view(
    backend_url: str, viewer: _WebRtcViewer, duration_s: float
) -> None:
    from aiortc import RTCPeerConnection, RTCSessionDescription

    import probe_webrtc_view_scaling as pvs

    peer = RTCPeerConnection()

    @peer.on("track")
    def _on_track(track: Any) -> None:
        async def _drain() -> None:
            deadline = time.monotonic() + duration_s
            while time.monotonic() < deadline:
                try:
                    await asyncio.wait_for(track.recv(), timeout=5.0)
                except Exception:
                    return
                viewer.frames += 1

        asyncio.ensure_future(_drain())

    peer.addTransceiver("video", direction="recvonly")
    offer = await peer.createOffer()
    await peer.setLocalDescription(offer)
    await pvs._wait_for_ice_gathering_complete(peer)
    local = peer.localDescription
    if local is None:
        viewer.error = "no local WebRTC offer"
        await peer.close()
        return
    answer = pvs._json_request(
        "POST",
        pvs._offer_url(backend_url, viewer.role),
        {"type": local.type, "sdp": local.sdp},
    )
    if not answer.get("ok"):
        viewer.error = json.dumps(answer.get("error") or answer, sort_keys=True)[:500]
        await peer.close()
        return
    await peer.setRemoteDescription(
        RTCSessionDescription(sdp=str(answer["sdp"]), type=str(answer["type"]))
    )
    viewer.connected = True
    await asyncio.sleep(duration_s)
    try:
        stats = await peer.getStats()
        for report in stats.values():
            if getattr(report, "type", "") == "inbound-rtp":
                viewer.bytes_received += int(getattr(report, "bytesReceived", 0) or 0)
    except Exception:
        pass
    await peer.close()


async def _run_webrtc_stream_phase_async(
    backend_url: str, roles: list[str], clients_per_role: int, duration_s: float
) -> dict[str, Any]:
    viewers = [
        _WebRtcViewer(role=role, index=index)
        for role in roles
        for index in range(clients_per_role)
    ]
    start = time.monotonic()
    await asyncio.gather(
        *(_consume_webrtc_view(backend_url, viewer, duration_s) for viewer in viewers)
    )
    elapsed = max(0.001, time.monotonic() - start)
    total_frames = sum(v.frames for v in viewers)
    total_bytes = sum(v.bytes_received for v in viewers)
    return {
        "transport": "webrtc",
        "clients_requested": len(viewers),
        "clients_connected": sum(1 for v in viewers if v.connected),
        "client_errors": sorted({v.error for v in viewers if v.error}),
        "mbps_total": round(total_bytes * 8.0 / (elapsed * 1_000_000.0), 3),
        "fps_total": round(total_frames / elapsed, 1),
        "fps_per_client_mean": round(total_frames / elapsed / max(1, len(viewers)), 1),
        "decode_note": (
            "WebRTC consumers software-decode H.264 in this benchmark process; "
            "its CPU is reported separately as benchmark_client_cpu_pct_mean."
        ),
    }


def run_webrtc_stream_phase(
    backend_url: str, roles: list[str], clients_per_role: int, duration_s: float
) -> dict[str, Any]:
    return asyncio.run(
        _run_webrtc_stream_phase_async(backend_url, roles, clients_per_role, duration_s)
    )


# ---------------------------------------------------------------------------
# Backend service control
# ---------------------------------------------------------------------------

def restart_backend(service: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] systemctl restart {service}")
        return
    subprocess.run(["systemctl", "restart", service], check=True)


def wait_backend_ready(backend_url: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = bct._json_request(f"{backend_url}/api/cameras/media-plane", timeout_s=5.0)
        if last.get("ok") and last.get("active"):
            return last
        time.sleep(2.0)
    raise TimeoutError(
        f"backend did not become ready within {timeout_s:.0f}s; last media-plane: "
        + json.dumps({k: last.get(k) for k in ("ok", "active", "error")}, sort_keys=True)
    )


def discover_roles(media_plane: dict[str, Any]) -> list[str]:
    roles = media_plane.get("roles")
    if isinstance(roles, dict) and roles:
        return sorted(roles.keys())
    return []


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_mode(mode: str, args: argparse.Namespace) -> dict[str, Any]:
    backend_url = args.backend_url.rstrip("/")
    if args.dry_run:
        print(f"[dry-run] [{mode}] would apply env block to {args.env_file}: {MODES[mode]}")
        restart_backend(args.service, dry_run=True)
        return {"mode": mode, "dry_run": True, "env": MODES[mode]}
    apply_env_block(Path(args.env_file), MODES[mode])
    print(f"[{mode}] env block applied to {args.env_file}")
    restart_backend(args.service, dry_run=False)

    media_plane = wait_backend_ready(backend_url, args.ready_timeout_s)
    pid = bct._backend_pid()
    if pid is None:
        raise RuntimeError(f"[{mode}] backend process not found after restart")

    roles = args.roles or discover_roles(media_plane)
    if not roles:
        raise RuntimeError(f"[{mode}] no camera roles found; pass --roles explicitly")
    print(f"[{mode}] backend pid={pid}, roles={roles}, settling {args.settle_s:.0f}s")
    time.sleep(args.settle_s)

    result: dict[str, Any] = {
        "mode": mode,
        "env": MODES[mode],
        "roles": roles,
        "backend_pid": pid,
        "selected_encoder_path": media_plane.get("capabilities", {}).get("selected_encoder_path"),
    }

    print(f"[{mode}] idle baseline {args.idle_s:.0f}s")
    with Sampler(pid) as sampler:
        time.sleep(args.idle_s)
    result["idle"] = sampler.stats.summary()

    print(f"[{mode}] streaming load {args.duration_s:.0f}s, {args.clients} clients/role")
    with Sampler(pid) as sampler:
        if mode == "legacy":
            stream = run_mjpeg_stream_phase(backend_url, roles, args.clients, args.duration_s)
        else:
            stream = run_webrtc_stream_phase(backend_url, roles, args.clients, args.duration_s)
    result["stream"] = stream
    result["stream"]["sampler"] = sampler.stats.summary()

    if stream["clients_connected"] < stream["clients_requested"]:
        print(
            f"[{mode}] WARNING: only {stream['clients_connected']}/{stream['clients_requested']} "
            f"clients connected: {stream['client_errors']}"
        )
    return result


def render_markdown(results: dict[str, dict[str, Any]], generated_at: str) -> str:
    modes = list(results.keys())

    def row(label: str, getter: Any) -> str:
        values = [getter(results[m]) for m in modes]
        return f"| {label} | " + " | ".join("—" if v is None else str(v) for v in values) + " |"

    lines = [
        "# A/B Camera Pipeline Comparison",
        "",
        f"Generated: {generated_at}",
        "",
        f"Roles: `{results[modes[0]].get('roles')}`, "
        f"clients/role: see per-mode JSON. Same device, modes run sequentially.",
        "",
        "| Metric | " + " | ".join(modes) + " |",
        "|---|" + "---|" * len(modes),
        row("Encoder path", lambda r: r.get("selected_encoder_path")),
        row("Idle: backend CPU % (mean, 1 core = 100)", lambda r: r.get("idle", {}).get("backend_tree_cpu_pct_mean")),
        row("Idle: system CPU %", lambda r: r.get("idle", {}).get("system_cpu_pct_mean")),
        row("Idle: backend RSS MB (max)", lambda r: r.get("idle", {}).get("backend_tree_rss_mb_max")),
        row("Stream: backend CPU % (mean)", lambda r: r.get("stream", {}).get("sampler", {}).get("backend_tree_cpu_pct_mean")),
        row("Stream: backend CPU % (max)", lambda r: r.get("stream", {}).get("sampler", {}).get("backend_tree_cpu_pct_max")),
        row("Stream: system CPU % (mean)", lambda r: r.get("stream", {}).get("sampler", {}).get("system_cpu_pct_mean")),
        row("Stream: benchmark-client CPU % (mean)", lambda r: r.get("stream", {}).get("sampler", {}).get("benchmark_client_cpu_pct_mean")),
        row("Stream: backend RSS MB (max)", lambda r: r.get("stream", {}).get("sampler", {}).get("backend_tree_rss_mb_max")),
        row("Stream: clients connected", lambda r: f"{r.get('stream', {}).get('clients_connected')}/{r.get('stream', {}).get('clients_requested')}"),
        row("Stream: total Mbps", lambda r: r.get("stream", {}).get("mbps_total")),
        row("Stream: total FPS (client-side)", lambda r: r.get("stream", {}).get("fps_total")),
        row("Max SoC temp °C (zone)", lambda r: f"{r.get('stream', {}).get('sampler', {}).get('temp_max_c')} ({r.get('stream', {}).get('sampler', {}).get('temp_max_zone')})"),
        row("Min CPU freq MHz (throttle indicator)", lambda r: r.get("stream", {}).get("sampler", {}).get("cpu_freq_min_mhz")),
        row("NPU load (last sample)", lambda r: r.get("stream", {}).get("sampler", {}).get("npu_load_last")),
        "",
        "Notes:",
        "- Backend CPU covers the whole process tree (ffmpeg/GStreamer encoder children included).",
        "- MJPEG has no client-side frame counter; compare via Mbps + backend CPU.",
        "- WebRTC client-side decode runs inside the benchmark process (separate CPU column).",
        "- Glass-to-glass latency is not measured.",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--modes", default="legacy,rkmpp", help="Comma list, run order")
    parser.add_argument("--roles", default="", help="Comma list; default: all roles from media-plane")
    parser.add_argument("--clients", type=int, default=3)
    parser.add_argument("--duration-s", type=float, default=120.0)
    parser.add_argument("--idle-s", type=float, default=60.0)
    parser.add_argument("--settle-s", type=float, default=10.0)
    parser.add_argument("--ready-timeout-s", type=float, default=240.0)
    parser.add_argument("--backend-url", default=bct.DEFAULT_BACKEND_URL)
    parser.add_argument("--service", default=bct.BACKEND_SERVICE)
    parser.add_argument(
        "--env-file",
        default=str(SCRIPT_DIR.parents[2] / ".env"),
        help="software/.env sourced by the backend service",
    )
    parser.add_argument("--output-dir", default=str(SCRIPT_DIR.parent / "reports"))
    parser.add_argument("--dry-run", action="store_true", help="Skip systemctl + workload, print actions")
    args = parser.parse_args(argv)
    args.modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    args.roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    for mode in args.modes:
        if mode not in MODES:
            parser.error(f"unknown mode {mode!r}; choose from {sorted(MODES)}")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    env_file = Path(args.env_file)
    original_env = env_file.read_text() if env_file.exists() else None

    def _restore() -> None:
        if args.dry_run:
            return
        if original_env is None:
            env_file.unlink(missing_ok=True)
        else:
            env_file.write_text(strip_env_block(original_env))
        try:
            restart_backend(args.service, dry_run=False)
        except Exception as exc:
            print(f"WARNING: could not restart backend after restore: {exc}", file=sys.stderr)

    # SIGINT/SIGTERM raise SystemExit so the finally-restore below runs.
    signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

    results: dict[str, dict[str, Any]] = {}
    try:
        for mode in args.modes:
            results[mode] = run_mode(mode, args)
    finally:
        _restore()
        if not args.dry_run:
            print("env restored, backend restarted in original configuration")

    if args.dry_run:
        print("[dry-run] complete; no results written")
        return 0

    generated_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"ab_pipeline_{stamp}.json"
    json_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"results: {json_path}")
    if len(results) > 1:
        md_path = output_dir / f"ab_pipeline_{stamp}.md"
        md_path.write_text(render_markdown(results, generated_at))
        print(f"report:  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
