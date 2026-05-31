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

import logging
import os
import random
import re
import socket
import subprocess
import time
from dataclasses import dataclass
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
# Split so the patcher (which scans the raw .img) doesn't find these
# occurrences instead of the real placeholder in /etc/sorteros-config.toml.
CFG_START_MARKER = "__SORTEROS_CFG" + "_START__"
CFG_END_MARKER = "__SORTEROS_CFG" + "_END__"
REPO_DIR = Path("/home/orangepi/sorter-v2")
SOFTWARE_DIR = REPO_DIR / "software"
POLL_INTERVAL = 60
INTERNET_PROBE_HOSTS = ("deb.debian.org", "github.com")
INTERNET_PROBE_TIMEOUT = 5

log = logging.getLogger("sorteros-firstboot")


@dataclass
class Stage:
    name: str
    needs_internet: bool
    run: Callable[[], None]


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

    Keys honored — keep in sync with sorteros-setup/src/lib/img-patch.ts:
      hostname              → set system hostname
      [wifi].ssid           → write NM connection (autoconnect=true)
      [wifi].password       → wpa-psk for the above
      [ssh].authorized_key  → append to orangepi user's authorized_keys
    """
    cfg: dict = {}
    if CONFIG_PATH.exists():
        raw = CONFIG_PATH.read_text("utf-8", errors="replace")
        if CFG_END_MARKER in raw:
            raw = raw[:raw.index(CFG_END_MARKER)]
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
    sh(["git", "clone", "https://github.com/basicallysource/sorter-v2", str(REPO_DIR)])
    sh(["git", "-C", str(REPO_DIR), "checkout", branch])
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
    hostname = _hostname()
    env_path.write_text(
        "export DEBUG_LEVEL=2\n"
        "export PYTHONUNBUFFERED=1\n"
        'export MACHINE_SPECIFIC_PARAMS_PATH="../machine.toml"\n'
        "export SORTER_API_HOST=0.0.0.0\n"
        f'export SORTER_API_ALLOWED_ORIGINS="http://{hostname}:5173,http://localhost:5173"\n'
    )
    sh(["chown", "orangepi:orangepi", str(env_path)])


def stage_write_machine_toml() -> None:
    machine_toml = SOFTWARE_DIR / "sorter" / "machine.toml"
    if machine_toml.exists():
        return
    if not (SOFTWARE_DIR / "sorter").exists():
        raise RuntimeError("repo not cloned yet")
    machine_toml.write_text("")
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

    for unit in ["sorter-backend.service", "sorter-ui.service", "sorter-backend-dev.service", "sorter-ui-dev.service"]:
        src = systemd_src / unit
        if not src.exists():
            raise RuntimeError(f"service template {unit} not found in repo")
        content = src.read_text()
        for k, v in replacements.items():
            content = content.replace(k, v)
        dest = Path("/etc/systemd/system") / unit
        dest.write_text(content)
        dest.chmod(0o644)

    sh(["systemctl", "daemon-reload"])
    sh(["systemctl", "enable", "wifi-repair.service", "wifi-connect.service"])
    # Dev services enabled by default. At this project stage, hot reload and rapid
    # iteration during setup/debugging are more valuable than production optimization.
    # Switch to sorter-backend.service / sorter-ui.service later when the system
    # stabilizes and we don't need frequent remote adjustments.
    sh(["systemctl", "enable", "--now", "sorter-backend-dev.service", "sorter-ui-dev.service"])
    log.info("sorter services installed and started (dev mode)")


def _ensure_clock_synced() -> None:
    """Force an NTP sync before any SSL-dependent network operation.

    Without this, the Pi boots with a stale RTC/no-RTC clock (often years
    behind), curl rejects TLS certs as 'not yet valid', and installs fail.
    chronyc makestep forces an immediate step adjustment; falls back to
    timedatectl if chrony isn't available.
    """
    r = subprocess.run(["chronyc", "makestep"], capture_output=True)
    if r.returncode != 0:
        subprocess.run(["timedatectl", "set-ntp", "true"])
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

    while True:
        remaining = [s for s in STAGES if not stamp_path(s.name).exists()]
        if not remaining:
            log.info("all stages complete; exiting")
            return 0

        net = internet_up()
        if net:
            _ensure_clock_synced()
        for s in remaining:
            if s.needs_internet and not net:
                continue
            log.info("running stage: %s", s.name)
            try:
                s.run()
                stamp_path(s.name).touch()
            except Exception as e:
                log.warning("stage %s failed: %s — will retry", s.name, e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
