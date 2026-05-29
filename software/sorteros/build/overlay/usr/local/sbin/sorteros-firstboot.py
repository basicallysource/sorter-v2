"""
SorterOS v3 firstboot daemon.

Type=simple background service. Loops every 60s. Each stage is idempotent
and guarded by a stamp file. Stages that need internet just skip themselves
and retry next iteration when offline — boot is NEVER blocked, errors are
NEVER fatal.

When all stages are stamped done, the daemon exits 0 and systemd stops
restarting it (RestartPreventExitStatus=0 in the unit).
"""

from __future__ import annotations

import base64
import html as _html
import json
import logging
import os
import random
import re
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
    "arch", "axle", "beam", "bracket", "brick", "clip", "cone", "cylinder",
    "dome", "gear", "hinge", "panel", "pin", "plate", "rail", "slope",
    "stud", "technic", "tile", "turntable", "wedge",
]

# tomllib is stdlib on Python 3.11+; Ubuntu Jammy ships 3.10 so we fall
# back to the python3-tomli apt package (drop-in API-compatible).
try:
    import tomllib  # type: ignore
except ImportError:
    import tomli as tomllib  # type: ignore

STAMP_DIR = Path("/var/lib/sorteros")
CONFIG_PATH = Path("/etc/sorteros-config.toml")
STATUS_PORT = 80
REPO_DIR = Path("/home/orangepi/sorter-v2")
SOFTWARE_DIR = REPO_DIR / "software"
POLL_INTERVAL = 60
INTERNET_PROBE_HOSTS = ("deb.debian.org", "github.com")
INTERNET_PROBE_TIMEOUT = 5

# Re-announce: the onboarding portal writes this file with the rendezvous
# {id, public_key, hive_url, created_at}. We re-post the current LAN IP each
# loop until the window elapses, then delete the file. The Hive dead-drop
# has a 10-min TTL, so re-announcing keeps the entry fresh for late lookups
# and survives a DHCP renewal. The private key is NOT here — it only ever
# lives in the user's browser.
ANNOUNCE_STATE_FILE = STAMP_DIR / "ip-announce.json"
ANNOUNCE_WINDOW_S = 900  # 15 min — comfortably past the Hive TTL
ANNOUNCE_HTTP_TIMEOUT = 8

log = logging.getLogger("sorteros-firstboot")


@dataclass
class Stage:
    name: str
    needs_internet: bool
    run: Callable[[], None]


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
    hostname = socket.gethostname() or "sorty"
    version = "dev"
    branch = "?"
    try:
        version = Path("/etc/sorteros/version").read_text().strip()
    except OSError:
        pass
    try:
        branch = Path("/etc/sorteros/branch").read_text().strip()
    except OSError:
        pass
    return hostname, version, branch


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
.foot{{color:#555;font-size:.8rem;margin:2rem auto 0;max-width:720px}}
code{{background:#1a1a1a;padding:.1rem .35rem}}
</style></head><body>
<div class="head">
<h1>SorterOS · {hostname}</h1>
<div class="meta">v{version} · {branch} · {done}/{total} · {net_label}</div>
</div>
{banner}
<table>{rows}</table>
<div class="foot">Live log: <code>journalctl -fu sorteros-firstboot</code></div>
</body></html>
"""


def _render_status_page() -> bytes:
    hostname, version, branch = _read_meta()
    with _state_lock:
        snapshot = {k: dict(v) for k, v in _stage_state.items()}
        net = _runtime.get("net", False)

    done = sum(1 for s in snapshot.values() if s.get("status") == "done")
    total = len(STAGES)
    complete = done == total

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
        branch=_html.escape(branch),
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
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{cmd[0]} exited {r.returncode}")


def _hostname() -> str:
    p = Path("/etc/hostname")
    return p.read_text().strip() if p.exists() else "sorter"


# ─── encrypted LAN-IP re-announce ───────────────────────────────────────────
#
# Safety net behind the onboarding portal's immediate announce. Reads the
# rendezvous the portal persisted and keeps re-posting the current egress LAN
# IP to Hive until the window elapses. Best-effort and crash-proof — every
# path is wrapped so a missing dep or network blip never kills the daemon.

def _current_lan_ip() -> str | None:
    """The IP of whichever interface routes to the internet (wlan0 or eth0).

    No packets are sent — connect() on a UDP socket just selects the egress
    interface, which is exactly the address the user reaches the local UI on.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _encrypt_for_pubkey(pubkey_b64: str, plaintext: bytes) -> str | None:
    """RSA-OAEP-SHA256 encrypt with the browser's SPKI public key.

    Returns base64 ciphertext, or None if cryptography is missing / the key
    is unparseable. Mirrors the portal's _encrypt_for_pubkey exactly.
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        pub = serialization.load_der_public_key(base64.b64decode(pubkey_b64))
        ciphertext = pub.encrypt(
            plaintext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        return base64.b64encode(ciphertext).decode("ascii")
    except Exception as e:
        log.warning("re-announce encrypt failed: %s", e)
        return None


def _fetch_pubkey(hive_url: str, rendezvous_id: str) -> str | None:
    """Fetch the browser's public key from Hive (base64 SPKI). Returns None
    until the user has opened the lookup page (which uploads the key)."""
    url = f"{hive_url.rstrip('/')}/api/machine-ip-lookup/{rendezvous_id}/pubkey"
    try:
        with urllib.request.urlopen(url, timeout=ANNOUNCE_HTTP_TIMEOUT) as resp:
            if not (200 <= resp.status < 300):
                return None
            data = json.loads(resp.read().decode("utf-8"))
            pubkey = data.get("pubkey")
            return pubkey if isinstance(pubkey, str) and pubkey else None
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
        log.info("pubkey fetch failed (will retry): %s", e)
        return None


def _post_ciphertext(hive_url: str, rendezvous_id: str, ciphertext_b64: str) -> bool:
    url = f"{hive_url.rstrip('/')}/api/machine-ip-lookup/{rendezvous_id}"
    body = json.dumps({"ciphertext": ciphertext_b64}).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=ANNOUNCE_HTTP_TIMEOUT) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as e:
        log.info("re-announce POST failed (will retry): %s", e)
        return False


def _maybe_reannounce_ip() -> None:
    """Called every loop while online. No-op unless the portal left a
    rendezvous file and we're still inside the window."""
    try:
        if not ANNOUNCE_STATE_FILE.exists():
            return
        data = json.loads(ANNOUNCE_STATE_FILE.read_text())
        created = float(data.get("created_at", 0))
        if time.time() - created > ANNOUNCE_WINDOW_S:
            ANNOUNCE_STATE_FILE.unlink(missing_ok=True)
            log.info("ip-announce window elapsed — stopping re-announce")
            return
        rid = data.get("rendezvous_id")
        hive_url = data.get("hive_url")
        if not (rid and hive_url):
            ANNOUNCE_STATE_FILE.unlink(missing_ok=True)
            return
        ip = _current_lan_ip()
        if not ip:
            return
        # The keypair lives in the user's browser on the Hive lookup page; we
        # fetch the public key from Hive. It's absent until the user opens that
        # page, so a None here just means "retry next loop".
        pubkey = _fetch_pubkey(hive_url, rid)
        if pubkey is None:
            return
        payload = json.dumps({
            "ip": ip,
            "hostname": f"{_hostname()}.local",
            "port": 80,
        }).encode("utf-8")
        ciphertext = _encrypt_for_pubkey(pubkey, payload)
        if ciphertext is None:
            # Unparseable key — re-announce can never succeed, stop trying.
            ANNOUNCE_STATE_FILE.unlink(missing_ok=True)
            return
        if _post_ciphertext(hive_url, rid, ciphertext):
            log.info("re-announced LAN IP %s to %s", ip, hive_url)
    except Exception as e:
        log.warning("re-announce skipped: %s", e)


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


def stage_apply_config_toml() -> None:
    """Read /etc/sorteros-config.toml and apply it.

    Written by sorteros-portal (AP captive portal) when the user submits
    their Wi-Fi credentials. Keys honored:
      hostname              → set system hostname
      [wifi].ssid           → write NM connection (autoconnect=true)
      [wifi].password       → wpa-psk for the above
      [ssh].authorized_key  → append to orangepi user's authorized_keys
      [tailscale].auth_key  → stored for stage_tailscale_up
    """
    cfg: dict = {}
    if CONFIG_PATH.exists():
        raw = CONFIG_PATH.read_text("utf-8", errors="replace")
        try:
            cfg = tomllib.loads(raw)
        except Exception as e:
            log.warning("config toml unreadable: %s", e)

    hostname = cfg.get("hostname")
    if isinstance(hostname, str) and hostname.strip():
        log.info("setting hostname: %s", hostname)
        sh(["hostnamectl", "set-hostname", hostname])

    wifi = cfg.get("wifi") or {}
    ssid = wifi.get("ssid")
    psk = wifi.get("password", "")
    if isinstance(ssid, str) and ssid.strip():
        log.info("applying wifi config for ssid: %s", ssid)
        _write_nm_wifi(ssid, str(psk))
        sh(["nmcli", "connection", "up", ssid])

    ssh_block = cfg.get("ssh") or {}
    key = ssh_block.get("authorized_key")
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


def _write_nm_wifi(ssid: str, psk: str) -> None:
    body = (
        "[connection]\n"
        f"id={ssid}\n"
        "type=wifi\n"
        "autoconnect=true\n"
        "\n"
        "[wifi]\n"
        f"ssid={ssid}\n"
        "mode=infrastructure\n"
        "\n"
        "[wifi-security]\n"
        "key-mgmt=wpa-psk\n"
        f"psk={psk}\n"
        "\n"
        "[ipv4]\n"
        "method=auto\n"
        "\n"
        "[ipv6]\n"
        "method=auto\n"
    )
    backup_dir = Path("/var/lib/sorteros/wifi-backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{ssid}.nmconnection"
    backup.write_text(body)
    backup.chmod(0o600)
    p = Path("/etc/NetworkManager/system-connections") / f"{ssid}.nmconnection"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    p.chmod(0o600)
    Path("/var/lib/sorteros/wifi-configured").parent.mkdir(parents=True, exist_ok=True)
    Path("/var/lib/sorteros/wifi-configured").touch()
    sh(["nmcli", "connection", "reload"])


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


def stage_clone_repo() -> None:
    if REPO_DIR.exists():
        return
    branch_file = Path("/etc/sorteros/branch")
    branch = branch_file.read_text().strip() if branch_file.exists() else "main"
    sh(["git", "clone", "--branch", branch, "--depth", "1",
        "https://github.com/basicallysource/sorter-v2", str(REPO_DIR)])
    sh(["git", "config", "--global", "--add", "safe.directory", str(REPO_DIR)])


def stage_git_lfs_pull() -> None:
    if not REPO_DIR.exists():
        raise RuntimeError("repo not cloned yet")
    env = {**os.environ, "HOME": "/root"}
    sh(["git", "-C", str(REPO_DIR), "lfs", "install"], env=env)
    sh(["git", "-C", str(REPO_DIR), "lfs", "pull"], env=env)


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
        f'export SORTING_PROFILE_PATH="{SOFTWARE_DIR}/sorter/backend/sorting_profile.json"\n'
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


def stage_write_frontend_env() -> None:
    frontend_env = SOFTWARE_DIR / "sorter" / "frontend" / ".env"
    if frontend_env.exists():
        return
    if not (SOFTWARE_DIR / "sorter" / "frontend").exists():
        raise RuntimeError("repo not cloned yet")
    hostname = _hostname()
    frontend_env.write_text(
        f"PUBLIC_BACKEND_BASE_URL=http://{hostname}:8000\n"
        f"PUBLIC_BACKEND_WS_URL=ws://{hostname}:8000\n"
        f"SORTER_ALLOWED_HOSTS={hostname}\n"
    )
    sh(["chown", "orangepi:orangepi", str(frontend_env)])


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
    sh(["systemctl", "enable", "wifi-repair.service", "wifi-connect.service"])
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
    sh(["tailscale", "up", f"--authkey={key}", f"--advertise-tags={tags}", f"--hostname={ts_name}", "--ssh"])
    env.unlink()


STAGES: list[Stage] = [
    Stage("ssh-host-keys",       needs_internet=False, run=stage_ssh_host_keys),
    Stage("grow-rootfs",         needs_internet=False, run=stage_grow_rootfs),
    Stage("apply-config-toml",   needs_internet=False, run=stage_apply_config_toml),
    Stage("setup-swap",          needs_internet=False, run=stage_setup_swap),
    Stage("clone-repo",          needs_internet=True,  run=stage_clone_repo),
    Stage("git-lfs-pull",        needs_internet=True,  run=stage_git_lfs_pull),
    Stage("write-env",           needs_internet=False, run=stage_write_env),
    Stage("write-machine-toml",  needs_internet=False, run=stage_write_machine_toml),
    Stage("write-frontend-env",  needs_internet=False, run=stage_write_frontend_env),
    Stage("uv-sync",             needs_internet=True,  run=stage_uv_sync),
    Stage("pnpm-install",        needs_internet=True,  run=stage_pnpm_install),
    Stage("pnpm-build",          needs_internet=False, run=stage_pnpm_build),
    Stage("install-services",    needs_internet=False, run=stage_install_services),
    Stage("install-tailscale",   needs_internet=True,  run=stage_install_tailscale),
    Stage("tailscale-up",        needs_internet=True,  run=stage_tailscale_up),
]


def stamp_path(name: str) -> Path:
    return STAMP_DIR / f"{name}.done"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="[%(name)s %(asctime)s] %(message)s")
    STAMP_DIR.mkdir(parents=True, exist_ok=True)

    for s in STAGES:
        _set_state(s.name, "done" if stamp_path(s.name).exists() else "pending")

    # Port 80 is shared with the onboarding captive portal. While onboarding is
    # still in progress (no uplink yet and wifi not configured) the portal owns
    # :80; firstboot must not grab it. We start the status server lazily — once
    # the box is online or onboarding has completed — and retry each loop until
    # the bind succeeds (the portal frees :80 when it tears the AP down).
    onboarding_gate = STAMP_DIR / "wifi-configured"
    server = None

    while True:
        remaining = [s for s in STAGES if not stamp_path(s.name).exists()]
        if not remaining:
            log.info("all stages complete")
            # let the final "complete" page render before we hand port 80 over
            time.sleep(5)
            if server is not None:
                server.shutdown()
                server.server_close()
                log.info("released port %d", STATUS_PORT)
            try:
                services = Path("/var/lib/sorteros/active-services").read_text().split()
            except OSError:
                services = ["sorter-backend.service", "sorter-ui.service"]
            subprocess.run(["systemctl", "start", *services])
            return 0

        net = internet_up()
        with _state_lock:
            _runtime["net"] = net
        if net:
            _ensure_clock_synced()
            _maybe_reannounce_ip()

        # Claim :80 for the status page only once onboarding is out of the way.
        if server is None and (net or onboarding_gate.exists()):
            server = _start_status_server(STATUS_PORT)

        for s in remaining:
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
                log.warning("stage %s failed: %s — will retry", s.name, e)
                _set_state(s.name, "waiting", str(e))

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
