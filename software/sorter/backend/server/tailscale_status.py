"""What the local Tailscale daemon says about this machine.

The one reader of `tailscale status --json`: Settings shows it, the origin
check takes the device name from it, and a join keeps that name.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict

SOCKET = os.getenv("TAILSCALE_SOCKET_PATH", "").strip()


def cli(*args: str) -> list[str]:
    return ["tailscale", *([f"--socket={SOCKET}"] if SOCKET else []), *args]


def read(timeout: float = 3.0) -> Dict[str, Any]:
    """`state` is one of not_installed, stopped, logged_out, needs_approval,
    connected or error; `error` says why when it isn't connected."""
    if not shutil.which("tailscale"):
        return {"installed": False, "connected": False, "state": "not_installed"}
    try:
        result = subprocess.run(cli("status", "--json"), capture_output=True, text=True, timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return _down("error", str(exc))
    if "appear to be running" in result.stderr:
        return _down("stopped", "The Tailscale service isn't running.")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return _down("error", result.stderr.strip() or "Tailscale did not answer")
    return parse(data)


def parse(data: Dict[str, Any]) -> Dict[str, Any]:
    me = data.get("Self") or {}
    # DNSName is the name MagicDNS resolves ("sorter-green-arch-0ffbef.
    # tail1234ab.ts.net."): the device name, then the tailnet. HostName can
    # differ when the asked-for name was taken, and is the OS's name until
    # the machine has joined.
    labels = (me.get("DNSName") or "").rstrip(".").split(".")
    tags = me.get("Tags") or []
    owner = None if tags else ((data.get("User") or {}).get(str(me.get("UserID"))) or {}).get("LoginName")
    status: Dict[str, Any] = {
        "installed": True,
        "connected": False,
        "hostname": labels[0] or None,
        "ipv4": next((ip for ip in me.get("TailscaleIPs") or [] if ":" not in ip), None),
        "tailnet": ".".join(labels[1:]) or None,
        "network": (data.get("CurrentTailnet") or {}).get("Name"),
        "tags": tags,
        "owner": owner,
    }
    health = [message for message in data.get("Health") or [] if message]
    backend_state = data.get("BackendState")
    # A refused key leaves the daemon Running and logged out; only Health says so.
    logged_out = next((message for message in health if message.startswith("You are logged out")), None)
    if backend_state == "NeedsMachineAuth":
        status.update(state="needs_approval", error="Waiting for an admin of that Tailscale network to approve this machine.")
    elif backend_state == "NeedsLogin" and not logged_out:
        # Health says "Tailscale is stopped." here, which reads as if the service were off.
        status.update(state="logged_out", error="Not on a Tailscale network yet.")
    elif backend_state != "Running" or logged_out:
        status.update(state="logged_out", error=logged_out or "; ".join(health) or backend_state or "Not connected")
    else:
        status.update(state="connected", connected=True, warnings=health)
    return status


def _down(state: str, error: str) -> Dict[str, Any]:
    return {"installed": True, "connected": False, "state": state, "error": error}
