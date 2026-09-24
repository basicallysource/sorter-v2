"""
SorterOS firstboot daemon.

Type=simple background service. Loops every 60s. Each stage is idempotent
and guarded by a stamp file. Stages that need internet just skip themselves
and retry next iteration when offline — boot is NEVER blocked, errors are
NEVER fatal.

The stages up to install-services are what it takes to run the Sorter UI.
The moment those are done the status page hands port 80 to the UI, even if a
later stage (Tailscale) is still retrying or has given up. A later stage that
keeps failing stops after LATE_STAGE_MAX_FAILURES tries so a bad key doesn't
retry forever.

When every stage is done or given up, the daemon exits 0 and systemd stops
restarting it (RestartPreventExitStatus=0 in the unit).
"""

from __future__ import annotations

import hashlib
import html as _html
import logging
import random
import re
import shutil
import socket
import subprocess
import threading
import time
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
LATE_STAGE_MAX_FAILURES = 10
DOCS_URL = "https://docs.basically.website/sorter/installation/sorter-os/"
INTERNET_PROBE_HOSTS = ("deb.debian.org", "github.com")
INTERNET_PROBE_TIMEOUT = 5


log = logging.getLogger("sorteros-firstboot")


@dataclass
class Stage:
    name: str
    needs_internet: bool
    run: Callable[[], None]
    # False for stages that run after the UI is up and may give up.
    before_ui: bool = True


# ─── status server ─────────────────────────────────────────────────────────
#
# A tiny HTTP server on port 80 that renders live firstboot progress so users
# pointing a browser at the device see "what's happening" instead of an
# ERR_CONNECTION_REFUSED. Hands port 80 over to sorter-ui-dev.service once
# all stages complete — same URL transitions from setup status to the UI.

_state_lock = threading.Lock()
_stage_state: dict[str, dict] = {}
_runtime: dict = {"net": False, "started_at": time.time()}

STATUS_ICONS = {
    "done":    ("✓", "done"),
    "active":  ("●", "running"),
    "waiting": ("…", "waiting"),
    "pending": ("○", "pending"),
    "failed":  ("✕", "failed"),
}


def _set_state(name: str, status: str, info: str = "") -> None:
    with _state_lock:
        prev = _stage_state.get(name, {})
        _stage_state[name] = {
            "status": status,
            "info": info,
            "started_at": time.time() if status == "active" and prev.get("status") != "active" else prev.get("started_at"),
        }


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


STATUS_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>SorterOS · {hostname}</title>
<meta http-equiv="refresh" content="5">
<style>
*{{box-sizing:border-box}}
body{{font-family:ui-monospace,'SF Mono',Menlo,monospace;background:#0a0a0a;color:#e5e5e5;margin:0;padding:2rem;line-height:1.45}}
.head{{display:flex;justify-content:space-between;align-items:baseline;max-width:760px;margin:0 auto 1.5rem;flex-wrap:wrap;gap:.5rem}}
h1{{font-size:1.25rem;font-weight:600;margin:0;letter-spacing:.02em}}
.meta{{color:#666;font-size:.85rem}}
.banner{{padding:.9rem 1.1rem;max-width:720px;margin:0 auto 1.5rem;font-size:.95rem}}
.banner.done{{background:#0d1e10;color:#4ade80}}
.banner.busy{{background:#1c1a0d;color:#fbbf24}}
.banner a{{color:#60a5fa;font-weight:600;text-decoration:none}}
.banner a:hover{{text-decoration:underline}}
table{{border-collapse:collapse;width:100%;max-width:720px;margin:0 auto;font-size:.9rem}}
td{{padding:.4rem .8rem;border-bottom:1px solid #1c1c1c;vertical-align:top}}
.icon{{width:1.3rem;text-align:center;font-family:ui-sans-serif}}
.done .icon{{color:#4ade80}}
.running .icon{{color:#fbbf24}}
.waiting .icon{{color:#888}}
.pending .icon{{color:#444}}
.name{{font-weight:500;width:14rem}}
.info{{color:#777;font-size:.82rem}}
.running .info{{color:#fbbf24}}
.waiting .info{{color:#888}}
.pending .info{{color:#555}}
.failed .icon,.failed .info{{color:#f87171}}
.foot{{color:#555;font-size:.8rem;margin:2rem auto 0;max-width:720px}}
code{{background:#1a1a1a;padding:.1rem .35rem}}
</style></head><body>
<div class="head">
<h1>SorterOS · {hostname}</h1>
<div class="meta">v{version} · {ref} · {done}/{total} · {net_label}</div>
</div>
{banner}
<table>{rows}</table>
<div class="foot">Live log: <code>journalctl -fu sorteros-firstboot</code> · Stuck? <a href="{docs_url}" style="color:#60a5fa">Install guide</a></div>
</body></html>
"""


def _render_status_page() -> bytes:
    hostname, version, ref = _read_meta()
    with _state_lock:
        snapshot = {k: dict(v) for k, v in _stage_state.items()}
        net = _runtime.get("net", False)

    done = sum(1 for s in snapshot.values() if s.get("status") == "done")
    total = len(STAGES)
    complete = all(
        snapshot.get(s.name, {}).get("status") == "done" for s in STAGES if s.before_ui
    )

    rows = []
    for stage in STAGES:
        st = snapshot.get(stage.name, {"status": "pending", "info": ""})
        status = st.get("status", "pending")
        info = st.get("info") or ""
        if status == "active" and st.get("started_at"):
            elapsed = int(time.time() - st["started_at"])
            mins, secs = divmod(elapsed, 60)
            elapsed_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            info = f"{info} · {elapsed_str}" if info else f"running · {elapsed_str}"
        icon, cls = STATUS_ICONS.get(status, ("?", "pending"))
        rows.append(
            f'<tr class="{cls}">'
            f'<td class="icon">{icon}</td>'
            f'<td class="name">{_html.escape(stage.name)}</td>'
            f'<td class="info">{_html.escape(info) if info else "—"}</td>'
            f'</tr>'
        )

    if complete:
        # Relative reload — stay on whatever address the user reached this page
        # on (IP, .local, hostname). sorter-ui takes over :80 on the same host,
        # so a same-origin reload lands on the Sorter UI; a hardcoded .local
        # link would wrongly bounce IP users off to an unresolvable name.
        banner = (
            '<div class="banner done">✓ Setup complete · '
            '<a href="/">Reload for Sorter UI →</a></div>'
        )
    else:
        banner = (
            '<div class="banner busy">⏳ Setting up… first install can take 10–30 min. '
            'Page auto-refreshes every 5s.</div>'
        )

    return STATUS_HTML.format(
        hostname=_html.escape(hostname),
        version=_html.escape(version),
        ref=_html.escape(ref),
        docs_url=_html.escape(DOCS_URL),
        done=done, total=total,
        net_label="online" if net else "offline",
        banner=banner,
        rows="".join(rows),
    ).encode("utf-8")


class _StatusHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler convention)
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        body = _render_status_page()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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


def _on_a_network() -> bool:
    r = subprocess.run(["ip", "-4", "route", "show", "default"], capture_output=True, text=True)
    return bool(r.stdout.strip())


def _keep_status_server(ui_ready: threading.Event) -> None:
    """Serve the progress page on :80 while the machine is on a network and
    the UI doesn't have the port yet. Off a network, sorteros-network's setup
    page needs :80, so it is let go within a couple of seconds, not at the
    end of whatever stage is running."""
    server = None
    while not ui_ready.is_set():
        on = _on_a_network()
        if on and server is None:
            server = _start_status_server(STATUS_PORT)
        elif not on and server is not None:
            server.shutdown()
            server.server_close()
            server = None
            log.info("off the network: released port %d for the setup page", STATUS_PORT)
        ui_ready.wait(2)
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
    if isinstance(hostname, str) and hostname.strip():
        log.info("setting hostname: %s", hostname)
        sh(["hostnamectl", "set-hostname", hostname.strip()])

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
        'export MACHINE_SPECIFIC_PARAMS_PATH="../machine.toml"\n'
        "export SORTER_API_HOST=0.0.0.0\n"
        # Headless LAN device: the user reaches it by IP, hostname, or .local —
        # whichever resolves for them. The local API is unauthenticated and not
        # internet-exposed, so accept any browser origin instead of guessing.
        'export SORTER_API_ALLOWED_ORIGINS="*"\n'
    )
    sh(["chown", "orangepi:orangepi", str(env_path)])


def stage_write_machine_toml() -> None:
    machine_toml = SOFTWARE_DIR / "sorter" / "machine.toml"
    if machine_toml.exists():
        return
    if not (SOFTWARE_DIR / "sorter").exists():
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
    # when dev templates aren't in this branch yet. Enable only — main()
    # starts the services AFTER our status server releases port 80,
    # otherwise vite-dev fights us for the same port.
    to_start = [u for u in ("sorter-backend-dev.service", "sorter-ui-dev.service") if u in installed] or \
               [u for u in ("sorter-backend.service", "sorter-ui.service") if u in installed]
    sh(["systemctl", "enable", *to_start])
    Path("/var/lib/sorteros/active-services").write_text("\n".join(to_start) + "\n")
    log.info("sorter services installed: %s (will start after firstboot exits)", ", ".join(to_start))


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


def _start_sorter_services() -> None:
    try:
        services = Path("/var/lib/sorteros/active-services").read_text().split()
    except OSError:
        services = ["sorter-backend.service", "sorter-ui.service"]
    subprocess.run(["systemctl", "start", *services])
    log.info("started %s", ", ".join(services))


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

    # Port 80 goes to whoever the machine needs: sorteros-network's setup page
    # while it's off a network, the progress page while first boot runs, then
    # the Sorter UI.
    ui_ready = threading.Event()
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
            # let the "complete" page render once before port 80 changes hands
            time.sleep(5)
            ui_ready.set()
            keeper.join(timeout=15)
            _start_sorter_services()
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

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
