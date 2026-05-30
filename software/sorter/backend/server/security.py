from __future__ import annotations

import ipaddress
import os
import re
import socket
import subprocess
from functools import lru_cache
from urllib.parse import urlsplit


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


def websocket_connection_allowed(
    origin: str | None,
    client_host: str | None,
) -> bool:
    normalized = normalize_origin(origin)
    if normalized is None:
        return is_loopback_client_address(client_host)
    return is_ui_origin_allowed(normalized)


def _ui_port() -> str:
    return os.getenv("SORTER_UI_PORT", "5173").strip() or "5173"


# Hosts trusted as "the UI talking to its own backend over the LAN": loopback,
# every RFC1918 private range, link-local, the Tailscale CGNAT range
# (100.64/10), any mDNS *.local or Tailscale MagicDNS *.ts.net name, plus this
# machine's own hostname / Tailscale name. Deliberately bounded to private/local
# hosts — a public origin never matches. Combined with the UI port this lets the
# operator reach the UI by IP, hostname, .local, or Tailscale without per-machine
# origin config, and survives DHCP address changes without a restart.
_LOCAL_HOST_PATTERNS: tuple[str, ...] = (
    r"localhost",
    r"127(?:\.\d{1,3}){3}",
    r"10(?:\.\d{1,3}){3}",
    r"192\.168(?:\.\d{1,3}){2}",
    r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2}",
    r"169\.254(?:\.\d{1,3}){2}",
    r"100\.(?:6[4-9]|[7-9]\d|1\d\d|2[0-4]\d|25[0-5])(?:\.\d{1,3}){2}",
    r"\[::1\]",
    r"[A-Za-z0-9-]+\.local",
    r"[A-Za-z0-9-]+\.ts\.net",
)


@lru_cache(maxsize=1)
def _local_origin_regex() -> re.Pattern[str]:
    patterns: list[str] = list(_LOCAL_HOST_PATTERNS)
    try:
        hostname = socket.gethostname().strip().lower()
    except Exception:
        hostname = ""
    if hostname:
        patterns.append(re.escape(hostname))
        if not hostname.endswith(".local"):
            patterns.append(re.escape(f"{hostname}.local"))
    tailscale_name = _tailscale_hostname()
    if tailscale_name:
        patterns.append(re.escape(tailscale_name.strip().lower()))
    host_group = "|".join(patterns)
    return re.compile(rf"^https?://(?:{host_group}):{re.escape(_ui_port())}$", re.IGNORECASE)


def ui_allowed_origin_regex() -> str:
    return _local_origin_regex().pattern


def explicit_allowed_origins() -> list[str]:
    override = os.getenv("SORTER_API_ALLOWED_ORIGINS")
    if not override:
        return []
    return _dedupe_origins(
        [origin for origin in (normalize_origin(item) for item in override.split(",")) if origin is not None]
    )


def is_ui_origin_allowed(origin: str | None) -> bool:
    normalized = normalize_origin(origin)
    if normalized is None:
        return False
    if normalized.lower() in {item.lower() for item in explicit_allowed_origins()}:
        return True
    return bool(_local_origin_regex().match(normalized))


def compute_allowed_ui_origins() -> list[str]:
    override = os.getenv("SORTER_API_ALLOWED_ORIGINS")
    if override:
        return _dedupe_origins(
            [
                origin
                for origin in (normalize_origin(item) for item in override.split(","))
                if origin is not None
            ]
        )

    bind_host = os.getenv("SORTER_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    ui_port = os.getenv("SORTER_UI_PORT", "5173").strip() or "5173"
    origins = [
        f"http://localhost:{ui_port}",
        f"http://127.0.0.1:{ui_port}",
    ]

    if bind_host not in ("127.0.0.1", "localhost", ""):
        try:
            hostname = socket.gethostname()
        except Exception:
            hostname = ""
        if hostname:
            origins.append(f"http://{hostname}:{ui_port}")
            if not hostname.endswith(".local"):
                origins.append(f"http://{hostname}.local:{ui_port}")
        if bind_host != "0.0.0.0":
            origins.append(f"http://{bind_host}:{ui_port}")

    tailscale_name = _tailscale_hostname()
    if tailscale_name:
        origins.append(f"http://{tailscale_name}:{ui_port}")

    return _dedupe_origins(origins)


_tailscale_hostname_cache: tuple[bool, str | None] = (False, None)


def _tailscale_hostname() -> str | None:
    global _tailscale_hostname_cache
    cached, value = _tailscale_hostname_cache
    if cached:
        return value

    from local_state import get_tailscale_hostname, set_tailscale_hostname

    resolved = _query_tailscale_hostname()
    if resolved:
        # Persist to DB so future boots resolve the hostname even if Tailscale
        # isn't up yet when this process starts.
        try:
            set_tailscale_hostname(resolved)
        except Exception:
            pass
    else:
        resolved = get_tailscale_hostname()

    _tailscale_hostname_cache = (True, resolved)
    return resolved


def _query_tailscale_hostname() -> str | None:
    # tailscale status --self reads from the local daemon's in-memory state
    # (loaded from disk at daemon startup), so it works without network access.
    # First field is the IP, second is the bare hostname.
    try:
        result = subprocess.run(
            ["tailscale", "status", "--self"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0 or not result.stdout:
        return None
    parts = result.stdout.strip().split()
    return parts[1] if len(parts) >= 2 else None


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
