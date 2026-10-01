from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import threading
import time
from typing import Callable
from urllib.parse import urlsplit

import db

# How long a computed snapshot of this device's own addresses/names is reused
# before we look them up again. Keeps a wifi/IP/Tailscale change visible within
# a few seconds without spawning subprocesses on every request.
_REFRESH_SECONDS = 15.0


def normalize_origin(origin: str | None) -> str | None:
    if not isinstance(origin, str):
        return None
    normalized = origin.strip().rstrip("/")
    if not normalized:
        return None
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return normalized


def origin_allowed(origin: str | None, allowed_origins: list[str] | tuple[str, ...]) -> bool:
    normalized = normalize_origin(origin)
    if normalized is None:
        return False
    return normalized in {item for item in allowed_origins if isinstance(item, str)}


def is_loopback_client_address(host: str | None) -> bool:
    if not isinstance(host, str):
        return False
    candidate = host.strip().lower()
    if not candidate:
        return False
    if candidate == "localhost":
        return True
    if candidate.startswith("::ffff:"):
        candidate = candidate.split("::ffff:", 1)[1]
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _ui_port() -> str:
    return os.getenv("SORTER_UI_PORT", "5173").strip() or "5173"


def allow_any_origin() -> bool:
    # ESCAPE HATCH: SORTER_API_ALLOW_ANY_ORIGIN=1 accepts any origin (and any
    # cross-origin websocket). Defeats the device-scoped allowlist entirely, so
    # it's a temporary bring-up measure on a trusted LAN only, not a default.
    return os.getenv("SORTER_API_ALLOW_ANY_ORIGIN", "").lower() in ("1", "true", "yes")


def explicit_allowed_origins() -> list[str]:
    override = os.getenv("SORTER_API_ALLOWED_ORIGINS")
    if not override:
        return []
    return _dedupe_origins(
        [origin for origin in (normalize_origin(item) for item in override.split(",")) if origin is not None]
    )


def _local_ip_addresses() -> list[str]:
    # `hostname -I` lists every current interface address (LAN, Tailscale, etc.),
    # so it tracks wifi/DHCP changes without us hardcoding anything.
    try:
        result = subprocess.run(
            ["hostname", "-I"], capture_output=True, text=True, timeout=2.0, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []
    return [token.lower() for token in result.stdout.split() if token]


def _this_device_hosts() -> frozenset[str]:
    # Every name/address that means "this machine's own UI talking to its own
    # backend": loopback, the OS hostname (+ .local), the Tailscale name, and the
    # device's current IPs. Deliberately scoped to this device only.
    hosts: set[str] = {"localhost", "127.0.0.1", "::1"}
    try:
        hostname = socket.gethostname().strip().lower()
    except Exception:
        hostname = ""
    if hostname:
        hosts.add(hostname)
        if not hostname.endswith(".local"):
            hosts.add(f"{hostname}.local")
    tailscale_name = _tailscale_hostname()
    if tailscale_name:
        hosts.add(tailscale_name.strip().lower())
    hosts.update(_local_ip_addresses())
    return frozenset(hosts)


_hosts_snapshot: tuple[float, frozenset[str]] = (0.0, frozenset())
_refreshing = threading.Lock()


def _allowed_hosts() -> frozenset[str]:
    # The origin check runs on the API's event loop, so it never waits on the
    # subprocesses behind this snapshot: once the snapshot is stale it is
    # rebuilt on a background thread and the check uses the current one.
    cached_at, hosts = _hosts_snapshot
    if not hosts:
        return refresh_device_identity()
    if time.monotonic() - cached_at >= _REFRESH_SECONDS and _refreshing.acquire(blocking=False):
        threading.Thread(target=_refresh_in_background, name="device-identity", daemon=True).start()
    return hosts


def _refresh_in_background() -> None:
    try:
        refresh_device_identity()
    finally:
        _refreshing.release()


def refresh_device_identity() -> frozenset[str]:
    # Re-read this device's current IPs / hostname / Tailscale name now. Also
    # called right after a join, logout, or rename so the new name is accepted
    # immediately instead of after the refresh window.
    global _hosts_snapshot
    hosts = _this_device_hosts()
    _hosts_snapshot = (time.monotonic(), hosts)
    return hosts


def is_ui_origin_allowed(origin: str | None) -> bool:
    normalized = normalize_origin(origin)
    if normalized is None:
        return False
    if allow_any_origin():
        return True
    if normalized.lower() in {item.lower() for item in explicit_allowed_origins()}:
        return True
    parsed = urlsplit(normalized.lower())
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:
        return False
    # Accept the configured UI dev port (5173), the port the supervisor serves
    # the UI on, AND a bare host with no explicit port (the UI served on the
    # default 80/443), so http://<device-ip> works just like
    # http://<device-ip>:5173.
    if port is not None and str(port) not in (_ui_port(), os.getenv("SORTER_SUPERVISOR_UI_PORT")):
        return False
    # Any mDNS .local name (e.g. sorter.local) resolves only on the local link,
    # so it's treated as this device on the LAN.
    if host.endswith(".local"):
        return True
    return host in _allowed_hosts()


def describe_origin_decision(origin: str | None) -> str:
    # Diagnostic for CORS/websocket rejections: shows the raw origin, how it
    # normalized, the parsed host/port, and everything the allowlist compares
    # against, so a remote "CORS error" can be diagnosed from the backend log.
    normalized = normalize_origin(origin)
    allowed = is_ui_origin_allowed(origin)
    host = ""
    port_str = ""
    if normalized is not None:
        parsed = urlsplit(normalized.lower())
        host = parsed.hostname or ""
        try:
            port = parsed.port
            port_str = str(port) if port is not None else ("443" if parsed.scheme == "https" else "80")
        except ValueError:
            port_str = "<invalid>"
    return (
        f"allowed={allowed} origin={origin!r} normalized={normalized!r} "
        f"host={host!r} port={port_str!r} ui_port={_ui_port()!r} "
        f"explicit_overrides={explicit_allowed_origins()} device_hosts={sorted(_allowed_hosts())}"
    )


def websocket_connection_allowed(
    origin: str | None,
    client_host: str | None,
) -> bool:
    normalized = normalize_origin(origin)
    if normalized is None:
        return is_loopback_client_address(client_host)
    return is_ui_origin_allowed(normalized)


def compute_allowed_ui_origins() -> list[str]:
    override = explicit_allowed_origins()
    if override:
        return override
    port = _ui_port()
    origins: list[str] = []
    for host in sorted(_allowed_hosts()):
        origins.append(f"http://{host}:{port}")
        origins.append(f"http://{host}")
    return _dedupe_origins(origins)


# The last name Tailscale reported. The backend starts it from the name it
# saved last time and saves each new one (keep_tailscale_name), so the origin
# check knows the name even while Tailscale is not up yet at boot.
_tailscale_name: str | None = None
_saved_tailscale_name: str | None = None
_save_tailscale_name: Callable[[str], None] | None = None


def keep_tailscale_name(saved: str | None, save: Callable[[str], None]) -> None:
    global _tailscale_name, _saved_tailscale_name, _save_tailscale_name
    _tailscale_name = _saved_tailscale_name = saved
    _save_tailscale_name = save


def _tailscale_hostname() -> str | None:
    global _tailscale_name, _saved_tailscale_name
    name = _query_tailscale_hostname()
    if name:
        _tailscale_name = name
        if _save_tailscale_name is not None and name != _saved_tailscale_name:
            try:
                _save_tailscale_name(name)
                _saved_tailscale_name = name
            except Exception as exc:
                db.report_failure("saving the Tailscale name", exc)
    return _tailscale_name


def _query_tailscale_hostname() -> str | None:
    # `tailscale status --json` reads the local daemon's state (no network
    # needed). Self.DNSName is the authoritative name MagicDNS resolves; its
    # first label is the device name.
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    try:
        self_node = (json.loads(result.stdout).get("Self") or {})
    except json.JSONDecodeError:
        return None
    dns_name = (self_node.get("DNSName") or "").rstrip(".")
    if dns_name:
        return dns_name.split(".")[0]
    return self_node.get("HostName") or None


def _dedupe_origins(origins: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for origin in origins:
        normalized = normalize_origin(origin)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered
