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
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

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
SOFTWARE_DIR = Path("/home/orangepi/sorter-v2/software")
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


def stage_ssh_host_keys() -> None:
    if list(Path("/etc/ssh").glob("ssh_host_*_key")):
        return
    sh(["ssh-keygen", "-A"])


def stage_grow_rootfs() -> None:
    # TODO: detect rootfs partition + run growpart + resize2fs.
    # On a freshly flashed card we want ext4 to fill the whole SD.
    pass


def stage_apply_config_toml() -> None:
    """Read /etc/sorteros-config.toml and apply it.

    The file is always present (build.py bakes it in as a padded
    placeholder); sorteros-setup (the browser-side patcher at
    setup.basically.website) overwrites the body in-place with real
    values. If no patching happened the file parses to an empty dict
    and we no-op.

    Keys honored — keep in sync with sorteros-setup/src/lib/img-patch.ts:
      hostname              → set system hostname
      [wifi].ssid           → write NM connection (autoconnect=true)
      [wifi].password       → wpa-psk for the above
      [ssh].authorized_key  → append to orangepi user's authorized_keys
    """
    if not CONFIG_PATH.exists():
        return

    raw = CONFIG_PATH.read_text("utf-8", errors="replace")
    # Strip everything from the bare end marker onward — the patcher leaves
    # __SORTEROS_CFG_END__ without a leading '#' so TOML would choke on it.
    if CFG_END_MARKER in raw:
        raw = raw[:raw.index(CFG_END_MARKER)]
    try:
        cfg = tomllib.loads(raw)
    except Exception as e:
        log.warning("config toml unreadable: %s", e)
        return

    # hostname — apply via hostnamectl + /etc/hostname.
    hostname = cfg.get("hostname")
    if isinstance(hostname, str) and hostname.strip():
        log.info("setting hostname: %s", hostname)
        sh(["hostnamectl", "set-hostname", hostname])

    # [wifi] — translate to an NM keyfile so it persists across reboots.
    wifi = cfg.get("wifi") or {}
    ssid = wifi.get("ssid")
    psk = wifi.get("password", "")
    if isinstance(ssid, str) and ssid.strip():
        log.info("applying wifi config for ssid: %s", ssid)
        _write_nm_wifi(ssid, str(psk))
        # If the AP is currently up, tear it down so the new connection
        # can attach to wlan0.
        sh(["systemctl", "stop", "sorteros-ap.service"])
        sh(["nmcli", "connection", "up", ssid])

    # [ssh] — append authorized_key to orangepi user.
    ssh_block = cfg.get("ssh") or {}
    key = ssh_block.get("authorized_key")
    if isinstance(key, str) and key.strip():
        _append_authorized_key(key.strip())


def _write_nm_wifi(ssid: str, psk: str) -> None:
    """Write an NM keyfile for the given SSID + PSK and reload NM."""
    # NM keyfile format. autoconnect=true so it picks the network up
    # without manual intervention.
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
    p = Path("/etc/NetworkManager/system-connections") / f"{ssid}.nmconnection"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    p.chmod(0o600)
    # Make sure NM picks up the new file. Stamp so sorteros-ap stays down.
    Path("/var/lib/sorteros/wifi-configured").parent.mkdir(parents=True, exist_ok=True)
    Path("/var/lib/sorteros/wifi-configured").touch()
    sh(["nmcli", "connection", "reload"])


def _append_authorized_key(key: str) -> None:
    """Append the given ssh public key to orangepi's authorized_keys
    (no duplicates)."""
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


def stage_clone_repo() -> None:
    if SOFTWARE_DIR.exists():
        return
    # TODO: git clone basicallysource/sorter-v2 → /home/orangepi/sorter-v2,
    # chown to orangepi:orangepi, checkout the branch from /etc/sorteros/branch.
    pass


def stage_uv_sync() -> None:
    backend = SOFTWARE_DIR / "sorter" / "backend"
    if not backend.exists():
        return
    if (backend / ".venv").exists():
        return
    sh(["su", "-", "orangepi", "-c", f"cd {backend} && uv sync"])


def stage_pnpm_install() -> None:
    frontend = SOFTWARE_DIR / "sorter" / "frontend"
    if not frontend.exists():
        return
    if (frontend / "node_modules").exists():
        return
    sh(["su", "-", "orangepi", "-c", f"cd {frontend} && pnpm install --frozen-lockfile"])


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
    """Install Tailscale via the upstream install script. Deferred from
    image build because the base ext4 doesn't have space for it pre-growfs."""
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
    sh(["tailscale", "up", f"--authkey={key}", f"--advertise-tags={tags}", "--ssh"])
    # Scrub the key from disk so it doesn't persist after first use.
    env.unlink()


STAGES: list[Stage] = [
    Stage("ssh-host-keys", needs_internet=False, run=stage_ssh_host_keys),
    Stage("grow-rootfs", needs_internet=False, run=stage_grow_rootfs),
    Stage("apply-config-toml", needs_internet=False, run=stage_apply_config_toml),
    Stage("clone-repo", needs_internet=True, run=stage_clone_repo),
    Stage("uv-sync", needs_internet=True, run=stage_uv_sync),
    Stage("pnpm-install", needs_internet=True, run=stage_pnpm_install),
    Stage("install-tailscale", needs_internet=True, run=stage_install_tailscale),
    Stage("tailscale-up", needs_internet=True, run=stage_tailscale_up),
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
                # Never fatal. Log and retry next iteration.
                log.warning("stage %s failed: %s — will retry", s.name, e)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
