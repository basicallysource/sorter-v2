"""Server-health metrics for the admin dashboard: storage, DB size, memory.

Storage accounting walks the whole object store (local disk or S3), which is
too expensive to do on every request, so it's cached with a short TTL. DB size
and memory are cheap and read live.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.storage_backend import get_backend

# Storage walk is the expensive part — cache it. Admins can force a fresh walk.
_STORAGE_TTL_S = 600.0
_storage_lock = threading.Lock()
_storage_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _categorize(key: str) -> str:
    parts = key.split("/")
    if parts and parts[0] == "models":
        return "model_files"
    # Piece crops live at {machine_id}/pieces/{piece_uuid}/... ; sample images
    # at {machine_id}/{session_id}/{sample_id}/...
    if len(parts) >= 2 and parts[1] == "pieces":
        return "piece_images"
    return "sample_images"


def _walk_storage() -> dict[str, Any]:
    buckets = {
        "sample_images": {"bytes": 0, "files": 0},
        "piece_images": {"bytes": 0, "files": 0},
        "model_files": {"bytes": 0, "files": 0},
    }
    for key, size in get_backend().iter_sizes():
        b = buckets[_categorize(key)]
        b["bytes"] += int(size or 0)
        b["files"] += 1
    total_bytes = sum(v["bytes"] for v in buckets.values())
    total_files = sum(v["files"] for v in buckets.values())
    return {
        **buckets,
        "total_bytes": total_bytes,
        "total_files": total_files,
        "computed_at": time.time(),
    }


def get_storage_stats(force: bool = False) -> dict[str, Any]:
    now = time.monotonic()
    if not force:
        with _storage_lock:
            cached = _storage_cache["value"]
            if cached is not None and (now - _storage_cache["at"]) < _STORAGE_TTL_S:
                return {**cached, "cached": True}
    value = _walk_storage()
    with _storage_lock:
        _storage_cache["at"] = time.monotonic()
        _storage_cache["value"] = value
    return {**value, "cached": False}


def get_database_stats(db: Session) -> dict[str, Any]:
    if db.bind.dialect.name != "postgresql":
        return {"total_bytes": None, "tables": [], "dialect": db.bind.dialect.name}
    total = db.execute(text("SELECT pg_database_size(current_database())")).scalar()
    rows = db.execute(
        text(
            """
            SELECT c.relname AS name,
                   pg_total_relation_size(c.oid) AS bytes,
                   c.reltuples::bigint AS rows
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
            ORDER BY pg_total_relation_size(c.oid) DESC
            LIMIT 30
            """
        )
    ).fetchall()
    return {
        "total_bytes": int(total) if total is not None else None,
        "dialect": "postgresql",
        "tables": [
            {"name": r.name, "bytes": int(r.bytes or 0), "rows": int(r.rows or 0)}
            for r in rows
        ],
    }


def _read_meminfo() -> dict[str, int]:
    info: dict[str, int] = {}
    with open("/proc/meminfo") as f:
        for line in f:
            name, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                info[name.strip()] = int(parts[0]) * 1024  # kB -> bytes
    return info


def _process_rss_bytes() -> int | None:
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (FileNotFoundError, ValueError, IndexError):
        return None
    return None


def get_memory_stats() -> dict[str, Any]:
    try:
        info = _read_meminfo()
        total = info.get("MemTotal")
        available = info.get("MemAvailable")
        used = (total - available) if (total is not None and available is not None) else None
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": used,
            "process_rss_bytes": _process_rss_bytes(),
        }
    except (FileNotFoundError, ValueError):
        # Not on Linux (e.g. local Mac dev) — /proc isn't available.
        return {
            "total_bytes": None,
            "available_bytes": None,
            "used_bytes": None,
            "process_rss_bytes": _process_rss_bytes(),
        }


def get_server_health(db: Session, *, refresh_storage: bool = False) -> dict[str, Any]:
    return {
        "storage": get_storage_stats(force=refresh_storage),
        "database": get_database_stats(db),
        "memory": get_memory_stats(),
    }
