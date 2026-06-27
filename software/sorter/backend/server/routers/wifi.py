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


def _run(*args: str, timeout: float = 10.0) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["nmcli", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


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


def _wifi_devices() -> List[Dict[str, Any]]:
    # DEVICE,TYPE,STATE,CONNECTION — keep only real wifi radios (not wifi-p2p).
    proc = _run("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status", timeout=6.0)
    devices: List[Dict[str, Any]] = []
    if proc.returncode != 0:
        return devices
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        parts = _split_terse(line)
        if len(parts) < 4 or parts[1] != "wifi":
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
    device: Optional[str] = None  # adapter to use; None lets NetworkManager pick


@router.post("/api/wifi/connect")
def wifi_connect(payload: WifiConnectPayload) -> Dict[str, Any]:
    if not _have_nmcli():
        return {"ok": False, "error": "nmcli not found"}
    ssid = payload.ssid.strip()
    if not ssid:
        return {"ok": False, "error": "ssid is required"}

    args = ["device", "wifi", "connect", ssid]
    if payload.password:
        args += ["password", payload.password]
    if payload.device:
        args += ["ifname", payload.device.strip()]

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
