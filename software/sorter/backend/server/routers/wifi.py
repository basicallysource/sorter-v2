"""WiFi management endpoints (NetworkManager / nmcli).

A small nmtui-style backend: enumerate wifi adapters, scan visible networks, and
connect/disconnect. The backend runs as root on the Pi, so nmcli needs no extra
privileges. Read endpoints are safe; connect/disconnect mutate live networking.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


def _have_nmcli() -> bool:
    return bool(shutil.which("nmcli"))


# nmcli draws a progress line while it associates and erases it with ESC[2K,
# which otherwise ends up in the message the UI shows. Cursor control, not
# colour, so --colors no doesn't help.
_CONTROL_SEQUENCES = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x08\x0b-\x1f]")


def _run(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["nmcli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    proc.stdout = _CONTROL_SEQUENCES.sub("", proc.stdout or "")
    proc.stderr = _CONTROL_SEQUENCES.sub("", proc.stderr or "")
    return proc


def _split_terse(line: str) -> List[str]:
    # nmcli -t escapes a literal ':' as '\:' and a literal '\' as '\\'. Split on
    # unescaped colons, then unescape each field.
    fields = re.split(r"(?<!\\):", line)
    return [f.replace("\\:", ":").replace("\\\\", "\\") for f in fields]


def _device_ip(device: str) -> Optional[str]:
    # IP4.ADDRESS is reported as "<ip>/<prefix>"; strip the prefix for display.
    proc = _run("-t", "-f", "IP4.ADDRESS", "device", "show", device, timeout=6.0)
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 2 or not parts[1].strip():
            continue
        return parts[1].strip().split("/")[0]
    return None


# SorterOS broadcasts its setup network from a second interface on the same
# radio. It is never a way online, and making it a client can switch the
# radio off, so it is neither listed nor used here.
SETUP_IFACE = "ap0"


def _wifi_devices() -> List[Dict[str, Any]]:
    # DEVICE,TYPE,STATE,CONNECTION — keep only real wifi radios (not wifi-p2p,
    # not the setup network's interface).
    proc = _run("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status", timeout=6.0)
    devices: List[Dict[str, Any]] = []
    if proc.returncode != 0:
        return devices
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = _split_terse(line)
        if len(parts) < 4 or parts[1] != "wifi" or parts[0] == SETUP_IFACE:
            continue
        device, _type, state, connection = parts[0], parts[1], parts[2], parts[3]
        connected = state == "connected"
        devices.append({
            "device": device,
            "state": state,
            "connected": connected,
            # nmcli prints "--" for no active connection.
            "active_ssid": connection if connection and connection != "--" else None,
            "ip": _device_ip(device) if connected else None,
        })
    return devices


def _scan_networks() -> List[Dict[str, Any]]:
    # IN-USE,SSID,SIGNAL,SECURITY across all wifi radios. Dedupe by SSID, keeping
    # the strongest signal and any in-use flag (a network can appear once per BSSID
    # and per adapter). Hidden networks (empty SSID) are dropped.
    proc = _run("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "device", "wifi", "list", timeout=8.0)
    by_ssid: Dict[str, Dict[str, Any]] = {}
    if proc.returncode != 0:
        return []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        in_use, ssid, signal_raw, security = parts[0], parts[1], parts[2], parts[3]
        if not ssid:
            continue
        try:
            signal = int(signal_raw)
        except ValueError:
            signal = 0
        secured = bool(security.strip()) and security.strip() != "--"
        entry = by_ssid.get(ssid)
        active = in_use.strip() == "*"
        if entry is None or signal > entry["signal"]:
            by_ssid[ssid] = {
                "ssid": ssid,
                "signal": signal,
                "security": security.strip(),
                "secured": secured,
                "active": active or (entry["active"] if entry else False),
            }
        elif active:
            by_ssid[ssid]["active"] = True
    networks = sorted(by_ssid.values(), key=lambda n: (not n["active"], -n["signal"]))
    return networks


@router.get("/api/wifi/status")
def wifi_status() -> Dict[str, Any]:
    if not _have_nmcli():
        return {"available": False, "adapters": [], "networks": [], "error": "nmcli not found"}
    return {
        "available": True,
        "adapters": _wifi_devices(),
        "networks": _scan_networks(),
    }


@router.post("/api/wifi/scan")
def wifi_scan() -> Dict[str, Any]:
    if not _have_nmcli():
        return {"available": False, "adapters": [], "networks": [], "error": "nmcli not found"}
    # Best-effort rescan; nmcli errors if asked to rescan too frequently, which is
    # harmless — we return the freshest cached list either way.
    try:
        _run("device", "wifi", "rescan", timeout=12.0)
    except subprocess.TimeoutExpired:
        pass
    return {
        "available": True,
        "adapters": _wifi_devices(),
        "networks": _scan_networks(),
    }


class WifiConnectPayload(BaseModel):
    ssid: str
    password: Optional[str] = None
    device: Optional[str] = None  # adapter to use; None means the first one


@router.post("/api/wifi/connect")
def wifi_connect(payload: WifiConnectPayload) -> Dict[str, Any]:
    if not _have_nmcli():
        return {"ok": False, "error": "nmcli not found"}
    # Kept exactly as given: spaces at either end are legal in an SSID.
    ssid = payload.ssid
    if not ssid.strip():
        return {"ok": False, "error": "ssid is required"}

    device = (payload.device or "").strip() or next((d["device"] for d in _wifi_devices()), "")
    if not device or device == SETUP_IFACE:
        return {"ok": False, "error": "No Wi-Fi adapter to connect with"}
    args = ["device", "wifi", "connect", ssid, "ifname", device]
    if payload.password:
        args += ["password", payload.password]

    try:
        # Association + DHCP can take a while on a slow AP; keep it generous.
        proc = _run(*args, timeout=45.0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timed out connecting (association/DHCP took too long)."}

    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or "Failed to connect"
        return {"ok": False, "error": err}
    return {"ok": True, "message": (proc.stdout or "").strip() or f"Connected to {ssid}"}


class WifiDisconnectPayload(BaseModel):
    device: str


@router.post("/api/wifi/disconnect")
def wifi_disconnect(payload: WifiDisconnectPayload) -> Dict[str, Any]:
    if not _have_nmcli():
        return {"ok": False, "error": "nmcli not found"}
    device = payload.device.strip()
    if not device:
        return {"ok": False, "error": "device is required"}
    try:
        proc = _run("device", "disconnect", device, timeout=15.0)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Timed out disconnecting."}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or "Failed to disconnect"
        return {"ok": False, "error": err}
    return {"ok": True, "message": (proc.stdout or "").strip() or f"Disconnected {device}"}
