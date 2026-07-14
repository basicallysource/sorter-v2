"""Machine specs snapshot — the "what is this machine" details we report to a
registered Hive account.

Unlike status_ping (anonymous, install-scoped), this rides the account-scoped
heartbeat so the specs land on the machine's own Hive dashboard. It answers the
basic compatibility/support questions: what camera, what controller board, what
platform and OS. Collection is entirely best-effort — a missing /proc file, an
uninitialized camera, or a machine still in standby just yields a smaller
snapshot, never an error that touches the sorting path.

The choke point (hive_telemetry.HiveTelemetryClient) gates the whole snapshot on
the "machine_specs" telemetry field, so an operator can turn it off per target.

BOOT_ID is fresh per process, so every restart produces a new snapshot the
server can distinguish from the previous one even when nothing else changed —
that is how the account dashboard can show a report per restart over time.
"""

from __future__ import annotations

import os
import platform
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1

BOOT_ID = str(uuid.uuid4())
_BOOTED_AT = datetime.now(timezone.utc).isoformat()


def _v4l2CameraModel(index: int) -> str | None:
    try:
        with open(f"/sys/class/video4linux/video{index}/name") as handle:
            name = handle.read().strip()
            return name or None
    except OSError:
        return None


def _cameraEntry(role_value: Any) -> dict[str, Any]:
    # A role in the TOML is either a bare device index or a dict carrying the
    # index/url plus capture settings. Normalize both into one shape.
    entry: dict[str, Any] = {
        "device_index": None,
        "url": None,
        "width": None,
        "height": None,
        "fps": None,
        "fourcc": None,
        "model": None,
    }
    if isinstance(role_value, dict):
        raw_index = role_value.get("device_index")
        if isinstance(raw_index, int) and not isinstance(raw_index, bool):
            entry["device_index"] = raw_index
        url = role_value.get("url")
        if isinstance(url, str) and url.strip():
            entry["url"] = url.strip()
        for key in ("width", "height", "fps"):
            value = role_value.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                entry[key] = value
        fourcc = role_value.get("fourcc")
        if isinstance(fourcc, str) and fourcc.strip():
            entry["fourcc"] = fourcc.strip()
    elif isinstance(role_value, int) and not isinstance(role_value, bool):
        entry["device_index"] = role_value

    if entry["url"] is None and isinstance(entry["device_index"], int) and entry["device_index"] >= 0:
        entry["model"] = _v4l2CameraModel(entry["device_index"])
    return entry


def _liveCameras() -> dict[str, Any]:
    # The running camera service holds the resolution each camera actually
    # opened with, which the raw TOML setup may not carry.
    try:
        from server import shared_state

        service = shared_state.camera_service
        devices = service.devices if service is not None else {}
    except Exception:
        return {}
    cameras: dict[str, Any] = {}
    for role, device in (devices or {}).items():
        config = getattr(device, "config", None)
        if config is None:
            continue
        index = getattr(config, "device_index", None)
        index = index if isinstance(index, int) and not isinstance(index, bool) else None
        url = getattr(config, "url", None)
        url = url.strip() if isinstance(url, str) and url.strip() else None
        if index is None and url is None:
            continue
        entry: dict[str, Any] = {
            "device_index": index,
            "url": url,
            "width": getattr(config, "width", None),
            "height": getattr(config, "height", None),
            "fps": getattr(config, "fps", None),
            "fourcc": getattr(config, "fourcc", None),
            "model": None,
        }
        if url is None and index is not None and index >= 0:
            entry["model"] = _v4l2CameraModel(index)
        cameras[str(role)] = entry
    return cameras


def _cameras() -> dict[str, Any]:
    live = _liveCameras()
    if live:
        return live
    # Fall back to the TOML setup when the camera service isn't up yet.
    try:
        from blob_manager import getCameraSetup

        setup = getCameraSetup()
    except Exception:
        return {}
    if not isinstance(setup, dict):
        return {}
    cameras: dict[str, Any] = {}
    for role, value in setup.items():
        if value is None:
            continue
        entry = _cameraEntry(value)
        if entry["device_index"] is not None or entry["url"] is not None:
            cameras[role] = entry
    return cameras


def _controllerBoards() -> dict[str, Any]:
    # Populated only once hardware has been discovered (homing/ready); a machine
    # sitting in standby reports no boards, which the dashboard renders as "—".
    try:
        from server import shared_state

        irl = shared_state.getActiveIRL()
    except Exception:
        return {}
    boards = getattr(irl, "control_boards", None) if irl is not None else None
    if not isinstance(boards, dict):
        return {}
    result: dict[str, Any] = {}
    for key, board in boards.items():
        identity = getattr(board, "identity", None)
        if identity is None:
            continue
        result[str(key)] = {
            "family": getattr(identity, "family", None),
            "role": getattr(identity, "role", None),
            "device_name": getattr(identity, "device_name", None),
            "port": getattr(identity, "port", None),
        }
    return result


def _system() -> dict[str, Any]:
    info: dict[str, Any] = {"ram_bytes": None, "disk_total_bytes": None, "cpu_count": os.cpu_count()}
    try:
        with open("/proc/meminfo") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    info["ram_bytes"] = int(line.split()[1]) * 1024
                    break
    except Exception:
        pass
    try:
        import shutil

        info["disk_total_bytes"] = int(shutil.disk_usage("/").total)
    except Exception:
        pass
    return info


def _macAddresses() -> list[str]:
    macs: set[str] = set()
    try:
        base = "/sys/class/net"
        for iface in os.listdir(base):
            if iface == "lo":
                continue
            try:
                with open(f"{base}/{iface}/address") as handle:
                    mac = handle.read().strip()
                if mac and mac != "00:00:00:00:00:00":
                    macs.add(mac)
            except OSError:
                continue
    except OSError:
        pass
    return sorted(macs)


def _localIps() -> list[str]:
    ips: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None):
            addr = info[4][0]
            if isinstance(addr, str) and not addr.startswith("127.") and addr != "::1":
                ips.add(addr)
    except Exception:
        pass
    return sorted(ips)


def _cpuSerial() -> str | None:
    try:
        with open("/proc/cpuinfo") as handle:
            for line in handle:
                if line.startswith("Serial"):
                    value = line.split(":", 1)[1].strip()
                    return value or None
    except Exception:
        pass
    return None


def _host() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname() or None,
        "local_ips": _localIps(),
        "mac_addresses": _macAddresses(),
        "cpu_serial": _cpuSerial(),
    }


def buildMachineSpecs() -> dict[str, Any]:
    from status_ping import _configInfo, _hardwareInfo, _osInfo, _softwareInfo

    hardware = _hardwareInfo()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "boot_id": BOOT_ID,
        "booted_at": _BOOTED_AT,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "platform": {
            "model": hardware.get("model"),
            "arch": platform.machine() or None,
            "python": platform.python_version(),
            "os": _osInfo(),
        },
        "software": _softwareInfo(),
        "system": _system(),
        "config": _configInfo(),
        "cameras": _cameras(),
        "controller_boards": _controllerBoards(),
        # Host/network details. The dashboard shows a compact summary, so this
        # block is retained in the report history rather than rendered.
        "host": _host(),
    }
    return payload
