"""Where this Sorter can be found on its networks, for the Hive heartbeat.

People lose track of their Sorter on the network: which name it answers to,
which port the UI is on, whether the address changed. Every heartbeat carries
this block so the machine's Hive page can link to the Sorter where it is now.

On SorterOS the network service keeps /run/sorteros/network.json current. It
knows things this process cannot see (the mDNS name the Sorter actually got,
which network reaches the internet, the setup network), so that file is the
source whenever it is fresh. Anywhere else, including a SorterOS image from
before that service, the block is built here in the same shape from the
kernel's interfaces (`ip addr`, so Linux), with whatever cannot be known left
as None.

Collection is best-effort and never raises: a missing tool just means a
smaller block.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from typing import Any

from defs.consts import BACKEND_PORT

SORTEROS_NETWORK_FILE = Path("/run/sorteros/network.json")
# The network service rewrites the file at least every 30 s. Older than this,
# it has stopped and the file may describe a network the Sorter has left.
FRESH_S = 120.0
_MAX_FILE_BYTES = 64 * 1024
_BLOCK_KEYS = ("version", "at", "clock_ok", "hostname", "mdns", "ports", "networks", "setup_network")

SYS_CLASS_NET = Path("/sys/class/net")
SYSTEMD_DIR = Path("/etc/systemd/system")
# The units that serve the UI when it runs as a service. SorterOS and
# `install.sh --as-service` both install them from software/systemd/, and
# enable one of the two.
UI_UNITS = ("sorter-ui-dev.service", "sorter-ui.service")
# Where `pnpm dev` (and ./dev.sh) serve the UI: vite's default port.
DEV_UI_PORT = 5173
MAX_NETWORKS = 8

# Container and VM plumbing: addresses on these are not a way to reach the
# Sorter from another device.
_VIRTUAL_PREFIXES = ("docker", "br-", "veth", "virbr", "vnet", "cni", "flannel", "cali", "lxc", "lxd")
_PORT_ARG = re.compile(r"--port[=\s]+(\d{1,5})\b")


def buildNetworkBlock() -> dict[str, Any]:
    return _fromSorterOS() or _fromInterfaces()


def _fromSorterOS() -> dict[str, Any] | None:
    try:
        if SORTEROS_NETWORK_FILE.stat().st_size > _MAX_FILE_BYTES:
            return None
        block = json.loads(SORTEROS_NETWORK_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(block, dict) or block.get("version") != 1:
        return None
    at = block.get("at")
    if not isinstance(at, (int, float)) or isinstance(at, bool):
        return None
    # `at` is stamped with this machine's clock, so the comparison holds even
    # before the clock was set from the internet.
    if abs(time.time() - at) > FRESH_S:
        return None
    return {key: block.get(key) for key in _BLOCK_KEYS}


def _fromInterfaces() -> dict[str, Any]:
    try:
        hostname = socket.gethostname().strip() or None
    except OSError:
        hostname = None
    label = hostname.split(".")[0].lower() if hostname else None
    return {
        "version": 1,
        "at": int(time.time()),
        # Whether the clock was set from the internet, which network reaches
        # the internet, and since when: only SorterOS's service tracks these.
        "clock_ok": None,
        "hostname": hostname,
        "mdns": f"{label}.local" if label else None,
        "ports": {"ui": _uiPort(), "backend": BACKEND_PORT},
        "networks": _interfaceNetworks(),
        "setup_network": None,
    }


def _uiPort() -> int:
    """The port the UI is served on, as far as this machine says.

    The backend does not serve the UI, so it can only read how the UI is
    started. SORTER_UI_PORT alone is not enough: SorterOS never sets it, and
    the CORS check falls back to 5173 for it, while every SorterOS image serves
    the UI on port 80.
    """
    # 1. The enabled systemd unit, when the UI runs as a service.
    for unit in UI_UNITS:
        if not (SYSTEMD_DIR / "multi-user.target.wants" / unit).exists():
            continue
        try:
            text = (SYSTEMD_DIR / unit).read_text()
        except OSError:
            continue
        for line in text.splitlines():
            if line.strip().startswith("ExecStart="):
                match = _PORT_ARG.search(line)
                port = _port(match.group(1)) if match else None
                if port is not None:
                    return port
    # 2. The port the operator configured for the UI.
    configured = _port(os.getenv("SORTER_UI_PORT", ""))
    if configured is not None:
        return configured
    # 3. Otherwise the UI is the dev server.
    return DEV_UI_PORT


def _port(value: Any) -> int | None:
    try:
        port = int(str(value).strip())
    except ValueError:
        return None
    return port if 0 < port < 65536 else None


def _interfaceNetworks() -> list[dict[str, Any]]:
    links = _run(["ip", "-j", "-4", "addr", "show"])
    try:
        parsed = json.loads(links) if links else []
    except ValueError:
        return []
    networks: list[dict[str, Any]] = []
    ssids: dict[str, str] | None = None
    for link in parsed if isinstance(parsed, list) else []:
        # `ip -j -4` lists an interface with no IPv4 address as {} on some
        # iproute2 versions.
        if not isinstance(link, dict):
            continue
        iface = link.get("ifname")
        flags = link.get("flags") if isinstance(link.get("flags"), list) else []
        if not isinstance(iface, str) or not iface or "LOOPBACK" in flags:
            continue
        # UP and LOWER_UP: configured, and a cable or an association behind it.
        if "UP" not in flags or "LOWER_UP" not in flags:
            continue
        if iface.startswith(_VIRTUAL_PREFIXES) or (SYS_CLASS_NET / iface / "bridge").exists():
            continue
        address = _ipv4Address(link.get("addr_info"))
        if address is None:
            continue
        kind = _kind(iface)
        if kind == "wifi":
            if ssids is None:
                ssids = _wifiSsids()
            name = ssids.get(iface) or iface
        elif kind == "ethernet":
            name = "Ethernet"
        elif kind == "tailscale":
            name = "Tailscale"
        else:
            name = iface
        networks.append(
            {"kind": kind, "iface": iface, "name": name, "address": address, "internet": None, "since": None}
        )
    return networks[:MAX_NETWORKS]


def _ipv4Address(addr_info: Any) -> str | None:
    candidates = [
        info
        for info in (addr_info if isinstance(addr_info, list) else [])
        if isinstance(info, dict)
        and info.get("family") == "inet"
        and info.get("scope") != "host"
        and isinstance(info.get("local"), str)
        and info.get("local")
    ]
    # A global address over a link-local one when an interface has both.
    candidates.sort(key=lambda info: info.get("scope") != "global")
    return candidates[0]["local"] if candidates else None


def _kind(iface: str) -> str:
    if iface.startswith("tailscale"):
        return "tailscale"
    sys_iface = SYS_CLASS_NET / iface
    if (sys_iface / "wireless").exists() or (sys_iface / "phy80211").exists():
        return "wifi"
    # A real device behind it; a VPN or other virtual link has none.
    if (sys_iface / "device").exists():
        return "ethernet"
    return "other"


def _wifiSsids() -> dict[str, str]:
    """Interface -> the SSID it is joined to, from NetworkManager's last scan
    (`--rescan no`: reading must not start a scan)."""
    output = _run(
        ["nmcli", "-t", "-f", "ACTIVE,SSID,DEVICE", "device", "wifi", "list", "--rescan", "no"],
        env={**os.environ, "LC_ALL": "C"},
    )
    ssids: dict[str, str] = {}
    for line in (output or "").splitlines():
        fields = _splitTerse(line)
        if len(fields) == 3 and fields[0] == "yes" and fields[1] and fields[2]:
            ssids.setdefault(fields[2], fields[1])
    return ssids


def _splitTerse(line: str) -> list[str]:
    # nmcli's terse output separates fields with ':' and escapes ':' and '\'
    # inside a value with a backslash.
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def _run(command: list[str], env: dict[str, str] | None = None) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=3.0, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None
