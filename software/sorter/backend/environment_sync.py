"""Bring the machine in line with the checked-out release before the backend
imports anything: the virtualenv with uv.lock, and the services with how the
release serves the UI.

An update checks out new code and restarts the backend process, not the service,
so what the service started with can be a release behind: a new dependency is
missing and the backend dies on import, or the UI still runs in a unit the
release no longer has. Standard library only, since it runs before anything else
is known to be installed.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
STAMP_NAME = ".synced-uv-lock"
SYSTEMD_DIR = Path("/etc/systemd/system")
# The UI's own units (Vite), from before the supervisor served the UI's build.
OLD_UI_UNITS = ("sorter-ui-dev.service", "sorter-ui.service")
# SorterOS starts the units listed here on every boot.
SORTEROS_SERVICES = Path("/var/lib/sorteros/active-services")
UI_BUILD_TIMEOUT_S = 900


def syncEnvironment() -> None:
    uv = os.environ.get("UV")
    venv = os.environ.get("VIRTUAL_ENV")
    if not uv or not venv:
        return  # not started through `uv run`: someone's own interpreter, leave it alone
    digest = hashlib.sha256((BACKEND_DIR / "uv.lock").read_bytes()).hexdigest()
    stamp = Path(venv) / STAMP_NAME
    if stamp.exists() and stamp.read_text().strip() == digest:
        return
    print("[startup] uv.lock differs from the environment's: running uv sync", file=sys.stderr, flush=True)
    subprocess.run([uv, "sync", "--locked"], cwd=BACKEND_DIR, check=True)
    stamp.write_text(digest)


def retireOldUiUnits() -> None:
    """A machine set up before the supervisor served the UI runs Vite in a unit
    of its own, which an update leaves running on the new release's config.
    Build the UI, remove that unit and restart this service, whose supervisor
    then serves the build on port 80. Once, and only as root in a systemd
    service: nowhere else is there such a unit to retire."""
    units = [unit for unit in OLD_UI_UNITS if (SYSTEMD_DIR / unit).exists()]
    service = _ownService()
    if not units or service is None or os.geteuid() != 0:
        return
    print(f"[startup] building the UI to retire {', '.join(units)}", file=sys.stderr, flush=True)
    # CI: pnpm may need to replace node_modules, which it only asks a terminal about.
    env = {**os.environ, "CI": "true"}
    try:
        for command in (["pnpm", "install", "--frozen-lockfile"], ["pnpm", "build"]):
            subprocess.run(command, cwd=BACKEND_DIR.parent / "frontend", env=env, check=True, timeout=UI_BUILD_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        # The backend starts anyway, and the next start tries again.
        print(f"[startup] could not build the UI ({exc}); keeping {', '.join(units)}", file=sys.stderr, flush=True)
        return
    subprocess.run(["systemctl", "disable", "--now", *units])
    for unit in units:
        (SYSTEMD_DIR / unit).unlink(missing_ok=True)
    if SORTEROS_SERVICES.exists():
        kept = [unit for unit in SORTEROS_SERVICES.read_text().split() if unit not in units]
        SORTEROS_SERVICES.write_text("".join(f"{unit}\n" for unit in kept))
    subprocess.run(["systemctl", "daemon-reload"])
    # This service's supervisor is the old one, which serves no UI. systemd
    # restarts the service in its own time, stopping this process with it.
    print(f"[startup] restarting {service} so its supervisor serves the UI", file=sys.stderr, flush=True)
    subprocess.run(["systemctl", "--no-block", "restart", service])
    time.sleep(60)


def _ownService() -> str | None:
    """The systemd service this process runs in, from its cgroup."""
    try:
        match = re.search(r"/([^/\s]+\.service)$", Path("/proc/self/cgroup").read_text(), re.M)
    except OSError:
        return None
    return match.group(1) if match else None
