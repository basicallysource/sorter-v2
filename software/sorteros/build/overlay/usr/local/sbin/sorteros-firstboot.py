"""
SorterOS firstboot daemon.

Type=simple background service. Loops every 60s. Each stage is idempotent
and guarded by a stamp file. Stages that need internet just skip themselves
and retry next iteration when offline — boot is NEVER blocked, errors are
NEVER fatal.

The stages up to install-services are what it takes to run the Sorter UI.
Once those are done the backend starts, and when it answers the progress page
hands port 80 to the UI, even if a later stage (Tailscale) is still retrying
or has given up. A later stage that
keeps failing stops after LATE_STAGE_MAX_FAILURES tries so a bad key doesn't
retry forever.

When every stage is done or given up, the daemon exits 0 and systemd stops
restarting it (RestartPreventExitStatus=0 in the unit).
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import logging
import os
import random
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

# Keep these lists in sync with the Sorter backend's server/machine_naming.py,
# which draws Hive machine names from the same vocabulary.
LEGO_COLORS = [
    "aqua", "azure", "black", "blue", "bright-green", "bright-pink",
    "brown", "coral", "dark-azure", "dark-blue", "dark-brown", "dark-gray",
    "dark-green", "dark-orange", "dark-pink", "dark-purple", "dark-red",
    "dark-tan", "dark-turquoise", "gray", "green", "lavender", "light-aqua",
    "light-blue", "light-gray", "light-pink", "light-purple", "light-yellow",
    "lime", "magenta", "medium-azure", "medium-blue", "medium-green",
    "medium-lavender", "medium-nougat", "nougat", "olive", "orange", "pink",
    "purple", "red", "reddish-brown", "sand-blue", "sand-green", "tan",
    "teal", "warm-gold", "white", "yellow",
]

LEGO_PIECES = [
    "antenna", "arch", "axle", "baseplate", "beam", "bracket", "brick",
    "bushing", "clip", "cone", "cylinder", "dish", "dome", "door", "fence",
    "flag", "gear", "grille", "hinge", "hose", "jumper", "ladder", "lever",
    "minifig", "panel", "pin", "plate", "propeller", "rail", "ramp", "rod",
    "roof", "slope", "sprocket", "stud", "technic", "tile", "tube",
    "turntable", "wedge", "wheel", "windscreen", "wing",
]

# tomllib is stdlib on Python 3.11+; Ubuntu Jammy ships 3.10 so we fall
# back to the python3-tomli apt package (drop-in API-compatible).
try:
    import tomllib  # type: ignore
except ImportError:
    import tomli as tomllib  # type: ignore

STAMP_DIR = Path("/var/lib/sorteros")
CONFIG_PATH = Path("/etc/sorteros-config.toml")
REF_PATH = Path("/etc/sorteros/ref")
STATUS_PORT = 80
REPO_URL = "https://github.com/basicallysource/sorter-v2"
REPO_DIR = Path("/home/orangepi/sorter-v2")
SOFTWARE_DIR = REPO_DIR / "software"
# The image bakes "stable" into REF_PATH: check out the newest release tag in
# the stable channel, the same tags the Sorter UI's Versions page updates to.
# A test image may bake a branch, tag or commit instead.
STABLE_REF = "stable"
STABLE_TAG_PREFIX = "sorter/stable/v"
POLL_INTERVAL = 60
WAITING_POLL_INTERVAL = 10  # waiting for the internet: a phone may be putting it on Wi-Fi right now
SOFTWARE_STATUS = Path("/run/sorteros/software.json")  # read by the setup page
LATE_STAGE_MAX_FAILURES = 10
DOCS_URL = "https://docs.basically.website/sorter/installation/sorter-os/"
INTERNET_PROBE_HOSTS = ("deb.debian.org", "github.com")
INTERNET_PROBE_TIMEOUT = 5
BACKEND_HEALTH_URL = "http://127.0.0.1:8000/health"
BACKEND_START_TIMEOUT = 600


log = logging.getLogger("sorteros-firstboot")


@dataclass
class Stage:
    name: str
    needs_internet: bool
    run: Callable[[], None]
    # False for stages that run after the UI is up and may give up.
    before_ui: bool = True


# ─── progress page ─────────────────────────────────────────────────────────
#
# While first boot runs, port 80 shows what it is doing, so a browser pointed
# at the machine sees progress instead of ERR_CONNECTION_REFUSED. It follows
# the Sorter UI's style guide (software/sorter/frontend/AGENTS.md and its
# /styleguide), as the setup page does, with the same two differences: system
# fonts, and dark mode from the browser. Everything is inline: the page must
# work with nothing else on the machine answering yet.
#
# When everything the UI needs is in place the backend starts first, while
# this page keeps port 80. Once the backend answers, the page gives port 80 to
# the UI, and the copy still open in the browser, which polls, opens the UI as
# soon as it answers. It never offers a link to a UI that isn't there yet.

_state_lock = threading.Lock()
_stage_state: dict[str, dict] = {}
_runtime: dict = {"net": False, "started_at": time.time(), "starting_since": None}


STEP_WORDS = {
    "ssh-host-keys": "Making the machine's keys",
    "grow-rootfs": "Growing the disk",
    "setup-swap": "Making swap",
    "clone-repo": "Downloading the Sorter software",
    "write-env": "Configuring",
    "write-machine-toml": "Configuring",
    "uv-sync": "Installing Python packages",
    "pnpm-install": "Installing the interface's packages",
    "pnpm-build": "Building the interface",
    "install-services": "Starting the Sorter",
}

PHASE_WORDS = {
    "installing": ("Installing the Sorter",
                   "This takes a few minutes. This page opens the Sorter UI when it's ready."),
    "waiting": ("Waiting for the internet",
                "The Sorter needs the internet to install its software. It carries on as soon as it's online."),
    "starting": ("Starting the Sorter",
                 "It's installed. This page opens the Sorter UI as soon as it answers, in a minute or two."),
}

WAITING_FOR_INTERNET = "waiting for internet"


def _set_state(name: str, status: str, info: str = "") -> None:
    with _state_lock:
        prev = _stage_state.get(name, {})
        _stage_state[name] = {
            "status": status,
            "info": info,
            "started_at": time.time() if status == "active" and prev.get("status") != "active" else prev.get("started_at"),
        }
        software = _software_status()
    try:
        SOFTWARE_STATUS.parent.mkdir(parents=True, exist_ok=True)
        tmp = SOFTWARE_STATUS.with_name(".software.json.tmp")
        tmp.write_text(json.dumps(software))
        os.replace(tmp, SOFTWARE_STATUS)
    except OSError as e:
        log.warning("couldn't write %s: %s", SOFTWARE_STATUS, e)


def _software_status() -> dict:
    """How far the install of the Sorter software is, for the setup page:
    waiting (for the internet), installing, or ready."""
    needed = [s for s in STAGES if s.before_ui]
    done = sum(1 for s in needed if _stage_state.get(s.name, {}).get("status") == "done")
    nxt = next((s for s in needed if _stage_state.get(s.name, {}).get("status") != "done"), None)
    if nxt is None:
        return {"state": "ready", "step": None, "done": done, "total": len(needed)}
    waiting = _stage_state.get(nxt.name, {}).get("info") == WAITING_FOR_INTERNET
    return {"state": "waiting" if waiting else "installing", "step": STEP_WORDS.get(nxt.name, nxt.name),
            "done": done, "total": len(needed)}


def _read_meta() -> tuple[str, str, str]:
    hostname = socket.gethostname() or "sorter"
    version = "dev"
    try:
        version = Path("/etc/sorteros/version").read_text().strip()
    except OSError:
        pass
    return hostname, version, _checked_out_ref() or _baked_ref()


def _baked_ref() -> str:
    try:
        return REF_PATH.read_text().strip() or STABLE_REF
    except OSError:
        return STABLE_REF


def _checked_out_ref() -> str | None:
    try:
        return (STAMP_DIR / "checked-out-ref").read_text().strip() or None
    except OSError:
        return None


def _elapsed(since: float | None) -> str:
    if not since:
        return ""
    mins, secs = divmod(max(0, int(time.time() - since)), 60)
    return f"{mins}m {secs:02d}s" if mins else f"{secs}s"


def _progress() -> dict:
    """Everything the page shows, from one look at the state."""
    hostname, version, ref = _read_meta()
    with _state_lock:
        snapshot = {k: dict(v) for k, v in _stage_state.items()}
        starting_since = _runtime.get("starting_since")
        net = _runtime.get("net", False)

    needed = [s for s in STAGES if s.before_ui]
    nxt = next((s for s in needed if snapshot.get(s.name, {}).get("status") != "done"), None)
    if starting_since or nxt is None:
        phase = "starting"
    elif snapshot.get(nxt.name, {}).get("info") == WAITING_FOR_INTERNET:
        phase = "waiting"
    else:
        phase = "installing"

    # One row per description, so the two Configuring stages are one row.
    rows: list[dict] = []
    for s in needed:
        words = STEP_WORDS.get(s.name, s.name)
        if rows and rows[-1]["words"] == words:
            rows[-1]["stages"].append(s.name)
        else:
            rows.append({"words": words, "stages": [s.name]})
    for row in rows:
        states = [snapshot.get(n, {}) for n in row["stages"]]
        # A stage that waits on an earlier one says "… yet"; that is not a failure.
        errors = [st.get("info") for st in states
                  if st.get("status") in ("waiting", "failed") and st.get("info")
                  and st.get("info") != WAITING_FOR_INTERNET and not st.get("info", "").endswith(" yet")]
        active = next((st for st in states if st.get("status") == "active"), None)
        if "install-services" in row["stages"] and starting_since:
            row["state"], row["detail"] = "active", _elapsed(starting_since)
        elif all(st.get("status") == "done" for st in states):
            row["state"], row["detail"] = "done", ""
        elif active is not None:
            row["state"], row["detail"] = "active", _elapsed(active.get("started_at"))
        elif errors:
            row["state"], row["detail"] = "retrying", errors[0]
        elif any(st.get("info") == WAITING_FOR_INTERNET for st in states):
            row["state"], row["detail"] = "waiting", "Waiting for the internet"
        else:
            row["state"], row["detail"] = "pending", ""

    return {
        "phase": phase,
        "hostname": hostname,
        "version": version,
        "ref": ref,
        "online": net,
        "rows": rows,
        "stages": [{"name": s.name,
                    "state": snapshot.get(s.name, {}).get("status", "pending"),
                    "info": snapshot.get(s.name, {}).get("info") or ""} for s in STAGES],
    }


_ICONS = {
    "done": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>',
    "retrying": '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
    "waiting": '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
    "pending": '<i aria-hidden="true"></i>',
}


def _spinner(size: int) -> str:
    return (f'<span class="spinner" style="--s:{size}px" role="status" aria-label="Working">'
            '<i></i><i></i><i></i><i></i></span>')


# The Sorter UI's tokens (software/sorter/frontend/src/routes/layout.css).
PAGE_CSS = """
:root{--bg:#f7f6f3;--surface:#fff;--border:#e2e0db;--text:#1a1a1a;--muted:#7a7770;--primary:#0055bf;
--success:#00852b;--danger:#d01012;--edge:inset 0 1px 0 rgba(255,255,255,.9);color-scheme:light;
--sans:'IBM Plex Sans',ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;
--mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,'Liberation Mono',monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0d0d0c;--surface:#1a1918;--border:#2a2926;--text:#f5f4f1;
--muted:#9a9890;--edge:inset 0 1px 0 rgba(255,255,255,.04);color-scheme:dark}}
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);line-height:1.5;-webkit-text-size-adjust:100%}
h1,h2,p,ol{margin:0}
.wrap{max-width:28rem;margin:0 auto;padding-left:1rem;padding-right:1rem}
header{background:var(--surface);border-bottom:1px solid var(--border)}
header .wrap{display:flex;align-items:center;justify-content:space-between;gap:.75rem;padding-top:.75rem;padding-bottom:.75rem}
.brand{display:flex;align-items:center;gap:.625rem;font-family:var(--mono);font-size:1.125rem;line-height:1.75rem;
font-weight:700;letter-spacing:-.025em;text-transform:uppercase}
.brand i{width:1rem;height:1rem;flex:none;background:var(--primary)}
.chip{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border:1px solid var(--border);
padding:.25rem .625rem;font-size:.875rem;line-height:1.25rem;font-weight:500;color:var(--muted)}
main{display:flex;flex-direction:column;gap:1.5rem;padding-top:1.5rem;padding-bottom:4rem}
.panel{border:1px solid var(--border);background:var(--surface);box-shadow:var(--edge),0 1px 2px rgba(32,28,20,.04)}
.hero{display:flex;flex-direction:column;align-items:center;gap:1.25rem;padding:2.5rem 1.5rem;text-align:center;color:var(--primary)}
.hero h1{color:var(--text);font-size:1.5rem;line-height:2rem;font-weight:700}
.hero p{margin-top:.5rem;color:var(--muted);font-size:.875rem;line-height:1.25rem;text-wrap:balance}
.label-row{display:flex;align-items:baseline;justify-content:space-between;gap:.75rem;margin-bottom:.75rem}
.label{font-size:.75rem;line-height:1rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
.count{font-size:.875rem;line-height:1.25rem;color:var(--muted);font-variant-numeric:tabular-nums}
.steps{list-style:none;padding:0}
.steps li{display:flex;align-items:flex-start;gap:.75rem;padding:.75rem 1rem;border-top:1px solid var(--border);
font-size:.875rem;line-height:1.25rem}
.steps li:first-child{border-top:0}
.icon{flex:none;display:flex;align-items:center;justify-content:center;width:1rem;height:1.25rem}
.words{flex:1;min-width:0}
.detail{flex:none;color:var(--muted);font-weight:400;font-variant-numeric:tabular-nums}
.error{display:block;margin-top:.25rem;color:var(--danger);font-weight:400;overflow-wrap:anywhere}
.done .icon{color:var(--success)}
.active{font-weight:600}
.active .icon{color:var(--primary)}
.pending,.waiting{color:var(--muted)}
.pending .icon i{width:.625rem;height:.625rem;border:1px solid currentColor}
.retrying .icon{color:var(--danger)}
svg{width:1rem;height:1rem;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.foot{display:flex;flex-direction:column;gap:.25rem;font-size:.875rem;line-height:1.25rem;color:var(--muted)}
.foot a{color:var(--primary)}
code{font-family:var(--mono);font-size:.875rem;overflow-wrap:anywhere}
.opening{display:none}
[data-opening] .opening{display:flex}
[data-opening] .phase{display:none}
.spinner{position:relative;display:inline-block;flex:none;width:var(--s);height:var(--s)}
.spinner i{position:absolute;width:42%;height:42%;background:currentColor;opacity:.2;animation:quarter .667s linear infinite}
.spinner i:nth-child(1){top:0;left:0}
.spinner i:nth-child(2){top:0;right:0;animation-delay:.1667s}
.spinner i:nth-child(3){bottom:0;right:0;animation-delay:.3333s}
.spinner i:nth-child(4){bottom:0;left:0;animation-delay:.5s}
@keyframes quarter{0%,24%{opacity:1}25%,100%{opacity:.2}}
"""

# Polls the page and swaps in the fresh <main>. While port 80 changes hands
# nothing answers for a moment; then the first answer that isn't this page is
# the Sorter UI, and the page reloads into it.
PAGE_JS = """
(function () {
  var root = document.documentElement;
  function tick() {
    fetch(location.pathname, { cache: 'no-store' }).then(function (r) {
      return r.text().then(function (html) {
        if (html.indexOf('data-firstboot') !== -1) {
          var doc = new DOMParser().parseFromString(html, 'text/html');
          var fresh = doc.querySelector('main');
          var main = document.querySelector('main');
          if (fresh && main) main.replaceWith(fresh);
          document.title = doc.title;
          root.removeAttribute('data-opening');
        } else if (r.ok) {
          location.reload();
          return true;
        }
      });
    }, function () {
      root.setAttribute('data-opening', '');
    }).then(function (reloading) {
      if (!reloading) setTimeout(tick, 2000);
    });
  }
  setTimeout(tick, 2000);
})();
"""


def _render_status_page() -> bytes:
    p = _progress()
    esc = _html.escape
    headline, lede = PHASE_WORDS[p["phase"]]
    rows = []
    for row in p["rows"]:
        state, detail = row["state"], row["detail"]
        icon = _spinner(16) if state == "active" else _ICONS[state]
        side = f'<span class="detail">{esc(detail)}</span>' if state in ("active", "waiting") and detail else ""
        error = f'<span class="error">Failed, trying again: {esc(detail)}</span>' if state == "retrying" else ""
        rows.append(f'<li class="{state}"><span class="icon">{icon}</span>'
                    f'<span class="words">{esc(row["words"])}{error}</span>{side}</li>')
    done = sum(1 for row in p["rows"] if row["state"] == "done")
    page = (
        '<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{esc(headline)} · {esc(p["hostname"])}</title>'
        '<noscript><meta http-equiv="refresh" content="5"></noscript>'
        f'<style>{PAGE_CSS}</style></head><body>'
        '<header><div class="wrap"><span class="brand"><i aria-hidden="true"></i>Sorter</span>'
        f'<span class="chip">{esc(p["hostname"])}</span></div></header>'
        f'<main class="wrap" data-firstboot="{p["phase"]}">'
        f'<section class="panel hero phase">{_spinner(32)}'
        f'<div><h1>{esc(headline)}</h1><p>{esc(lede)}</p></div></section>'
        f'<section class="panel hero opening">{_spinner(32)}'
        '<div><h1>Opening the Sorter UI</h1><p>It takes a few seconds.</p></div></section>'
        '<section class="phase"><div class="label-row"><h2 class="label">Steps</h2>'
        f'<span class="count">{done} of {len(p["rows"])} done</span></div>'
        f'<ol class="panel steps">{"".join(rows)}</ol></section>'
        f'<footer class="foot phase"><p>SorterOS {esc(p["version"])} · {esc(p["ref"])}</p>'
        f'<p>Stuck? See <a href="{esc(DOCS_URL)}#debugging">Debugging</a> in the install guide.</p>'
        '<p>Live log: <code>journalctl -fu sorteros-firstboot</code></p></footer>'
        '</main>'
        f'<script>{PAGE_JS}</script></body></html>'
    )
    return page.encode("utf-8")


def _status_json() -> bytes:
    p = _progress()
    return json.dumps({k: p[k] for k in ("phase", "hostname", "version", "ref", "online", "stages")}).encode()


class _StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler convention)
        if self.path == "/":
            body, kind = _render_status_page(), "text/html; charset=utf-8"
        elif self.path == "/status.json":
            body, kind = _status_json(), "application/json"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args, **_kw) -> None:  # noqa: N802
        return  # silence default access log


def _start_status_server(port: int) -> ThreadingHTTPServer | None:
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", port), _StatusHandler)
    except OSError as e:
        log.warning("status server: cannot bind port %d (%s) — skipping", port, e)
        return None
    threading.Thread(target=srv.serve_forever, name="status-http", daemon=True).start()
    log.info("status server on http://0.0.0.0:%d", port)
    return srv


def _keep_status_server(ui_ready: threading.Event) -> None:
    """Serve the progress page on :80 until the UI takes the port. (The setup
    network's port 80 is redirected to the setup page, so it never needs it.)"""
    server = None
    while server is None and not ui_ready.is_set():
        server = _start_status_server(STATUS_PORT)
        if server is None:
            ui_ready.wait(5)
    ui_ready.wait()
    if server is not None:
        server.shutdown()
        server.server_close()
        log.info("released port %d", STATUS_PORT)


def internet_up() -> bool:
    for host in INTERNET_PROBE_HOSTS:
        try:
            socket.create_connection((host, 443), timeout=INTERNET_PROBE_TIMEOUT).close()
            return True
        except OSError:
            continue
    return False


def sh(cmd: list[str], **kw) -> None:
    log.info("$ %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, **kw)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{cmd[0]} timed out") from None
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {r.returncode}")


def _hostname() -> str:
    p = Path("/etc/hostname")
    return p.read_text().strip() if p.exists() else "sorter"


def _mac_suffix() -> str:
    net = Path("/sys/class/net")
    for iface in sorted(net.iterdir()):
        if iface.name == "lo":
            continue
        addr_file = iface / "address"
        if addr_file.exists():
            mac = addr_file.read_text().strip().replace(":", "")
            if mac and mac != "000000000000":
                return mac[-6:].lower()
    return format(random.randint(0, 0xFFFFFF), "06x")


def _generate_machine_name() -> str:
    color = random.choice(LEGO_COLORS)
    piece = random.choice(LEGO_PIECES)
    suffix = _mac_suffix()
    return f"sorter-{color}-{piece}-{suffix}"


def stage_ssh_host_keys() -> None:
    if list(Path("/etc/ssh").glob("ssh_host_*_key")):
        return
    sh(["ssh-keygen", "-A"])


def stage_grow_rootfs() -> None:
    # Find the block device mounted at /.
    root_dev = None
    for line in Path("/proc/mounts").read_text().splitlines():
        cols = line.split()
        if len(cols) >= 2 and cols[1] == "/":
            root_dev = cols[0]
            break
    if not root_dev or not root_dev.startswith("/dev/"):
        raise RuntimeError(f"unexpected root device: {root_dev}")

    # Split device + partition number.
    # mmcblk/nvme:  /dev/mmcblk1p1  → disk=/dev/mmcblk1, part=1
    # sd*:          /dev/sda1        → disk=/dev/sda,     part=1
    m = re.match(r"^(/dev/(?:mmcblk|nvme)\w+?)p(\d+)$", root_dev)
    if not m:
        m = re.match(r"^(/dev/[a-z]+)(\d+)$", root_dev)
    if not m:
        raise RuntimeError(f"cannot parse root device: {root_dev}")
    disk, part_num = m.group(1), m.group(2)

    # growpart expands the partition to fill the disk. Exit 1 = already full (OK).
    r = subprocess.run(["growpart", disk, part_num], capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(f"growpart failed ({r.returncode}): {r.stderr.strip()}")

    # resize2fs can resize a mounted ext4 filesystem online on modern kernels.
    sh(["resize2fs", root_dev])


# Split so the setup site, which scans the raw image for the marker lines,
# never finds them in this file.
CFG_END_MARKER = "# __SORTEROS_CFG" + "_END__"
CONFIG_APPLIED = STAMP_DIR / "config-applied"


def _read_config() -> tuple[str, dict]:
    """/etc/sorteros-config.toml as (text, parsed), minus the setup site's
    placeholder padding. Written by the setup site before flashing and by the
    setup page on the device."""
    try:
        raw = CONFIG_PATH.read_text("utf-8", errors="replace")
    except OSError:
        return "", {}
    if CFG_END_MARKER in raw:
        raw = raw[: raw.index(CFG_END_MARKER)]
    try:
        return raw, tomllib.loads(raw)
    except Exception as e:
        log.warning("config toml unreadable: %s", e)
        return raw, {}


def apply_config_if_changed() -> None:
    """Apply the setup config whenever its contents change: once at first
    boot for what the setup site wrote, again if the setup page on the device
    adds a hostname or SSH key later. Wi-Fi is sorteros-network's job.
      hostname              → system hostname (avahi announces <name>.local)
      timezone              → system time zone (the vendor image says Asia/Shanghai)
      [ssh].authorized_key  → orangepi's authorized_keys
      [tailscale].auth_key  → stored for stage_tailscale_up
    """
    raw, cfg = _read_config()
    digest = hashlib.sha256(raw.encode()).hexdigest()
    try:
        if CONFIG_APPLIED.read_text().strip() == digest:
            return
    except OSError:
        pass

    hostname = cfg.get("hostname")
    if isinstance(hostname, str) and hostname.strip() and hostname.strip() != socket.gethostname():
        log.info("setting hostname: %s", hostname)
        sh(["hostnamectl", "set-hostname", hostname.strip()])
        # avahi keeps announcing the old <name>.local until it restarts
        subprocess.run(["systemctl", "try-restart", "avahi-daemon.service"], check=False)

    timezone = cfg.get("timezone")
    if isinstance(timezone, str) and re.fullmatch(r"[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)*", timezone) \
            and (Path("/usr/share/zoneinfo") / timezone).is_file():
        log.info("setting time zone: %s", timezone)
        sh(["timedatectl", "set-timezone", timezone])

    key = (cfg.get("ssh") or {}).get("authorized_key")
    if isinstance(key, str) and key.strip():
        _append_authorized_key(key.strip())

    ts_block = cfg.get("tailscale") or {}
    ts_key = ts_block.get("auth_key")
    ts_tags = ts_block.get("tags", "tag:sorter")
    if isinstance(ts_key, str) and ts_key.strip():
        ts_env = Path("/etc/sorteros/tailscale.env")
        ts_env.parent.mkdir(parents=True, exist_ok=True)
        ts_env.write_text(f"TAILSCALE_AUTH_KEY={ts_key.strip()}\nTAILSCALE_TAGS={ts_tags}\n")
        ts_env.chmod(0o600)
        log.info("tailscale auth key written from config")

    CONFIG_APPLIED.write_text(digest + "\n")


def _append_authorized_key(key: str) -> None:
    ssh_dir = Path("/home/orangepi/.ssh")
    ssh_dir.mkdir(parents=True, exist_ok=True)
    sh(["chown", "orangepi:orangepi", str(ssh_dir)])
    ssh_dir.chmod(0o700)
    auth = ssh_dir / "authorized_keys"
    existing = auth.read_text() if auth.exists() else ""
    if key in existing:
        return
    with auth.open("a") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(key + "\n")
    sh(["chown", "orangepi:orangepi", str(auth)])
    auth.chmod(0o600)


def stage_setup_swap() -> None:
    swapfile = Path("/swapfile")
    if swapfile.exists():
        return
    stat = subprocess.check_output(["df", "--output=avail", "-B1", "/"], text=True)
    free_bytes = int(stat.splitlines()[1].strip())
    target = 8 * 1024 ** 3
    if free_bytes < target + 2 * 1024 ** 3:
        # grow-rootfs may not have run yet — defer until there's enough room
        raise RuntimeError(
            f"only {free_bytes // 1024**3}GB free; need {target // 1024**3}GB for swap + 2GB headroom"
        )
    sh(["fallocate", "-l", "8G", str(swapfile)])
    swapfile.chmod(0o600)
    sh(["mkswap", str(swapfile)])
    sh(["swapon", str(swapfile)])
    fstab = Path("/etc/fstab")
    content = fstab.read_text()
    if "/swapfile" not in content:
        with fstab.open("a") as f:
            f.write("/swapfile none swap sw,pri=-2 0 0\n")


def _resolve_ref(ref: str) -> str:
    """``stable`` → the newest ``sorter/stable/v*`` tag; anything else as given."""
    if ref != STABLE_REF:
        return ref
    out = subprocess.check_output(
        ["git", "-C", str(REPO_DIR), "tag", "-l", f"{STABLE_TAG_PREFIX}*", "--sort=-v:refname"],
        text=True,
    )
    tags = out.split()
    if not tags:
        raise RuntimeError(f"no {STABLE_TAG_PREFIX}* tag in {REPO_URL}")
    return tags[0]


def stage_clone_repo() -> None:
    # Blobless: full history and tags (the Versions page lists and switches
    # between them) without downloading every file ever committed. Cloned
    # beside the target and renamed, so an interrupted clone never leaves a
    # half-made repo that looks finished.
    if not (REPO_DIR / ".git").exists():
        partial = REPO_DIR.with_name(REPO_DIR.name + ".partial")
        shutil.rmtree(partial, ignore_errors=True)
        shutil.rmtree(REPO_DIR, ignore_errors=True)
        sh(["git", "clone", "--filter=blob:none", "--no-checkout", REPO_URL, str(partial)])
        partial.rename(REPO_DIR)
    sh(["git", "config", "--global", "--add", "safe.directory", str(REPO_DIR)])
    target = _resolve_ref(_baked_ref())
    sh(["git", "-C", str(REPO_DIR), "checkout", "--quiet", target])
    (STAMP_DIR / "checked-out-ref").write_text(target + "\n")
    log.info("checked out %s", target)


def stage_write_env() -> None:
    env_path = SOFTWARE_DIR / ".env"
    if env_path.exists():
        return
    if not SOFTWARE_DIR.exists():
        raise RuntimeError("repo not cloned yet")
    env_path.write_text(
        "export DEBUG_LEVEL=2\n"
        "export PYTHONUNBUFFERED=1\n"
        # software/machine.toml, where the Sorter looks by itself; releases
        # older than that need telling, relative to the backend directory.
        'export MACHINE_SPECIFIC_PARAMS_PATH="../../machine.toml"\n'
        "export SORTER_API_HOST=0.0.0.0\n"
        # Headless LAN device: the user reaches it by IP, hostname, or .local —
        # whichever resolves for them. The local API is unauthenticated and not
        # internet-exposed, so accept any browser origin instead of guessing.
        'export SORTER_API_ALLOWED_ORIGINS="*"\n'
    )
    sh(["chown", "orangepi:orangepi", str(env_path)])


def stage_write_machine_toml() -> None:
    machine_toml = SOFTWARE_DIR / "machine.toml"
    if machine_toml.exists():
        return
    if not SOFTWARE_DIR.exists():
        raise RuntimeError("repo not cloned yet")
    # Minimal [cameras] section — backend bails on startup without it.
    # -1 means "no camera assigned"; user picks real indexes in Settings → Cameras.
    machine_toml.write_text(
        "# Auto-generated by sorteros firstboot. Edit via Settings → Cameras in the UI.\n"
        "[cameras]\n"
        "feeder = -1\n"
        "classification_top = -1\n"
        "classification_bottom = -1\n"
    )
    sh(["chown", "orangepi:orangepi", str(machine_toml)])


def stage_uv_sync() -> None:
    backend = SOFTWARE_DIR / "sorter" / "backend"
    if not backend.exists():
        raise RuntimeError("repo not cloned yet")
    if (backend / ".venv").exists():
        return
    sh(["/usr/local/bin/uv", "sync", "--python", "3.12"], cwd=backend)


def stage_pnpm_install() -> None:
    frontend = SOFTWARE_DIR / "sorter" / "frontend"
    if not frontend.exists():
        raise RuntimeError("repo not cloned yet")
    if (frontend / "node_modules").exists():
        return
    sh(["pnpm", "install", "--frozen-lockfile"], cwd=frontend)


def stage_pnpm_build() -> None:
    frontend = SOFTWARE_DIR / "sorter" / "frontend"
    if not (frontend / "node_modules").exists():
        raise RuntimeError("pnpm install not done yet")
    if (frontend / ".svelte-kit" / "output" / "client").exists():
        return
    sh(["pnpm", "build"], cwd=frontend)


def stage_install_services() -> None:
    systemd_src = SOFTWARE_DIR / "systemd"
    if not systemd_src.exists():
        raise RuntimeError("repo not cloned yet")
    if not (SOFTWARE_DIR / "sorter" / "frontend" / ".svelte-kit" / "output" / "client").exists():
        raise RuntimeError("pnpm build not done yet")

    pnpm_bin = subprocess.check_output(["which", "pnpm"], text=True).strip()
    replacements = {
        "__USER__": "root",
        "__SOFTWARE_DIR__": str(SOFTWARE_DIR),
        "__UV_BIN__": "/usr/local/bin/uv",
        "__PNPM_BIN__": pnpm_bin,
    }

    required = ["sorter-backend.service", "sorter-ui.service"]
    optional = ["sorter-backend-dev.service", "sorter-ui-dev.service"]
    installed: list[str] = []
    for unit in required + optional:
        src = systemd_src / unit
        if not src.exists():
            if unit in required:
                raise RuntimeError(f"service template {unit} not found in repo")
            log.info("optional service template %s not in repo — skipping", unit)
            continue
        content = src.read_text()
        for k, v in replacements.items():
            content = content.replace(k, v)
        dest = Path("/etc/systemd/system") / unit
        dest.write_text(content)
        dest.chmod(0o644)
        installed.append(unit)

    sh(["systemctl", "daemon-reload"])
    # Prefer dev services for HMR during early setup; fall back to prod
    # when dev templates aren't in this branch yet. Enable only: main()
    # starts the backend, and the UI only after the progress page releases
    # port 80, or vite-dev fights it for the port.
    to_start = [u for u in ("sorter-backend-dev.service", "sorter-ui-dev.service") if u in installed] or \
               [u for u in ("sorter-backend.service", "sorter-ui.service") if u in installed]
    sh(["systemctl", "enable", *to_start])
    Path("/var/lib/sorteros/active-services").write_text("\n".join(to_start) + "\n")
    log.info("sorter services installed: %s", ", ".join(to_start))


def _ensure_clock_synced() -> None:
    """Force an NTP sync before any SSL-dependent network operation.

    Without this, the Pi boots with a stale RTC/no-RTC clock (often years
    behind), curl rejects TLS certs as 'not yet valid', and installs fail.
    Tries chronyc first (if installed); falls back to systemd-timesyncd
    via timedatectl when chrony is missing (OPi Noble base ships timesyncd).
    """
    try:
        r = subprocess.run(["chronyc", "makestep"], capture_output=True)
        if r.returncode == 0:
            return
    except FileNotFoundError:
        pass
    subprocess.run(["timedatectl", "set-ntp", "true"], check=False)
    time.sleep(5)


def stage_install_tailscale() -> None:
    if Path("/usr/bin/tailscale").exists() or Path("/usr/sbin/tailscale").exists():
        return
    sh(["bash", "-c", "curl -fsSL https://tailscale.com/install.sh | sh"])


def stage_tailscale_up() -> None:
    env = Path("/etc/sorteros/tailscale.env")
    if not env.exists():
        return
    kvs = {}
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            kvs[k.strip()] = v.strip()
    key = kvs.get("TAILSCALE_AUTH_KEY", "")
    tags = kvs.get("TAILSCALE_TAGS", "tag:sorter")
    if not key:
        return
    override_file = Path("/etc/sorteros/tailscale_hostname_override")
    if override_file.exists() and (override := override_file.read_text().strip()):
        ts_name = override
        log.info("tailscale device name (override): %s", ts_name)
    else:
        ts_name = _generate_machine_name()
        log.info("tailscale device name: %s", ts_name)
    sh(
        ["tailscale", "up", f"--authkey={key}", f"--advertise-tags={tags}", f"--hostname={ts_name}", "--ssh"],
        timeout=120,
    )
    env.unlink()


STAGES: list[Stage] = [
    Stage("ssh-host-keys",       needs_internet=False, run=stage_ssh_host_keys),
    Stage("grow-rootfs",         needs_internet=False, run=stage_grow_rootfs),
    Stage("setup-swap",          needs_internet=False, run=stage_setup_swap),
    Stage("clone-repo",          needs_internet=True,  run=stage_clone_repo),
    Stage("write-env",           needs_internet=False, run=stage_write_env),
    Stage("write-machine-toml",  needs_internet=False, run=stage_write_machine_toml),
    Stage("uv-sync",             needs_internet=True,  run=stage_uv_sync),
    Stage("pnpm-install",        needs_internet=True,  run=stage_pnpm_install),
    Stage("pnpm-build",          needs_internet=False, run=stage_pnpm_build),
    Stage("install-services",    needs_internet=False, run=stage_install_services),
    Stage("install-tailscale",   needs_internet=True,  run=stage_install_tailscale, before_ui=False),
    Stage("tailscale-up",        needs_internet=True,  run=stage_tailscale_up, before_ui=False),
]


def stamp_path(name: str) -> Path:
    return STAMP_DIR / f"{name}.done"


def failed_path(name: str) -> Path:
    return STAMP_DIR / f"{name}.failed"


def _finished(stage: Stage) -> bool:
    return stamp_path(stage.name).exists() or failed_path(stage.name).exists()


def _sorter_services() -> list[str]:
    try:
        return Path("/var/lib/sorteros/active-services").read_text().split()
    except OSError:
        return ["sorter-backend.service", "sorter-ui.service"]


def _backend_answers() -> bool:
    try:
        with urllib.request.urlopen(BACKEND_HEALTH_URL, timeout=3) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _start_sorter(keeper: threading.Thread | None, ui_ready: threading.Event) -> None:
    """Start the Sorter. With the progress page up, the backend goes first and
    the page keeps port 80 until the backend answers (about a minute and a half
    on an Orange Pi 5), so the UI the page opens has a machine to show."""
    services = _sorter_services()
    if keeper is None:
        subprocess.run(["systemctl", "start", *services])
        log.info("started %s", ", ".join(services))
        return
    backend = [u for u in services if "backend" in u]
    rest = [u for u in services if u not in backend]
    with _state_lock:
        _runtime["starting_since"] = started = time.time()
    subprocess.run(["systemctl", "start", *backend])
    log.info("started %s", ", ".join(backend))
    while not _backend_answers():
        if time.time() - started > BACKEND_START_TIMEOUT:
            log.warning("the backend didn't answer in %ds; opening the UI anyway", BACKEND_START_TIMEOUT)
            break
        time.sleep(2)
    else:
        log.info("the backend answers after %ds", time.time() - started)
    ui_ready.set()
    keeper.join(timeout=15)
    subprocess.run(["systemctl", "start", *rest])
    log.info("started %s", ", ".join(rest))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s %(asctime)s] %(message)s")
    STAMP_DIR.mkdir(parents=True, exist_ok=True)

    for s in STAGES:
        if stamp_path(s.name).exists():
            _set_state(s.name, "done")
        elif failed_path(s.name).exists():
            _set_state(s.name, "failed", failed_path(s.name).read_text().strip())
        else:
            _set_state(s.name, "pending")
    failures: dict[str, int] = {}

    # Port 80 goes to the progress page while first boot runs, then to the
    # Sorter UI. A machine whose UI is long installed has nothing to show.
    ui_ready = threading.Event()
    keeper = None
    if not all(stamp_path(s.name).exists() for s in STAGES if s.before_ui):
        keeper = threading.Thread(target=_keep_status_server, args=(ui_ready,), name="status-keeper", daemon=True)
        keeper.start()
    ui_started = False

    while True:
        # First, and on every boot: the setup page can change the config
        # (hostname, SSH key) on a machine whose stages are long done.
        try:
            apply_config_if_changed()
        except Exception as e:
            log.warning("applying the setup config failed: %s — will retry", e)

        if not ui_started and all(stamp_path(s.name).exists() for s in STAGES if s.before_ui):
            log.info("everything the UI needs is in place")
            _start_sorter(keeper, ui_ready)
            ui_started = True

        remaining = [s for s in STAGES if not _finished(s)]
        if not remaining:
            log.info("all stages finished")
            return 0

        net = internet_up()
        with _state_lock:
            _runtime["net"] = net
        if net:
            _ensure_clock_synced()

        for s in remaining:
            # Stages after the UI wait for it, so they never delay it.
            if not s.before_ui and not ui_started:
                continue
            if s.needs_internet and not net:
                _set_state(s.name, "waiting", "waiting for internet")
                continue
            _set_state(s.name, "active")
            log.info("running stage: %s", s.name)
            try:
                s.run()
                stamp_path(s.name).touch()
                _set_state(s.name, "done")
            except Exception as e:
                failures[s.name] = failures.get(s.name, 0) + 1
                if not s.before_ui and failures[s.name] >= LATE_STAGE_MAX_FAILURES:
                    log.warning("stage %s failed %d times: %s — giving up", s.name, failures[s.name], e)
                    failed_path(s.name).write_text(f"{e}\n")
                    _set_state(s.name, "failed", str(e))
                else:
                    log.warning("stage %s failed: %s — will retry", s.name, e)
                    _set_state(s.name, "waiting", str(e))

        waiting = any(_stage_state.get(s.name, {}).get("info") == "waiting for internet" for s in remaining)
        time.sleep(WAITING_POLL_INTERVAL if waiting else POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
