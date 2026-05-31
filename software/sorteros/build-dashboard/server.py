"""
SorterOS build dashboard — local Mac service.

Start:  uv run python server.py
API:    http://localhost:7373
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── paths ────────────────────────────────────────────────────────────────────

DASHBOARD_DIR = Path(__file__).resolve().parent
BUILD_DIR = DASHBOARD_DIR.parent / "build"
OUT_DIR = BUILD_DIR / "out"
CONFIG_TOML = BUILD_DIR / "config.toml"
PRESET_FILE = DASHBOARD_DIR / "preset.toml"     # gitignored, local only

# Phase order + rough expected durations (seconds) from past builds on M2.
PHASE_DURATIONS: dict[str, int] = {
    "prep": 50,
    "grow": 15,
    "mount": 5,
    "overlay": 3,
    "portal": 20,
    "chroot": 90,
    "finalize": 5,
    "zip": 120,
}
PHASES = list(PHASE_DURATIONS.keys())
TOTAL_EXPECTED = sum(PHASE_DURATIONS.values())

PORT = int(os.environ.get("DASHBOARD_PORT", "7373"))

# ── state ────────────────────────────────────────────────────────────────────

@dataclass
class BuildState:
    running: bool = False
    phase: str = ""
    phase_index: int = 0
    log_lines: list[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    success: bool | None = None
    version: str = ""
    output_path: str = ""

_state = BuildState()
_subscribers: list[asyncio.Queue] = []
_build_lock = asyncio.Lock()


def _broadcast(event: dict) -> None:
    data = json.dumps(event)
    for q in list(_subscribers):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


def _push_log(line: str) -> None:
    _state.log_lines.append(line)
    if len(_state.log_lines) > 2000:
        _state.log_lines = _state.log_lines[-2000:]

    phase_match = re.search(r"=== phase: (\w[\w-]*) ===", line)
    if phase_match:
        _state.phase = phase_match.group(1)
        _state.phase_index = PHASES.index(_state.phase) if _state.phase in PHASES else 0

    _broadcast({"type": "log", "line": line, "phase": _state.phase})


# ── build history ─────────────────────────────────────────────────────────────

@dataclass
class BuildRecord:
    version: str
    date: str
    path: str
    size_mb: float
    success: bool


def _scan_builds() -> list[BuildRecord]:
    records: list[BuildRecord] = []
    if not OUT_DIR.exists():
        return records
    seen: set[str] = set()
    candidates = sorted(
        list(OUT_DIR.glob("sorteros-v*.zip")) + list(OUT_DIR.glob("sorteros-v*.img")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for p in candidates:
        m = re.match(r"sorteros-(v[\d.]+)-(\d{4}-\d{2}-\d{2})\.(img|zip)", p.name)
        if not m:
            continue
        key = f"{m.group(1)}-{m.group(2)}"
        if key in seen:
            continue  # prefer .zip over .img for same version/date
        seen.add(key)
        records.append(BuildRecord(
            version=m.group(1),
            date=m.group(2),
            path=str(p),
            size_mb=round(p.stat().st_size / 1024**2, 1),
            success=True,
        ))
    return records


# ── config helpers ────────────────────────────────────────────────────────────

def _read_build_config() -> dict:
    if CONFIG_TOML.exists():
        with open(CONFIG_TOML, "rb") as f:
            return tomllib.load(f)
    return {}


def _read_preset() -> str:
    if PRESET_FILE.exists():
        return PRESET_FILE.read_text()
    return ""


# ── build runner ──────────────────────────────────────────────────────────────

class BuildRequest(BaseModel):
    version: str | None = None
    branch: str | None = None
    base_img: str | None = None
    preset_config: str | None = None   # raw TOML to write as preset


async def _run_build(req: BuildRequest) -> None:
    global _state
    _state = BuildState(running=True, start_time=time.time())

    cfg = _read_build_config()
    _state.version = req.version or cfg.get("output", {}).get("version", "?")

    if req.preset_config is not None:
        PRESET_FILE.write_text(req.preset_config)

    env = os.environ.copy()
    if req.base_img:
        env["SORTEROS_BASE_IMG"] = req.base_img

    cmd = [sys.executable, str(BUILD_DIR / "build.py")]
    if req.branch:
        cmd += ["--branch", req.branch]

    _broadcast({"type": "start", "version": _state.version})

    try:
        proc = await asyncio.create_subprocess_exec(
            "colima", "ssh", "--", "bash", "-c",
            f"cd {BUILD_DIR} && sudo python3 build.py"
            + (f" --branch {req.branch}" if req.branch else ""),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        assert proc.stdout
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            _push_log(line)

        await proc.wait()
        _state.success = proc.returncode == 0
    except Exception as e:
        _push_log(f"[dashboard] build subprocess error: {e}")
        _state.success = False

    _state.end_time = time.time()
    _state.running = False

    # Prefer the .zip if present, fall back to .img
    latest_zip = sorted(OUT_DIR.glob("sorteros-v*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest_img = sorted(OUT_DIR.glob("sorteros-v*.img"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest = latest_zip or latest_img
    if latest:
        _state.output_path = str(latest[0])

    _broadcast({"type": "done", "success": _state.success, "path": _state.output_path})


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(title="SorterOS Build Dashboard")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (DASHBOARD_DIR / "index.html").read_text()
    return HTMLResponse(html)


@app.post("/build")
async def start_build(req: BuildRequest) -> dict:
    if _build_lock.locked():
        raise HTTPException(409, "build already running")
    async with _build_lock:
        asyncio.create_task(_run_build(req))
    return {"status": "started"}


@app.get("/build/status")
async def build_status() -> dict:
    elapsed = (time.time() - _state.start_time) if _state.start_time else 0
    phases_done_time = sum(PHASE_DURATIONS.get(p, 0) for p in PHASES[:_state.phase_index])
    pct = min(99, int(phases_done_time / TOTAL_EXPECTED * 100)) if _state.running else (100 if _state.success else 0)
    eta = max(0, TOTAL_EXPECTED - elapsed) if _state.running else 0
    return {
        "running": _state.running,
        "phase": _state.phase,
        "phase_index": _state.phase_index,
        "total_phases": len(PHASES),
        "pct": pct,
        "eta_s": int(eta),
        "elapsed_s": int(elapsed),
        "success": _state.success,
        "version": _state.version,
        "output_path": _state.output_path,
        "log_tail": _state.log_lines[-100:],
    }


@app.get("/builds")
async def list_builds() -> list[dict]:
    return [asdict(r) for r in _scan_builds()]


@app.get("/config")
async def get_config() -> dict:
    cfg = _read_build_config()
    return {
        "version": cfg.get("output", {}).get("version", ""),
        "branch": cfg.get("branch", {}).get("default", "main"),
        "preset": _read_preset(),
    }


@app.get("/stream")
async def stream() -> StreamingResponse:
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.append(q)

    async def gen() -> AsyncIterator[str]:
        try:
            # Send current state immediately on connect
            yield f"data: {json.dumps({'type': 'state', 'status': (await build_status())})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _subscribers.remove(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/open-finder")
async def open_in_finder(path: str) -> dict:
    subprocess.Popen(["open", "-R", path])
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    print(f"SorterOS Build Dashboard → http://localhost:{PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
