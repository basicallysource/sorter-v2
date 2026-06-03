from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import time
from urllib.parse import urlsplit

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


def _allowed_hosts() -> frozenset[str]:
    global _hosts_snapshot
    now = time.monotonic()
    cached_at, hosts = _hosts_snapshot
    if hosts and now - cached_at < _REFRESH_SECONDS:
        return hosts
    hosts = _this_device_hosts()
    _hosts_snapshot = (now, hosts)
    return hosts


def refresh_device_identity() -> None:
    # Drop the cached snapshots so the next origin check re-reads this device's
    # current IPs / hostname / Tailscale name. Call right after a join, logout,
    # or rename so the new name is accepted immediately instead of after the
    # refresh window.
    global _hosts_snapshot, _tailscale_hostname_cache
    _hosts_snapshot = (0.0, frozenset())
    _tailscale_hostname_cache = (0.0, None)


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
    port_str = str(port) if port is not None else ("443" if parsed.scheme == "https" else "80")
    if port_str != _ui_port():
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
        f"explicit_overrides={explicit_allowed_origins()} device_hosts={sorted(_this_device_hosts())}"
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
    return _dedupe_origins([f"http://{host}:{port}" for host in sorted(_this_device_hosts())])


_tailscale_hostname_cache: tuple[float, str | None] = (0.0, None)


def _tailscale_hostname() -> str | None:
    global _tailscale_hostname_cache
    now = time.monotonic()
    cached_at, value = _tailscale_hostname_cache
    if value is not None and now - cached_at < _REFRESH_SECONDS:
        return value

    from local_state import get_tailscale_hostname, set_tailscale_hostname

    resolved = _query_tailscale_hostname()
    if resolved:
        # Persist so future boots resolve the name even if Tailscale isn't up yet
        # when this process starts.
        try:
            set_tailscale_hostname(resolved)
        except Exception:
            pass
    else:
        resolved = get_tailscale_hostname()

    _tailscale_hostname_cache = (now, resolved)
    return resolved


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
