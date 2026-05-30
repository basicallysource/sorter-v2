"""Tailscale network management endpoints."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

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
            _cli("status", "--self"),
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

    parts = result.stdout.strip().split()
    ipv4 = parts[0] if parts else None
    hostname = parts[1] if len(parts) > 1 else None
    tailnet: str | None = None
    if len(parts) >= 3:
        fqdn_parts = parts[2].split(".")
        if len(fqdn_parts) >= 3:
            tailnet = ".".join(fqdn_parts[1:])

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


class TailscaleUpPayload(BaseModel):
    auth_key: str


@router.post("/api/tailscale/up")
def tailscale_up(payload: TailscaleUpPayload) -> Dict[str, Any]:
    auth_key = payload.auth_key.strip()
    if not auth_key:
        return {"ok": False, "error": "auth_key is required"}

    if not shutil.which("tailscale"):
        return {"ok": False, "error": "Tailscale is not installed on this machine"}

    try:
        result = subprocess.run(
            _cli("up", f"--authkey={auth_key}", "--ssh"),
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

    return {"ok": True, "status": _get_status()}
