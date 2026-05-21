from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
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
    allowed_origins: list[str] | tuple[str, ...],
) -> bool:
    normalized = normalize_origin(origin)
    if normalized is None:
        return is_loopback_client_address(client_host)
    return origin_allowed(normalized, allowed_origins)


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
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        _tailscale_hostname_cache = (True, None)
        return None
    if result.returncode != 0 or not result.stdout:
        _tailscale_hostname_cache = (True, None)
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        _tailscale_hostname_cache = (True, None)
        return None
    name = (data.get("Self") or {}).get("HostName")
    resolved = name if isinstance(name, str) and name else None
    _tailscale_hostname_cache = (True, resolved)
    return resolved


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
