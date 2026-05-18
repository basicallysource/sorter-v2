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

STAMP_DIR = Path("/var/lib/sorteros")
CONFIG_PATH = Path("/etc/sorteros-config.toml")
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


def sh(cmd: list[str], **kw) -> int:
    log.info("$ %s", " ".join(cmd))
    return subprocess.run(cmd, **kw).returncode


def stage_ssh_host_keys() -> None:
    if list(Path("/etc/ssh").glob("ssh_host_*_key")):
        return
    sh(["ssh-keygen", "-A"])


def stage_grow_rootfs() -> None:
    # TODO: detect rootfs partition + run growpart + resize2fs.
    # On a freshly flashed card we want ext4 to fill the whole SD.
    pass


def stage_apply_config_toml() -> None:
    if not CONFIG_PATH.exists():
        return
    # TODO: parse TOML, write NM connection for wifi block, set hostname,
    # write authorized_keys. The TOML was patched in by sorteros-setup
    # (the browser customizer) or left at placeholder bytes (in which
    # case we no-op).
    pass


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


def stage_tailscale_up() -> None:
    env = Path("/etc/sorteros/tailscale.env")
    if not env.exists():
        return
    # TODO: read env, tailscale up, scrub auth key from disk afterward.
    pass


STAGES: list[Stage] = [
    Stage("ssh-host-keys", needs_internet=False, run=stage_ssh_host_keys),
    Stage("grow-rootfs", needs_internet=False, run=stage_grow_rootfs),
    Stage("apply-config-toml", needs_internet=False, run=stage_apply_config_toml),
    Stage("clone-repo", needs_internet=True, run=stage_clone_repo),
    Stage("uv-sync", needs_internet=True, run=stage_uv_sync),
    Stage("pnpm-install", needs_internet=True, run=stage_pnpm_install),
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
