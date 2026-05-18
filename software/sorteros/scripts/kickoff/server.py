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
import tomllib
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
BUILDS_DIR = pathlib.Path(__file__).parent / "builds"

STAGES = [
    "decompress",
    "node22_upgrade",
    "apt_cloud_init",
    "extract_ext4",
    "place_ext4",
    "partition_table",
    "format_fat",
    "fsck_ext4",
    "chroot_mount",
    "ap6275p",
    "ethernet_fallback",
    "iphone_hotspot",
    "tailscale",
    "blank_env",
    "branch_swap",
    "apply_network_config",
    "growfs_unit",
    "firstboot_units",
    "fat_seed",
    "image_ready",
    "downloading",
    "done",
]

STAGE_PATTERNS: list[tuple[str, str]] = [
    ("decompress",          r"decompressing|copying .* →"),
    ("node22_upgrade",      r"upgrading to node 22"),
    ("apt_cloud_init",      r"installing cloud-init"),
    ("extract_ext4",        r"extracting ext4 partition data"),
    ("place_ext4",          r"writing ext4 partition data back at offset"),
    ("partition_table",     r"rewriting MBR partition table"),
    ("format_fat",          r"formatting .* as FAT32"),
    ("fsck_ext4",           r"fsck of moved ext4 partition"),
    ("chroot_mount",        r"mounting rootfs \+ bind mounts for chroot"),
    ("ap6275p",             r"AP6275P Wi-Fi overlay"),
    ("ethernet_fallback",   r"installing ethernet link-local fallback"),
    ("iphone_hotspot",      r"installing fallback Wi-Fi"),
    ("tailscale",           r"TAILSCALE_AUTH_KEY present"),
    ("blank_env",           r"creating blank \.env"),
    ("branch_swap",         r"switching sorter-v2 checkout to branch"),
    ("apply_network_config",r"sorteros-apply-network-config"),
    ("growfs_unit",         r"sorteros-growfs"),
    ("firstboot_units",     r"installing split firstboot units"),
    ("fat_seed",            r"populating FAT partition"),
    ("image_ready",         r"image ready:"),
]


@dataclass
class BuildConfig:
    name: str
    slug: str                       # filename stem, used as ID
    branch: Optional[str] = None
    in_path: Optional[str] = None
    out_name: Optional[str] = None  # stem only; extend.sh appends date + .img
    updated_at: Optional[float] = None  # file mtime, unix timestamp


@dataclass
class BuildState:
    status: str = "idle"
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error: Optional[str] = None
    stages: dict[str, str] = field(default_factory=dict)
    log_lines: list[str] = field(default_factory=list)
    last_log_size: int = 0
    image_remote_path: Optional[str] = None
    image_local_path: Optional[str] = None
    image_bytes_expected: Optional[int] = None
    image_bytes_local: int = 0
    config: dict = field(default_factory=dict)
    target_name: Optional[str] = None
    finished_remote_log_tail: list[str] = field(default_factory=list)


STATE = BuildState()
STATE_LOCK = threading.RLock()
SUBSCRIBERS: list[asyncio.Queue] = []


def load_build_configs() -> list[BuildConfig]:
    configs: list[BuildConfig] = []
    if not BUILDS_DIR.exists():
        return configs
    for p in sorted(BUILDS_DIR.glob("*.toml")):
        try:
            data = tomllib.loads(p.read_text())
            configs.append(BuildConfig(
                name=data.get("name", p.stem),
                slug=p.stem,
                branch=data.get("branch"),
                in_path=data.get("in_path"),
                out_name=data.get("out_name"),
                updated_at=p.stat().st_mtime,
            ))
        except Exception:
            pass
    return configs


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


def ssh_cmd(remote_cmd: str) -> list[str]:
    return [
        "ssh", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=accept-new",
        f"{HIVE_USER}@{HIVE_HOST}", remote_cmd,
    ]


def run_build(cfg: BuildConfig) -> None:
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
        STATE.config = asdict(cfg)
        STATE.target_name = cfg.name
        STATE.finished_remote_log_tail = []
    persist_state()
    broadcast({"type": "state", "state": serializable_state()})

    try:
        flags: list[str] = []
        if cfg.in_path:
            flags += ["--in", cfg.in_path]
        if cfg.out_name:
            flags += ["--out", f"{OUT_DIR_REMOTE}/{cfg.out_name}.img"]
        if cfg.branch:
            flags += ["--branch", cfg.branch]

        flags_str = " ".join(shlex.quote(f) for f in flags)
        remote_log = f"{OUT_DIR_REMOTE}/extend.log"
        launch_cmd = (
            f"cd {BUILD_DIR_REMOTE} && "
            f"nohup bash extend.sh {flags_str} > {remote_log} 2>&1 & "
            f"disown; echo started"
        )
        push_log(f"[kickoff] launching: extend.sh {flags_str}")
        result = subprocess.run(ssh_cmd(launch_cmd), capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"launch failed: {result.stderr.strip()}")

        # Poll remote log until image ready
        idle_loops = 0
        while True:
            time.sleep(2)
            still_running = subprocess.run(
                ssh_cmd('pgrep -f "bash extend.sh" >/dev/null && echo yes || echo no'),
                capture_output=True, text=True, timeout=15,
            ).stdout.strip()

            tail_proc = subprocess.run(
                ssh_cmd(
                    f"wc -c {remote_log} | awk '{{print $1}}'; "
                    f"tail -c +$(({STATE.last_log_size}+1)) {remote_log}"
                ),
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
                raise RuntimeError("extend.sh exited without producing an image; see log")
            if idle_loops > 90:
                raise RuntimeError("build appears stuck (no log activity for 3 min)")

        m = re.search(r"image ready: (\S+)", "\n".join(STATE.log_lines))
        if not m:
            raise RuntimeError("couldn't parse image path from log")
        remote_img = m.group(1)
        with STATE_LOCK:
            STATE.image_remote_path = remote_img
        set_stage("image_ready", "done")

        # Get raw image size for progress tracking
        sz_proc = subprocess.run(
            ssh_cmd(f"stat -c %s {shlex.quote(remote_img)}"),
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

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        local_path = DOWNLOADS_DIR / pathlib.Path(remote_img).name
        if local_path.exists():
            local_path.unlink()
        with STATE_LOCK:
            STATE.image_local_path = str(local_path)
        push_log(f"[kickoff] downloading via zstd pipe → {local_path}")
        set_stage("downloading", "running")

        # Stream: ssh | zstd -3 -T0 -c  →  zstd -d -o local
        # Much faster than scp -C: zstd-3 compresses ~5-10x better than zlib
        # and decompresses at ~1 GB/s locally. No compressed copy stored on Hive.
        ssh_proc = subprocess.Popen(
            ssh_cmd(f"zstd -3 -T0 -c {shlex.quote(remote_img)}"),
            stdout=subprocess.PIPE,
        )
        zstd_proc = subprocess.Popen(
            ["zstd", "-d", "-o", str(local_path), "-f"],
            stdin=ssh_proc.stdout,
        )
        if ssh_proc.stdout:
            ssh_proc.stdout.close()

        while zstd_proc.poll() is None:
            time.sleep(1)
            if local_path.exists():
                with STATE_LOCK:
                    STATE.image_bytes_local = local_path.stat().st_size
                broadcast({"type": "state", "state": serializable_state()})

        ssh_proc.wait()
        if zstd_proc.returncode != 0:
            raise RuntimeError(f"download pipeline failed (zstd exit {zstd_proc.returncode})")
        if ssh_proc.returncode != 0:
            raise RuntimeError(f"download pipeline failed (ssh exit {ssh_proc.returncode})")

        with STATE_LOCK:
            STATE.image_bytes_local = local_path.stat().st_size
            STATE.status = "done"
            STATE.finished_at = time.time()
        set_stage("downloading", "done")
        set_stage("done", "done")
        push_log(f"[kickoff] complete — {local_path} ({STATE.image_bytes_local:,} bytes)")

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
header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 12px; }
header h1 { font-size: 18px; margin: 0; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.badge.idle       { background: var(--border); color: var(--muted); }
.badge.building   { background: rgba(88,166,255,0.2); color: var(--accent); }
.badge.downloading{ background: rgba(210,153,34,0.2); color: var(--warn); }
.badge.done       { background: rgba(63,185,80,0.2); color: var(--ok); }
.badge.failed     { background: rgba(248,81,73,0.2); color: var(--bad); }
main { display: grid; grid-template-columns: 340px 1fr; gap: 16px; padding: 16px 24px; }
.panel { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
.panel h2 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 10px; }
.build-list { display: flex; flex-direction: column; gap: 6px; }
.build-card {
  padding: 10px 12px; border-radius: 6px; border: 1px solid var(--border);
  cursor: pointer; transition: border-color .15s, background .15s;
  user-select: none;
}
.build-card:hover { border-color: var(--accent); }
.build-card.selected { border-color: var(--accent); background: rgba(88,166,255,0.08); }
.build-card.selected .card-name { color: var(--accent); }
.card-name { font-size: 13px; font-weight: 600; }
.card-meta { font-size: 11px; color: var(--muted); margin-top: 3px; }
.empty-builds { font-size: 12px; color: var(--muted); padding: 8px 0; }
button#go-btn {
  margin-top: 12px; width: 100%; padding: 9px;
  background: var(--accent); color: #0e1116;
  border: 0; border-radius: 6px; font-weight: 700; font-size: 14px;
  cursor: pointer;
}
button#go-btn:disabled { background: var(--border); color: var(--muted); cursor: not-allowed; }
.error { color: var(--bad); font-size: 12px; margin-top: 8px; word-break: break-word; }
.stages { display: flex; flex-direction: column; gap: 3px; }
.stage { display: flex; justify-content: space-between; padding: 3px 8px; border-radius: 4px; font-size: 11px; }
.stage.pending { color: var(--muted); }
.stage.running { background: rgba(88,166,255,0.12); color: var(--accent); }
.stage.done { color: var(--ok); }
.progress { height: 5px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 6px; }
.progress > div { height: 100%; background: var(--accent); width: 0%; transition: width 0.4s; }
#dl-text { font-size: 11px; color: var(--muted); margin-top: 4px; }
.log {
  background: #0e1116; border: 1px solid var(--border); border-radius: 4px;
  padding: 8px; font-family: ui-monospace, monospace; font-size: 11px;
  color: #c9d1d9; height: 520px; overflow-y: scroll;
  white-space: pre-wrap; word-break: break-all;
}
</style>
</head>
<body>
<header>
  <h1>SorterOS Kickoff</h1>
  <span class="badge idle" id="status-badge">idle</span>
  <span style="flex:1"></span>
  <span id="target-name" style="font-size:13px;color:var(--muted)"></span>
</header>
<main>
  <div>
    <div class="panel">
      <h2>Select build</h2>
      <div class="build-list" id="build-list">
        <div class="empty-builds">Loading…</div>
      </div>
      <button id="go-btn" disabled>Start build</button>
      <div class="error" id="error-msg"></div>
    </div>
    <div class="panel" style="margin-top:14px;">
      <h2>Stages</h2>
      <div class="stages" id="stages"></div>
    </div>
    <div class="panel" style="margin-top:14px;">
      <h2>Download</h2>
      <div class="progress"><div id="dl-bar"></div></div>
      <div id="dl-text">waiting…</div>
    </div>
  </div>
  <div class="panel">
    <h2>Live log</h2>
    <div class="log" id="log"></div>
  </div>
</main>
<script>
const stagesEl  = document.getElementById('stages');
const logEl     = document.getElementById('log');
const badge     = document.getElementById('status-badge');
const targetEl  = document.getElementById('target-name');
const dlText    = document.getElementById('dl-text');
const dlBar     = document.getElementById('dl-bar');
const errorEl   = document.getElementById('error-msg');
const goBtn     = document.getElementById('go-btn');
const listEl    = document.getElementById('build-list');

let configs     = [];
let selectedSlug = null;

function fmtBytes(n) {
  if (n == null) return '?';
  const units = ['B','KiB','MiB','GiB'];
  let u = 0, x = n;
  while (x >= 1024 && u < units.length-1) { x /= 1024; u++; }
  return x.toFixed(1) + ' ' + units[u];
}

function renderConfigs() {
  if (!configs.length) {
    listEl.innerHTML = '<div class="empty-builds">No build configs found in builds/</div>';
    return;
  }
  listEl.innerHTML = '';
  for (const c of configs) {
    const card = document.createElement('div');
    card.className = 'build-card' + (selectedSlug === c.slug ? ' selected' : '');
    card.dataset.slug = c.slug;
    const meta = [c.branch && ('branch: ' + c.branch), c.in_path && ('in: ' + c.in_path.split('/').pop())].filter(Boolean).join(' · ');
    const ts = c.updated_at ? new Date(c.updated_at * 1000).toLocaleString() : '';
    card.innerHTML = '<div class="card-name">' + c.name + '</div>'
      + '<div class="card-meta">'
      + (meta ? meta + (ts ? ' · ' : '') : '')
      + (ts ? 'updated ' + ts : '')
      + '</div>';
    card.onclick = () => {
      selectedSlug = c.slug;
      renderConfigs();
      goBtn.disabled = (document.getElementById('status-badge').textContent === 'building' ||
                        document.getElementById('status-badge').textContent === 'downloading');
    };
    listEl.appendChild(card);
  }
}

function render(state) {
  badge.textContent = state.status;
  badge.className   = 'badge ' + state.status;
  targetEl.textContent = state.target_name || '';
  errorEl.textContent  = state.error || '';

  const busy = state.status === 'building' || state.status === 'downloading';
  goBtn.disabled = busy || !selectedSlug;

  stagesEl.innerHTML = '';
  const order = {{STAGE_ORDER}};
  for (const name of order) {
    const st = state.stages[name] || 'pending';
    const div = document.createElement('div');
    div.className = 'stage ' + st;
    div.innerHTML = '<span>' + name.replace(/_/g,' ') + '</span><span>' + st + '</span>';
    stagesEl.appendChild(div);
  }

  const exp = state.image_bytes_expected, loc = state.image_bytes_local;
  if (exp && exp > 0) {
    const pct = Math.min(100, (loc/exp)*100);
    dlBar.style.width = pct.toFixed(1)+'%';
    dlText.textContent = fmtBytes(loc) + ' / ' + fmtBytes(exp) + ' (' + pct.toFixed(1)+'%) → ' + (state.image_local_path||'?');
  } else {
    dlBar.style.width = '0%';
    dlText.textContent = 'waiting…';
  }
}

function appendLog(line) {
  const atBottom = (logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight) < 50;
  logEl.textContent += line + '\n';
  if (atBottom) logEl.scrollTop = logEl.scrollHeight;
}

goBtn.onclick = async () => {
  if (!selectedSlug) return;
  errorEl.textContent = '';
  const r = await fetch('/api/build', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({slug: selectedSlug}),
  });
  if (!r.ok) errorEl.textContent = (await r.json()).detail || 'failed to start';
};

async function init() {
  // Load build configs
  const cr = await fetch('/api/configs');
  configs = await cr.json();
  if (configs.length) selectedSlug = configs[0].slug;
  renderConfigs();
  goBtn.disabled = !selectedSlug;

  // Load current state
  const sr = await fetch('/api/state');
  const state = await sr.json();
  render(state);
  logEl.textContent = (state.log_lines||[]).join('\n') + '\n';
  logEl.scrollTop = logEl.scrollHeight;

  // SSE
  const es = new EventSource('/api/events');
  es.onmessage = e => {
    const ev = JSON.parse(e.data);
    if (ev.type === 'log')   appendLog(ev.line);
    if (ev.type === 'state') render(ev.state);
  };
}

init();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(INDEX_HTML.replace("{{STAGE_ORDER}}", json.dumps(STAGES)))


@app.get("/api/configs")
async def get_configs():
    return [asdict(c) for c in load_build_configs()]


@app.get("/api/state")
async def get_state():
    return serializable_state()


@app.post("/api/build")
async def post_build(payload: dict):
    with STATE_LOCK:
        if STATE.status in ("building", "downloading"):
            raise HTTPException(409, "another build is in progress")

    slug = payload.get("slug")
    if not slug:
        raise HTTPException(400, "slug required")

    configs = load_build_configs()
    cfg = next((c for c in configs if c.slug == slug), None)
    if cfg is None:
        raise HTTPException(404, f"no build config with slug {slug!r}")

    thread = threading.Thread(target=run_build, args=(cfg,), daemon=True)
    thread.start()
    return {"ok": True}


@app.get("/api/events")
async def get_events():
    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    SUBSCRIBERS.append(queue)

    async def stream():
        try:
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
