"""The network block a Sorter reports on its heartbeat: where to find it.

The block arrives with a machine token, so it is untrusted input, and the
machine page turns parts of it into links. normalize_network_block keeps only
the fields Hive knows, with checked types and bounded sizes: an address is an
IP literal, a name that becomes a URL host is a DNS name, a port is a port.
Anything else becomes None, and a network without a usable address is
dropped, so one odd field never costs the rest of the block.

Version 1, as the Sorter sends it:

    {"version": 1, "at": <unix s>, "clock_ok": bool, "hostname": str,
     "mdns": "sorter.local", "ports": {"ui": 80, "backend": 8000},
     "networks": [{"kind": "wifi" | "ethernet" | "tailscale" | "other",
                   "iface": str, "name": str, "address": str,
                   "internet": bool | None, "since": <unix s> | None}],
     "setup_network": {"ssid": str, "clients": int, "since": <unix s>} | None}

`at` and `since` are the Sorter's clock, which is wrong until clock_ok is
true. Hive dates the block by when it arrived (machines.network_reported_at).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

NETWORK_KINDS = frozenset({"wifi", "ethernet", "tailscale", "other"})
MAX_NETWORKS = 8
# Raw entries looked at before giving up, so an oversized list costs nothing.
_MAX_NETWORKS_SCANNED = 32
# An SSID is at most 32 bytes; this leaves room for the way it is escaped.
_MAX_TEXT = 64
_MAX_ADDRESS = 64
_MAX_HOSTNAME = 253
_MAX_TIMESTAMP = 10**10
_MAX_CLIENTS = 10_000
_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_IFACE = re.compile(r"^[A-Za-z0-9_.:@-]{1,32}$")


def normalize_network_block(raw: Any) -> dict[str, Any] | None:
    """The block as Hive stores it, or None when it is not a block at all."""
    if not isinstance(raw, dict):
        return None
    ports = raw.get("ports") if isinstance(raw.get("ports"), dict) else {}
    entries = raw.get("networks") if isinstance(raw.get("networks"), list) else []
    networks = [network for network in map(_network, entries[:_MAX_NETWORKS_SCANNED]) if network is not None]
    mdns = _hostname(raw.get("mdns"))
    return {
        "version": _int(raw.get("version"), 1, 1000),
        "at": _timestamp(raw.get("at")),
        "clock_ok": _bool(raw.get("clock_ok")),
        "hostname": _hostname(raw.get("hostname")),
        "mdns": mdns.lower() if mdns and mdns.lower().endswith(".local") else None,
        "ports": {"ui": _int(ports.get("ui"), 1, 65535), "backend": _int(ports.get("backend"), 1, 65535)},
        "networks": networks[:MAX_NETWORKS],
        "setup_network": _setup_network(raw.get("setup_network")),
    }


def _network(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None
    address = _address(entry.get("address"))
    if address is None:
        return None
    kind = entry.get("kind")
    iface = entry.get("iface")
    return {
        "kind": kind if isinstance(kind, str) and kind in NETWORK_KINDS else "other",
        "iface": iface if isinstance(iface, str) and _IFACE.match(iface) else None,
        "name": _text(entry.get("name")),
        "address": address,
        "internet": _bool(entry.get("internet")),
        "since": _timestamp(entry.get("since")),
    }


def _address(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) > _MAX_ADDRESS:
        return None
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    # Nothing another device could open: loopback, unspecified, multicast, and
    # an IPv6 link-local address, which means nothing without an interface.
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and (ip.is_link_local or ip.scope_id):
        return None
    return str(ip)


def _hostname(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.strip().rstrip(".")
    if not name or len(name) > _MAX_HOSTNAME:
        return None
    return name if all(_DNS_LABEL.match(label) for label in name.split(".")) else None


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = "".join(char for char in value[: _MAX_TEXT * 4] if char.isprintable()).strip()[:_MAX_TEXT]
    return text or None


def _setup_network(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    ssid = _text(value.get("ssid"))
    if ssid is None:
        return None
    return {
        "ssid": ssid,
        "clients": _int(value.get("clients"), 0, _MAX_CLIENTS),
        "since": _timestamp(value.get("since")),
    }


def _int(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if low <= value <= high else None


def _timestamp(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    # Also rejects NaN and infinity, which Python's JSON parser accepts.
    return int(value) if 0 <= value <= _MAX_TIMESTAMP else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
