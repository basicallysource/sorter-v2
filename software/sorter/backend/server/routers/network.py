"""WiFi network management endpoints (NetworkManager via nmcli).

Lets the settings UI scan, join and forget WiFi networks while the machine is
reached over wired LAN. Mirrors the nmcli flows of the SorterOS onboarding
portal (software/sorteros/portal/backend/portal.py); on hosts without nmcli
(dev machines) every endpoint degrades to {"available": false}.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

NM_CONNECTIONS_DIR = Path("/etc/NetworkManager/system-connections")
CONNECT_TIMEOUT_S = 45.0

_SSID_RE = re.compile(r"^[^/\x00]{1,32}$")


def _run(cmd: List[str], *, timeout: float = 15.0) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _nmcli_available() -> bool:
    return shutil.which("nmcli") is not None


def _split_terse(line: str) -> List[str]:
    """Split nmcli terse output; values escape ':' as '\\:'."""
    return [part.replace("\x00", ":") for part in line.replace(r"\:", "\x00").split(":")]


def parse_wifi_scan(stdout: str) -> List[Dict[str, Any]]:
    """Parse `nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY dev wifi list` output."""
    networks: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for line in stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        in_use_raw, ssid, signal_raw, security = parts[0], parts[1].strip(), parts[2], parts[3]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        try:
            signal = int(signal_raw)
        except ValueError:
            signal = 0
        networks.append({
            "ssid": ssid,
            "signal": signal,
            "security": security.strip(),
            "in_use": in_use_raw.strip() == "*",
        })
    networks.sort(key=lambda n: n["signal"], reverse=True)
    return networks


def parse_devices(stdout: str) -> List[Dict[str, Any]]:
    """Parse `nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device` output."""
    devices: List[Dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 4:
            continue
        devices.append({
            "device": parts[0],
            "type": parts[1],
            "state": parts[2],
            "connection": parts[3] or None,
        })
    return devices


def nmconnection_body(ssid: str, password: str, hidden: bool) -> str:
    """Render a .nmconnection profile the same way firstboot/portal do."""
    body = (
        "[connection]\n"
        f"id={ssid}\n"
        "type=wifi\n"
        "autoconnect=true\n"
        "\n[wifi]\n"
        f"ssid={ssid}\n"
        "mode=infrastructure\n"
    )
    if hidden:
        body += "hidden=true\n"
    if password:
        body += "\n[wifi-security]\nkey-mgmt=wpa-psk\n" + f"psk={password}\n"
    body += "\n[ipv4]\nmethod=auto\n\n[ipv6]\nmethod=auto\n"
    return body


def parse_device_net_info(stdout: str) -> Dict[str, Any]:
    """Parse `nmcli -t -f IP4.ADDRESS,IP4.GATEWAY,IP4.DNS device show` output."""
    info: Dict[str, Any] = {"ip": None, "gateway": None, "dns": []}
    for line in stdout.splitlines():
        key, _, value = line.partition(":")
        value = value.strip()
        if not value:
            continue
        if key.startswith("IP4.ADDRESS") and info["ip"] is None:
            info["ip"] = value.split("/")[0]
        elif key == "IP4.GATEWAY":
            info["gateway"] = value
        elif key.startswith("IP4.DNS"):
            info["dns"].append(value)
    return info


def _device_net_info(device: str) -> Dict[str, Any]:
    result = _run(["nmcli", "-t", "-f", "IP4.ADDRESS,IP4.GATEWAY,IP4.DNS", "device", "show", device])
    return parse_device_net_info(result.stdout)


def _wifi_radio_enabled() -> bool:
    return _run(["nmcli", "radio", "wifi"]).stdout.strip().lower() == "enabled"


def _status() -> Dict[str, Any]:
    if not _nmcli_available():
        return {"available": False}

    devices = parse_devices(
        _run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]).stdout
    )
    wifi_devices = [d for d in devices if d["type"] == "wifi"]
    ethernet = [
        {
            **d,
            **(_device_net_info(d["device"]) if d["state"].startswith("connected")
               else {"ip": None, "gateway": None, "dns": []}),
        }
        for d in devices
        if d["type"] == "ethernet"
    ]

    wifi: Dict[str, Any] = {"present": bool(wifi_devices), "connected": False}
    for d in wifi_devices:
        if d["state"].startswith("connected"):
            wifi = {
                "present": True,
                "connected": True,
                "device": d["device"],
                "ssid": d["connection"],
                **_device_net_info(d["device"]),
            }
            break

    return {
        "available": True,
        "radio_enabled": _wifi_radio_enabled(),
        "wifi": wifi,
        "ethernet": ethernet,
    }


@router.get("/api/network/wifi/status")
def get_wifi_status() -> Dict[str, Any]:
    return _status()


@router.post("/api/network/wifi/scan")
def scan_wifi() -> Dict[str, Any]:
    if not _nmcli_available():
        return {"available": False, "networks": []}
    try:
        result = _run(
            ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
             "--rescan", "yes"],
            timeout=25.0,
        )
    except subprocess.TimeoutExpired:
        return {"available": True, "ok": False, "error": "WiFi scan timed out", "networks": []}
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "scan failed").strip()
        return {"available": True, "ok": False, "error": err, "networks": []}
    return {"available": True, "ok": True, "networks": parse_wifi_scan(result.stdout)}


class WifiConnectPayload(BaseModel):
    ssid: str
    password: str = ""
    hidden: bool = False


@router.post("/api/network/wifi/connect")
def connect_wifi(payload: WifiConnectPayload) -> Dict[str, Any]:
    if not _nmcli_available():
        return {"ok": False, "error": "NetworkManager (nmcli) is not available on this machine"}

    ssid = payload.ssid.strip()
    if not _SSID_RE.match(ssid):
        return {"ok": False, "error": "Invalid SSID"}
    password = payload.password
    if password and not (8 <= len(password) <= 63):
        return {"ok": False, "error": "WPA password must be 8-63 characters"}

    profile = NM_CONNECTIONS_DIR / f"{ssid}.nmconnection"
    try:
        profile.parent.mkdir(parents=True, exist_ok=True)
        profile.write_text(nmconnection_body(ssid, password, payload.hidden))
        profile.chmod(0o600)
    except OSError as exc:
        return {"ok": False, "error": f"Could not write connection profile: {exc}"}

    reload_result = _run(["nmcli", "connection", "reload"])
    if reload_result.returncode != 0:
        return {"ok": False, "error": (reload_result.stderr or "nmcli reload failed").strip()}

    if not _wifi_radio_enabled():
        _run(["nmcli", "radio", "wifi", "on"])

    try:
        up = _run(["nmcli", "connection", "up", ssid], timeout=CONNECT_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"Connecting to {ssid!r} timed out", "status": _status()}
    if up.returncode != 0:
        err = (up.stderr or up.stdout or "unknown error").strip()
        return {"ok": False, "error": err, "status": _status()}

    # nmcli returns when the activation settles; IPv4 can lag a moment.
    deadline = time.monotonic() + 5.0
    status = _status()
    while time.monotonic() < deadline and not status["wifi"].get("ip"):
        time.sleep(0.5)
        status = _status()
    return {"ok": True, "status": status}


class WifiDisconnectPayload(BaseModel):
    ssid: str


@router.post("/api/network/wifi/disconnect")
def disconnect_wifi(payload: WifiDisconnectPayload) -> Dict[str, Any]:
    """Take the connection down. The saved profile is kept, so reconnecting
    later does not require re-entering the password; NetworkManager blocks
    autoconnect until the user brings it up again."""
    if not _nmcli_available():
        return {"ok": False, "error": "NetworkManager (nmcli) is not available on this machine"}
    ssid = payload.ssid.strip()
    if not _SSID_RE.match(ssid):
        return {"ok": False, "error": "Invalid SSID"}
    result = _run(["nmcli", "connection", "down", ssid])
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        return {"ok": False, "error": err, "status": _status()}
    return {"ok": True, "status": _status()}


class WifiRadioPayload(BaseModel):
    enabled: bool


@router.post("/api/network/wifi/radio")
def set_wifi_radio(payload: WifiRadioPayload) -> Dict[str, Any]:
    if not _nmcli_available():
        return {"ok": False, "error": "NetworkManager (nmcli) is not available on this machine"}
    result = _run(["nmcli", "radio", "wifi", "on" if payload.enabled else "off"])
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        return {"ok": False, "error": err, "status": _status()}
    return {"ok": True, "status": _status()}
