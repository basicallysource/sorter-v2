"""Server-health metrics for the admin dashboard: storage, DB size, memory.

Storage accounting walks the whole object store (local disk or S3). On S3/Spaces
that lists every key, which takes long enough that doing it inside the request
blew past Cloudflare's proxy timeout (524). So a PeriodicWorker walks the store
on a slow cadence and upserts a single cache row; the API reads that row
instantly. DB size and memory are cheap and read live.
"""

from __future__ import annotations

import ctypes
import logging
import re
import sys
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.server_storage_cache import ServerStorageCache
from app.services.periodic import PeriodicWorker
from app.services.storage_backend import get_backend

logger = logging.getLogger(__name__)

_BUCKETS = ("sample_images", "piece_images", "model_files")


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
    buckets = {name: {"bytes": 0, "files": 0} for name in _BUCKETS}
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
    }


def _row_to_stats(row: ServerStorageCache | None) -> dict[str, Any]:
    if row is None:
        # Never walked yet (fresh DB / first boot before the worker's priming
        # pass finishes). Serve zeros so the page renders instantly instead of
        # blocking; pending flags the UI that real numbers are on the way.
        return {
            **{name: {"bytes": 0, "files": 0} for name in _BUCKETS},
            "total_bytes": 0,
            "total_files": 0,
            "computed_at": None,
            "pending": True,
        }
    return {
        "sample_images": {"bytes": int(row.sample_images_bytes), "files": int(row.sample_images_files)},
        "piece_images": {"bytes": int(row.piece_images_bytes), "files": int(row.piece_images_files)},
        "model_files": {"bytes": int(row.model_files_bytes), "files": int(row.model_files_files)},
        "total_bytes": int(row.total_bytes),
        "total_files": int(row.total_files),
        "computed_at": row.computed_at.timestamp() if row.computed_at else None,
        "pending": False,
    }


def get_storage_stats(db: Session) -> dict[str, Any]:
    """Read the cached storage accounting. Never walks — instant."""
    row = db.query(ServerStorageCache).filter(ServerStorageCache.id == 1).first()
    return _row_to_stats(row)


def refresh_storage_cache(db: Session) -> dict[str, Any]:
    """Walk the object store and upsert the single cache row. Expensive — only
    called from the background worker, never on a request thread."""
    walked = _walk_storage()
    row = db.query(ServerStorageCache).filter(ServerStorageCache.id == 1).first()
    if row is None:
        row = ServerStorageCache(id=1)
        db.add(row)
    row.sample_images_bytes = walked["sample_images"]["bytes"]
    row.sample_images_files = walked["sample_images"]["files"]
    row.piece_images_bytes = walked["piece_images"]["bytes"]
    row.piece_images_files = walked["piece_images"]["files"]
    row.model_files_bytes = walked["model_files"]["bytes"]
    row.model_files_files = walked["model_files"]["files"]
    row.total_bytes = walked["total_bytes"]
    row.total_files = walked["total_files"]
    row.computed_at = datetime.now(timezone.utc)
    db.commit()
    return _row_to_stats(row)


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


_MALLOC_INFO_TOTALS = re.compile(r'<(total|system) type="([a-z]+)"[^>]*size="(\d+)"')


def _glibc_malloc_stats() -> dict[str, int] | None:
    """glibc's own allocator accounting, read out of malloc_info(3).

    RSS cannot tell "this process is holding live objects" apart from "glibc is
    sitting on memory Python already freed", and those two have opposite fixes:
    one is an object leak to hunt, the other is fragmentation to trim.

    Deliberately NOT mallinfo2, which is the obvious choice and is wrong here:
    it reports the main arena only. Tested against this image it insisted 1.2 MB
    was in use while 200 MB of live bytearrays sat in the process. A confidently
    wrong number is worse than no number. malloc_info walks every arena, and the
    same test tracked the 200 MB alloc and its release exactly.

    Only the trailing summary is parsed; the per-heap detail above it is far more
    XML than this is worth.
    """
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.open_memstream.restype = ctypes.c_void_p
        libc.open_memstream.argtypes = [ctypes.POINTER(ctypes.c_char_p), ctypes.POINTER(ctypes.c_size_t)]
        libc.malloc_info.argtypes = [ctypes.c_int, ctypes.c_void_p]
        libc.fclose.argtypes = [ctypes.c_void_p]
        libc.free.argtypes = [ctypes.c_void_p]
    except (OSError, AttributeError):
        return None

    buf = ctypes.c_char_p()
    size = ctypes.c_size_t()
    stream = libc.open_memstream(ctypes.byref(buf), ctypes.byref(size))
    if not stream:
        return None
    try:
        libc.malloc_info(0, stream)
        libc.fclose(stream)
        xml = ctypes.string_at(buf, size.value).decode("ascii", "replace")
    finally:
        libc.free(buf)

    tail = xml[xml.rfind("</heap>"):] if "</heap>" in xml else xml
    found = {f"{kind}:{name}": int(value) for kind, name, value in _MALLOC_INFO_TOTALS.findall(tail)}
    return {
        # Memory glibc currently holds from the kernel for its arenas.
        "arena_bytes": found.get("system:current", 0),
        # Free space inside those arenas — glibc has it, Python does not want it.
        "free_in_arena_bytes": found.get("total:rest", 0),
        # Large blocks mmapped individually, returned to the kernel when freed.
        "mmapped_bytes": found.get("total:mmap", 0),
        "heap_count": xml.count("<heap "),
    }


def get_memory_stats() -> dict[str, Any]:
    # Cheap enough to read on every request: one libc call and one interpreter
    # counter, no allocation, no walking the heap.
    process = {
        "process_rss_bytes": _process_rss_bytes(),
        # Blocks live in CPython's own allocator. If this climbs with RSS the
        # leak is Python objects; if RSS climbs while this stays flat it is
        # C-level (psycopg2 result buffers, boto3, onnxruntime) or glibc.
        "python_allocated_blocks": sys.getallocatedblocks(),
        "glibc": _glibc_malloc_stats(),
    }
    try:
        info = _read_meminfo()
        total = info.get("MemTotal")
        available = info.get("MemAvailable")
        used = (total - available) if (total is not None and available is not None) else None
        return {
            "total_bytes": total,
            "available_bytes": available,
            "used_bytes": used,
            **process,
        }
    except (FileNotFoundError, ValueError):
        # Not on Linux (e.g. local Mac dev) — /proc isn't available.
        return {
            "total_bytes": None,
            "available_bytes": None,
            "used_bytes": None,
            **process,
        }


def get_server_health(db: Session) -> dict[str, Any]:
    return {
        "storage": get_storage_stats(db),
        "database": get_database_stats(db),
        "memory": get_memory_stats(),
    }


def _storage_interval_s() -> float:
    return max(300.0, float(settings.SERVER_STORAGE_REFRESH_INTERVAL_MINUTES) * 60.0)


def _needs_initial_walk() -> bool:
    """Only walk on boot if the cached row is missing or already stale, so a
    restart does not re-walk a store that was measured minutes ago."""
    db = SessionLocal()
    try:
        row = db.query(ServerStorageCache).filter(ServerStorageCache.id == 1).first()
        if row is None or row.computed_at is None:
            return True
        return (datetime.now(timezone.utc) - row.computed_at).total_seconds() >= _storage_interval_s()
    except Exception:
        return True
    finally:
        db.close()


def _storage_pass() -> dict[str, Any]:
    db = SessionLocal()
    try:
        stats = refresh_storage_cache(db)
        return {"last_run_files": int(stats.get("total_files", 0))}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_INSTANCE: PeriodicWorker | None = None
_INSTANCE_LOCK = threading.Lock()


def get_storage_stats_worker() -> PeriodicWorker:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = PeriodicWorker(
                    "storage-stats-worker",
                    _storage_pass,
                    _storage_interval_s,
                    run_at_start=_needs_initial_walk,
                )
    return _INSTANCE


MEMORY_LOG_INTERVAL_S = 300.0


def _log_memory_once() -> None:
    """Write one memory line to the log.

    DIAGNOSTIC. This exists for the leak that took hive down on 2026-08-20 and
    should be deleted the day that closes — see hive-prod-server.md.

    The same numbers are on /api/admin/server-health, which is the right place
    for them, but reading that needs a login and a leak is measured in days. A
    log line is what is still there tomorrow, survives a restart in the
    journal, and costs nothing to collect. Deliberately its own worker rather
    than folded into the storage walk: that ticks every three hours and only
    after walking the whole object store, far too coarse to sample on.
    """
    stats = get_memory_stats()
    glibc = stats.get("glibc") or {}
    logger.info(
        "memory rss=%.0fMB blocks=%d arena=%.0fMB free_in_arena=%.0fMB mmap=%.0fMB heaps=%s",
        _as_mb(stats.get("process_rss_bytes")),
        stats.get("python_allocated_blocks") or 0,
        _as_mb(glibc.get("arena_bytes")),
        _as_mb(glibc.get("free_in_arena_bytes")),
        _as_mb(glibc.get("mmapped_bytes")),
        glibc.get("heap_count"),
    )


def _as_mb(value: int | None) -> float:
    return (value or 0) / (1024 * 1024)


_MEMORY_LOG_INSTANCE: PeriodicWorker | None = None


def get_memory_log_worker() -> PeriodicWorker:
    global _MEMORY_LOG_INSTANCE
    if _MEMORY_LOG_INSTANCE is None:
        with _INSTANCE_LOCK:
            if _MEMORY_LOG_INSTANCE is None:
                _MEMORY_LOG_INSTANCE = PeriodicWorker(
                    "memory-log-worker",
                    _log_memory_once,
                    lambda: MEMORY_LOG_INTERVAL_S,
                    run_at_start=True,
                )
    return _MEMORY_LOG_INSTANCE
