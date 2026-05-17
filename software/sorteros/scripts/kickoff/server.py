from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import shlex
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse

HIVE_HOST = os.environ.get("SORTEROS_BUILD_HOST", "45.55.232.164")
HIVE_USER = os.environ.get("SORTEROS_BUILD_USER", "root")
BUILD_DIR_REMOTE = "/basically/sorteros/build"
OUT_DIR_REMOTE = "/basically/sorteros/out"
DOWNLOADS_DIR = pathlib.Path.home() / "Downloads"
STATE_FILE = pathlib.Path(__file__).parent / ".state.json"

STAGES = [
    "decompress",       # zstd -d
    "extract_ext4",     # first dd
    "place_ext4",       # second dd
    "partition_table",  # parted
    "format_fat",       # mkfs.vfat
    "fsck_ext4",        # e2fsck
    "chroot_mount",
    "apt_cloud_init",
    "fat_seed",
    "tailscale",
    "ap6275p",
    "ethernet_fallback",
    "iphone_hotspot",
    "branch_swap",
    "firstboot_units",
    "growfs_unit",
    "apply_network_config",
    "image_ready",
    "downloading",
    "done",
]

STAGE_PATTERNS: list[tuple[str, str]] = [
    ("decompress", r"decompressing|copying .* → "),
    ("extract_ext4", r"extracting ext4 partition data"),
    ("place_ext4", r"writing ext4 partition data back at offset"),
    ("partition_table", r"rewriting MBR partition table"),
    ("format_fat", r"formatting .* as FAT32"),
    ("fsck_ext4", r"fsck of moved ext4 partition"),
    ("chroot_mount", r"mounting rootfs \+ bind mounts for chroot"),
    ("apt_cloud_init", r"installing cloud-init|apt update"),
    ("ap6275p", r"AP6275P Wi-Fi overlay"),
    ("ethernet_fallback", r"installing ethernet link-local fallback"),
    ("iphone_hotspot", r"installing fallback Wi-Fi"),
    ("tailscale", r"TAILSCALE_AUTH_KEY present"),
    ("branch_swap", r"switching sorter-v2 checkout to branch"),
    ("apply_network_config", r"installing.*apply-network-config|sorteros-apply-network-config"),
    ("growfs_unit", r"sorteros-growfs"),
    ("firstboot_units", r"installing split firstboot units"),
    ("fat_seed", r"populating FAT partition"),
    ("image_ready", r"image ready:"),
]


@dataclass
class BuildState:
    status: str = "idle"                  # idle | building | downloading | done | failed
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    stages: dict[str, str] = field(default_factory=dict)   # stage → "pending" | "running" | "done"
    log_lines: list[str] = field(default_factory=list)
    last_log_size: int = 0
    image_remote_path: Optional[str] = None
    image_local_path: Optional[str] = None
    image_bytes_expected: Optional[int] = None
    image_bytes_local: int = 0
    config: dict = field(default_factory=dict)
    target_name: Optional[str] = None     # e.g. "v2.5"
    finished_remote_log_tail: list[str] = field(default_factory=list)


STATE = BuildState()
STATE_LOCK = threading.RLock()
SUBSCRIBERS: list[asyncio.Queue] = []


def persist_state() -> None:
    try:
        STATE_FILE.write_text(json.dumps(asdict(STATE), indent=2))
    except Exception:
        pass


def load_state() -> None:
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
            for key, value in data.items():
                if hasattr(STATE, key):
                    setattr(STATE, key, value)
        except Exception:
            pass


def broadcast(event: dict) -> None:
    payload = json.dumps(event)
    for queue in list(SUBSCRIBERS):
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def push_log(line: str) -> None:
    with STATE_LOCK:
        STATE.log_lines.append(line)
        STATE.log_lines = STATE.log_lines[-400:]
        for stage_name, pattern in STAGE_PATTERNS:
            if re.search(pattern, line):
                STATE.stages[stage_name] = "done"
        persist_state()
    broadcast({"type": "log", "line": line})
    broadcast({"type": "state", "state": serializable_state()})


def set_stage(stage_name: str, status: str) -> None:
    with STATE_LOCK:
        STATE.stages[stage_name] = status
        persist_state()
    broadcast({"type": "state", "state": serializable_state()})


def serializable_state() -> dict:
    with STATE_LOCK:
        return asdict(STATE)


def ssh_args(remote_cmd: str) -> list[str]:
    return [
        "ssh", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new",
        f"{HIVE_USER}@{HIVE_HOST}", remote_cmd,
    ]


def run_build(config: dict) -> None:
    with STATE_LOCK:
        STATE.status = "building"
        STATE.started_at = time.time()
        STATE.finished_at = None
        STATE.error = None
        STATE.stages = {name: "pending" for name in STAGES}
        STATE.log_lines = []
        STATE.last_log_size = 0
        STATE.image_remote_path = None
        STATE.image_local_path = None
        STATE.image_bytes_expected = None
        STATE.image_bytes_local = 0
        STATE.config = config
        STATE.target_name = config.get("target_name", "v2.x")
        STATE.finished_remote_log_tail = []
    persist_state()
    broadcast({"type": "state", "state": serializable_state()})

    try:
        # Compose extend.sh invocation. The .env on Hive already has
        # TAILSCALE_AUTH_KEY / SORTER_BRANCH; we only override if the
        # form passed explicit values.
        flags: list[str] = []
        if config.get("in_path"):
            flags += ["--in", config["in_path"]]
        if config.get("out_path"):
            flags += ["--out", config["out_path"]]
        if config.get("branch"):
            flags += ["--branch", config["branch"]]
        if config.get("compress"):
            flags += ["--compress"]

        flags_str = " ".join(shlex.quote(f) for f in flags)
        remote_log = f"{OUT_DIR_REMOTE}/extend.log"
        launch_cmd = (
            f"cd {BUILD_DIR_REMOTE} && "
            f"nohup bash extend.sh {flags_str} > {remote_log} 2>&1 & "
            f"disown; echo started"
        )
        push_log(f"[kickoff] launching: extend.sh {flags_str}")
        result = subprocess.run(ssh_args(launch_cmd), capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"launch failed: {result.stderr.strip()}")

        # Poll the remote log until we see "image ready:" or the process exits
        idle_loops = 0
        while True:
            time.sleep(2)
            still_running = subprocess.run(
                ssh_args('pgrep -f "bash extend.sh" >/dev/null && echo yes || echo no'),
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()

            # Pull new log content
            tail_proc = subprocess.run(
                ssh_args(f"wc -c {remote_log} | awk '{{print $1}}'; tail -c +$(({STATE.last_log_size}+1)) {remote_log}"),
                capture_output=True, text=True, timeout=15,
            )
            chunks = tail_proc.stdout.split("\n", 1)
            try:
                new_size = int(chunks[0].strip())
            except (ValueError, IndexError):
                new_size = STATE.last_log_size
            new_content = chunks[1] if len(chunks) > 1 else ""
            if new_content:
                for raw_line in new_content.splitlines():
                    if raw_line.strip():
                        push_log(raw_line.rstrip())
                with STATE_LOCK:
                    STATE.last_log_size = new_size
                idle_loops = 0
            else:
                idle_loops += 1

            if "image ready:" in "\n".join(STATE.log_lines[-20:]):
                break
            if still_running == "no":
                # extend.sh exited but didn't print image-ready → fail
                raise RuntimeError("extend.sh exited without producing an image; see log")
            if idle_loops > 90:  # ~3 min with no output
                raise RuntimeError("build appears stuck (no log activity for 3 min)")

        # Find the image path
        m = re.search(r"image ready: (\S+)", "\n".join(STATE.log_lines))
        if not m:
            raise RuntimeError("couldn't parse image path from log")
        remote_img = m.group(1)
        with STATE_LOCK:
            STATE.image_remote_path = remote_img
        set_stage("image_ready", "done")

        # Get expected size
        sz_proc = subprocess.run(
            ssh_args(f"stat -c %s {shlex.quote(remote_img)}"),
            capture_output=True, text=True, timeout=15,
        )
        try:
            expected_bytes = int(sz_proc.stdout.strip())
        except ValueError:
            expected_bytes = None
        with STATE_LOCK:
            STATE.image_bytes_expected = expected_bytes
            STATE.status = "downloading"
        persist_state()
        broadcast({"type": "state", "state": serializable_state()})

        # Pick local path
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        local_path = DOWNLOADS_DIR / pathlib.Path(remote_img).name
        if local_path.exists():
            local_path.unlink()
        with STATE_LOCK:
            STATE.image_local_path = str(local_path)
        push_log(f"[kickoff] downloading → {local_path}")
        set_stage("downloading", "running")

        # Spawn scp and tail local file size for progress
        scp_proc = subprocess.Popen(
            ["scp", "-C", f"{HIVE_USER}@{HIVE_HOST}:{remote_img}", str(local_path)],
        )

        while scp_proc.poll() is None:
            time.sleep(2)
            if local_path.exists():
                with STATE_LOCK:
                    STATE.image_bytes_local = local_path.stat().st_size
                broadcast({"type": "state", "state": serializable_state()})

        if scp_proc.returncode != 0:
            raise RuntimeError(f"scp failed with exit {scp_proc.returncode}")

        with STATE_LOCK:
            STATE.image_bytes_local = local_path.stat().st_size
            STATE.status = "done"
            STATE.finished_at = time.time()
        set_stage("downloading", "done")
        set_stage("done", "done")
        push_log(f"[kickoff] complete — {local_path} ({STATE.image_bytes_local} bytes)")

    except Exception as exc:
        with STATE_LOCK:
            STATE.status = "failed"
            STATE.error = str(exc)
            STATE.finished_at = time.time()
        push_log(f"[kickoff] ERROR: {exc}")
    finally:
        persist_state()
        broadcast({"type": "state", "state": serializable_state()})


app = FastAPI(title="SorterOS Kickoff")


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SorterOS Kickoff</title>
<style>
:root {
  --bg: #0e1116; --panel: #161b22; --border: #30363d;
  --fg: #e6edf3; --muted: #7d8590; --accent: #58a6ff;
  --ok: #3fb950; --bad: #f85149; --warn: #d29922;
}
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, system-ui, sans-serif; background: var(--bg); color: var(--fg); }
header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 16px; }
header h1 { font-size: 18px; margin: 0; }
header .target { color: var(--muted); }
main { display: grid; grid-template-columns: 360px 1fr; gap: 16px; padding: 16px 24px; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.panel h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 12px; }
label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }
input[type=text] { width: 100%; padding: 6px 8px; background: #0e1116; border: 1px solid var(--border); border-radius: 4px; color: var(--fg); font-family: inherit; font-size: 13px; }
input[type=checkbox] { margin-right: 6px; }
.row { margin-bottom: 10px; }
button { background: var(--accent); color: #0e1116; border: 0; border-radius: 6px; padding: 8px 14px; font-weight: 600; cursor: pointer; font-size: 14px; }
button:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }
.stages { display: flex; flex-direction: column; gap: 4px; }
.stage { display: flex; justify-content: space-between; align-items: center; padding: 4px 8px; border-radius: 4px; font-size: 12px; }
.stage.pending { color: var(--muted); }
.stage.running { background: rgba(88,166,255,0.12); color: var(--accent); }
.stage.done { color: var(--ok); }
.progress { height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 8px; }
.progress > div { height: 100%; background: var(--accent); width: 0%; transition: width 0.3s; }
.log { background: #0e1116; border: 1px solid var(--border); border-radius: 4px; padding: 8px; font-family: ui-monospace, monospace; font-size: 11px; color: #c9d1d9; height: 480px; overflow-y: scroll; white-space: pre-wrap; word-break: break-all; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.badge.idle { background: var(--border); color: var(--muted); }
.badge.building { background: rgba(88,166,255,0.2); color: var(--accent); }
.badge.downloading { background: rgba(210,153,34,0.2); color: var(--warn); }
.badge.done { background: rgba(63,185,80,0.2); color: var(--ok); }
.badge.failed { background: rgba(248,81,73,0.2); color: var(--bad); }
.error { color: var(--bad); font-size: 12px; margin-top: 8px; word-break: break-word; }
</style>
</head>
<body>
<header>
  <h1>SorterOS Kickoff</h1>
  <span class="target" id="target-name">—</span>
  <span style="flex:1"></span>
  <span class="badge idle" id="status-badge">idle</span>
</header>
<main>
  <div>
    <div class="panel">
      <h2>Build config</h2>
      <div class="row">
        <label>Branch (optional, defaults to .env)</label>
        <input type="text" id="branch" placeholder="e.g. spencer/foo-bar">
      </div>
      <div class="row">
        <label>Input image (on Hive)</label>
        <input type="text" id="in_path" placeholder="(extend.sh default v2.1 zst)">
      </div>
      <div class="row">
        <label>Output image name (on Hive, e.g. sorteros-v2.6-2026-05-17.img)</label>
        <input type="text" id="out_path" placeholder="(extend.sh default)">
      </div>
      <div class="row">
        <label><input type="checkbox" id="compress"> Compress with zstd before download (slow, ~30 min on Hive)</label>
      </div>
      <button id="go-btn">Start build</button>
      <div class="error" id="error-msg"></div>
    </div>
    <div class="panel" style="margin-top: 16px;">
      <h2>Stages</h2>
      <div class="stages" id="stages"></div>
    </div>
    <div class="panel" style="margin-top: 16px;">
      <h2>Download</h2>
      <div id="dl-text" style="font-size: 12px; color: var(--muted);">waiting…</div>
      <div class="progress"><div id="dl-bar"></div></div>
    </div>
  </div>
  <div class="panel">
    <h2>Live log</h2>
    <div class="log" id="log"></div>
  </div>
</main>
<script>
const stagesEl = document.getElementById('stages');
const logEl = document.getElementById('log');
const badge = document.getElementById('status-badge');
const targetEl = document.getElementById('target-name');
const dlText = document.getElementById('dl-text');
const dlBar = document.getElementById('dl-bar');
const errorEl = document.getElementById('error-msg');
const goBtn = document.getElementById('go-btn');

function fmtBytes(n) {
  if (n == null) return '?';
  const units = ['B', 'KiB', 'MiB', 'GiB'];
  let u = 0; let x = n;
  while (x >= 1024 && u < units.length - 1) { x /= 1024; u++; }
  return x.toFixed(2) + ' ' + units[u];
}

function render(state) {
  badge.textContent = state.status;
  badge.className = 'badge ' + state.status;
  targetEl.textContent = state.target_name || '';
  errorEl.textContent = state.error || '';
  goBtn.disabled = (state.status === 'building' || state.status === 'downloading');

  stagesEl.innerHTML = '';
  const order = {{STAGE_ORDER}};
  for (const name of order) {
    const status = state.stages[name] || 'pending';
    const div = document.createElement('div');
    div.className = 'stage ' + status;
    div.innerHTML = '<span>' + name.replace(/_/g, ' ') + '</span><span>' + status + '</span>';
    stagesEl.appendChild(div);
  }

  const expected = state.image_bytes_expected;
  const local = state.image_bytes_local;
  if (expected && expected > 0) {
    const pct = Math.min(100, (local / expected) * 100);
    dlBar.style.width = pct.toFixed(1) + '%';
    dlText.textContent = fmtBytes(local) + ' / ' + fmtBytes(expected) + ' (' + pct.toFixed(1) + '%) → ' + (state.image_local_path || '?');
  } else {
    dlBar.style.width = '0%';
    dlText.textContent = 'waiting…';
  }
}

function appendLog(line) {
  const wasAtBottom = (logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight) < 50;
  logEl.textContent += line + '\n';
  if (wasAtBottom) logEl.scrollTop = logEl.scrollHeight;
}

async function init() {
  const r = await fetch('/api/state');
  const state = await r.json();
  render(state);
  logEl.textContent = (state.log_lines || []).join('\n') + '\n';
  logEl.scrollTop = logEl.scrollHeight;

  const es = new EventSource('/api/events');
  es.onmessage = e => {
    const event = JSON.parse(e.data);
    if (event.type === 'log') appendLog(event.line);
    if (event.type === 'state') render(event.state);
  };
}

goBtn.onclick = async () => {
  const body = {
    branch: document.getElementById('branch').value.trim() || null,
    in_path: document.getElementById('in_path').value.trim() || null,
    out_path: document.getElementById('out_path').value.trim() || null,
    compress: document.getElementById('compress').checked,
  };
  const target = (body.out_path || '').match(/v\d+\.\d+/);
  body.target_name = target ? target[0] : '';
  const r = await fetch('/api/build', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  if (!r.ok) errorEl.textContent = (await r.json()).detail || 'build failed to start';
};

init();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    html = INDEX_HTML.replace("{{STAGE_ORDER}}", json.dumps(STAGES))
    return HTMLResponse(html)


@app.get("/api/state")
async def get_state():
    return serializable_state()


@app.post("/api/build")
async def post_build(payload: dict):
    with STATE_LOCK:
        if STATE.status in ("building", "downloading"):
            raise HTTPException(409, "another build is in progress")
    thread = threading.Thread(target=run_build, args=(payload or {},), daemon=True)
    thread.start()
    return {"ok": True}


@app.get("/api/events")
async def get_events():
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    SUBSCRIBERS.append(queue)

    async def stream():
        try:
            # Initial state push
            yield {"data": json.dumps({"type": "state", "state": serializable_state()})}
            while True:
                payload = await queue.get()
                yield {"data": payload}
        finally:
            if queue in SUBSCRIBERS:
                SUBSCRIBERS.remove(queue)

    return EventSourceResponse(stream())


load_state()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8780, log_level="info")
