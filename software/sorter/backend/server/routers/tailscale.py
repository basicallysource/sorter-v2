"""Tailscale network management endpoints.

On SorterOS the backend also keeps Tailscale installed, so an auth key can be
added from Settings at any time. First boot tries once and gives up for good
when that one download fails.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from server.machine_naming import generate_hostname
from server.security import refresh_device_identity

router = APIRouter()
log = logging.getLogger(__name__)

_TAILSCALE_SOCKET = os.getenv("TAILSCALE_SOCKET_PATH", "").strip()

SORTEROS_STAMP = Path("/etc/sorteros/version")
# Where first boot keeps a key typed on the setup page until it has joined.
SETUP_KEY_FILE = Path("/etc/sorteros/tailscale.env")
# Download, then run: `curl | sh` succeeds when the download fails.
INSTALL_COMMAND = (
    "curl -fsSL --retry 5 --retry-all-errors --connect-timeout 20 -o /tmp/tailscale-install.sh"
    " https://tailscale.com/install.sh && sh /tmp/tailscale-install.sh"
)
INSTALL_UNIT = "sorter-tailscale-install"
# Tailscale's coordination server, which every join has to reach.
CONTROL_URL = "https://controlplane.tailscale.com/"
JOIN_TIMEOUT_S = 30.0
INSTALL_RETRY_S = 300.0
BUSY_POLL_S = 30.0

_installer: threading.Thread | None = None
_install_error: str | None = None


def _cli(*args: str) -> list[str]:
    base = ["tailscale"]
    if _TAILSCALE_SOCKET:
        base += [f"--socket={_TAILSCALE_SOCKET}"]
    return base + list(args)


def _get_status() -> Dict[str, Any]:
    if not shutil.which("tailscale"):
        return {
            "installed": False,
            "connected": False,
            "installing": _installer is not None and _installer.is_alive(),
            "install_error": _install_error,
        }

    try:
        result = subprocess.run(
            _cli("status", "--json"),
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return {"installed": True, "connected": False, "error": str(exc)}

    if result.returncode != 0 or not result.stdout.strip():
        err = (result.stderr or "").strip() or "Not connected"
        return {"installed": True, "connected": False, "error": err}

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"installed": True, "connected": False, "error": str(exc)}

    if data.get("BackendState") != "Running":
        # Health carries the reason, e.g. "You are logged out. The last login
        # error was: invalid key: API key does not exist".
        health = "; ".join(data.get("Health") or [])
        return {"installed": True, "connected": False, "error": health or data.get("BackendState") or "Not connected"}

    self_node = data.get("Self") or {}
    # DNSName is the authoritative name MagicDNS actually resolves (e.g.
    # "sorter-green-arch-0ffbef.tail1234ab.ts.net."); the first label is the
    # device name, the rest is the tailnet. HostName can differ from this when a
    # requested name collided with an existing node.
    dns_name = (self_node.get("DNSName") or "").rstrip(".")
    labels = dns_name.split(".") if dns_name else []
    hostname = labels[0] if labels else (self_node.get("HostName") or None)
    tailnet = ".".join(labels[1:]) if len(labels) >= 3 else None
    ips = self_node.get("TailscaleIPs") or []
    ipv4 = next((ip for ip in ips if ":" not in ip), None)

    return {
        "installed": True,
        "connected": True,
        "hostname": hostname,
        "ipv4": ipv4,
        "tailnet": tailnet,
    }


@router.get("/api/tailscale/status")
def get_tailscale_status() -> Dict[str, Any]:
    return _get_status()


def current_hostname() -> str | None:
    """This machine's Tailscale device name, or None when it has not joined."""
    status = _get_status()
    hostname = status.get("hostname")
    return hostname.strip() if isinstance(hostname, str) and hostname.strip() else None


class TailscaleUpPayload(BaseModel):
    auth_key: str


@router.post("/api/tailscale/up")
def tailscale_up(payload: TailscaleUpPayload) -> Dict[str, Any]:
    auth_key = payload.auth_key.strip()
    if not auth_key:
        return {"ok": False, "error": "auth_key is required"}
    return _join(auth_key)


def _join(auth_key: str) -> Dict[str, Any]:
    if not shutil.which("tailscale"):
        return {"ok": False, "error": "Tailscale is not installed on this machine"}

    # Keep an existing sorter-* device name so a re-join never renames the
    # machine; replace a generic name (e.g. "orangepi") or generate one on first
    # join, so every UI-joined machine lands as sorter-color-piece-mac.
    existing = (_get_status().get("hostname") or "").strip()
    hostname = existing if existing.startswith("sorter-") else generate_hostname()

    try:
        result = subprocess.run(
            _cli("up", f"--authkey={auth_key}", f"--hostname={hostname}", "--ssh"),
            capture_output=True,
            text=True,
            timeout=JOIN_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # A bad key fails in seconds; a join that never finishes almost always
        # means Tailscale's servers can't be reached from this network.
        status = _get_status()
        unreachable = _control_unreachable()
        if unreachable:
            error = (
                f"This machine can't reach Tailscale's servers ({unreachable}). "
                "Something on this network, like a router, firewall or DNS filter, may be blocking Tailscale."
            )
        else:
            error = f"Tailscale didn't finish joining within {JOIN_TIMEOUT_S:.0f} seconds: {status.get('error')}"
        return {"ok": False, "error": error, "status": status}
    except (FileNotFoundError, OSError) as exc:
        return {"ok": False, "error": str(exc)}

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        return {"ok": False, "error": err, "status": _get_status()}

    # The device name just changed; let the origin allowlist pick it up now so
    # the UI reloaded at the new name isn't blocked during the refresh window.
    refresh_device_identity()
    return {"ok": True, "status": _get_status()}


@router.post("/api/tailscale/logout")
def tailscale_logout() -> Dict[str, Any]:
    if not shutil.which("tailscale"):
        return {"ok": False, "error": "Tailscale is not installed on this machine"}

    try:
        result = subprocess.run(
            _cli("logout"),
            capture_output=True,
            text=True,
            timeout=10.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return {"ok": False, "error": str(exc)}

    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        return {"ok": False, "error": err, "status": _get_status()}

    refresh_device_identity()
    return {"ok": True, "status": _get_status()}


def _control_unreachable() -> str | None:
    """Why Tailscale's coordination server can't be reached, or None if it answers."""
    # curl's -m bounds the whole check; a socket timeout applies per address
    # and the server has many.
    try:
        result = subprocess.run(
            ["curl", "-sS", "-o", "/dev/null", "-m", "10", CONTROL_URL],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return str(exc)
    if result.returncode == 0:
        return None
    return re.sub(r"^curl: \(\d+\) ", "", result.stderr.strip()) or f"curl exited {result.returncode}"


def keep_installed() -> None:
    """On SorterOS, install Tailscale in the background whenever it is missing,
    then join with a key from the setup page that first boot could not use."""
    global _installer
    if not SORTEROS_STAMP.exists() or os.geteuid() != 0:
        return
    _installer = threading.Thread(target=_install_until_done, name="tailscale-install", daemon=True)
    _installer.start()


def _install_until_done() -> None:
    global _install_error
    # First boot installs Tailscale and joins with the setup key itself, and a
    # restarted backend's install may still be going; doing either beside them
    # fights over apt's lock or spends a single-use key twice.
    while _busy():
        time.sleep(BUSY_POLL_S)
    while not shutil.which("tailscale"):
        try:
            _install()
            _install_error = None
            log.info("Tailscale installed")
        except Exception as exc:
            _install_error = str(exc)
            log.warning("Tailscale install failed, trying again in %d minutes: %s", INSTALL_RETRY_S // 60, exc)
            time.sleep(INSTALL_RETRY_S)
    _join_with_setup_key()


def _install() -> None:
    # Its own unit, so restarting the backend never stops apt halfway through.
    result = subprocess.run(
        ["systemd-run", f"--unit={INSTALL_UNIT}", "--collect", "--wait", "--quiet", "sh", "-c", INSTALL_COMMAND],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    if result.returncode != 0 or not shutil.which("tailscale"):
        raise RuntimeError(f"the installer failed, see journalctl -u {INSTALL_UNIT}")


def _busy() -> bool:
    return any(_unit_active(unit) for unit in ("sorteros-firstboot.service", f"{INSTALL_UNIT}.service"))


def _unit_active(unit: str) -> bool:
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", unit], timeout=10, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _join_with_setup_key() -> None:
    """Join with a key typed on the setup page that first boot could not use."""
    try:
        lines = SETUP_KEY_FILE.read_text().splitlines()
    except OSError:
        return
    key = next((ln.split("=", 1)[1].strip() for ln in lines if ln.strip().startswith("TAILSCALE_AUTH_KEY=")), "")
    if key and not _get_status().get("connected"):
        result = _join(key)
        if not result.get("ok"):
            log.warning("Tailscale: the setup page's key did not join: %s", result.get("error"))
            return
    SETUP_KEY_FILE.unlink(missing_ok=True)
