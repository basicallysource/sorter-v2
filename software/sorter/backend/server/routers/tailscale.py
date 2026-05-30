"""Tailscale network management endpoints."""
from __future__ import annotations

import os
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_TAILSCALE_SOCKET = os.getenv("TAILSCALE_SOCKET_PATH", "").strip()

# Keep this naming scheme in sync with sorteros-firstboot.py's
# _generate_machine_name() so UI-joined and firstboot-joined machines look alike.
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


def _cli(*args: str) -> list[str]:
    base = ["tailscale"]
    if _TAILSCALE_SOCKET:
        base += [f"--socket={_TAILSCALE_SOCKET}"]
    return base + list(args)


def _mac_suffix() -> str:
    net = Path("/sys/class/net")
    if net.exists():
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
    return f"sorter-{color}-{piece}-{_mac_suffix()}"


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

    # Keep an existing sorter-* device name so a re-join never renames the
    # machine; replace a generic name (e.g. "orangepi") or generate one on first
    # join, so every UI-joined machine lands as sorter-color-piece-mac.
    existing = (_get_status().get("hostname") or "").strip()
    hostname = existing if existing.startswith("sorter-") else _generate_machine_name()

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

    return {"ok": True, "status": _get_status()}
