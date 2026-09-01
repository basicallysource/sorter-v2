"""Tailscale network management endpoints."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

from server.machine_naming import generate_hostname
from server.security import refresh_device_identity

router = APIRouter()

_TAILSCALE_SOCKET = os.getenv("TAILSCALE_SOCKET_PATH", "").strip()


def _cli(*args: str) -> list[str]:
    base = ["tailscale"]
    if _TAILSCALE_SOCKET:
        base += [f"--socket={_TAILSCALE_SOCKET}"]
    return base + list(args)


def _get_status() -> Dict[str, Any]:
    if not shutil.which("tailscale"):
        return {"installed": False, "connected": False}

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
        return {"installed": True, "connected": False, "error": data.get("BackendState") or "Not connected"}

    self_node = data.get("Self") or {}
    # DNSName is the authoritative name MagicDNS actually resolves (e.g.
    # "sorter-green-arch-0ffbef.tailf1686d.ts.net."); the first label is the
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
            timeout=30.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "tailscale up timed out after 30 seconds", "status": _get_status()}
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
