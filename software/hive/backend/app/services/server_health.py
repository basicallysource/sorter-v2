"""Server-health metrics for the admin dashboard: storage, DB size, memory.

Storage accounting walks the whole object store (local disk or S3). On S3/Spaces
that lists every key, which takes long enough that doing it inside the request
blew past Cloudflare's proxy timeout (524). So a background daemon thread
(StorageStatsWorker, mirroring MachineStatsWorker) walks the store on a slow
cadence and upserts a single cache row; the API reads that row instantly. DB
size and memory are cheap and read live.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.server_storage_cache import ServerStorageCache
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


def get_server_health(db: Session) -> dict[str, Any]:
    return {
        "storage": get_storage_stats(db),
        "database": get_database_stats(db),
        "memory": get_memory_stats(),
    }


class StorageStatsWorker:
    """Daemon thread that walks the object store into server_storage_cache on a
    slow cadence. Mirrors MachineStatsWorker."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._start_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "last_run_at": None,
            "last_run_files": 0,
            "last_run_duration_s": None,
            "last_error": None,
            "total_runs": 0,
        }

    def start(self) -> None:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="storage-stats-worker")
            self._thread.start()
        self._update_state(running=True)

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        self._update_state(running=False)

    def wake(self) -> None:
        """Ask the loop to run a fresh storage walk as soon as possible."""
        self._wake_event.set()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            snapshot = dict(self._state)
        snapshot["interval_s"] = self._interval_s()
        return snapshot

    def _interval_s(self) -> float:
        return max(300.0, float(settings.SERVER_STORAGE_REFRESH_INTERVAL_MINUTES) * 60.0)

    def _loop(self) -> None:
        logger.info("StorageStatsWorker: started")
        # Prime the cache on boot so the first server-health load is warm. Only
        # walk if the row is stale/missing, so a restart doesn't re-walk a store
        # that was just measured.
        if self._needs_initial_walk():
            self._run_one_pass()
        while not self._stop_event.is_set():
            self._wake_event.wait(timeout=self._interval_s())
            self._wake_event.clear()
            if self._stop_event.is_set():
                break
            self._run_one_pass()
        self._update_state(running=False)
        logger.info("StorageStatsWorker: stopped")

    def _needs_initial_walk(self) -> bool:
        db = SessionLocal()
        try:
            row = db.query(ServerStorageCache).filter(ServerStorageCache.id == 1).first()
            if row is None or row.computed_at is None:
                return True
            age = datetime.now(timezone.utc) - row.computed_at
            return age.total_seconds() >= self._interval_s()
        except Exception:
            return True
        finally:
            db.close()

    def _run_one_pass(self) -> None:
        started = time.monotonic()
        db = SessionLocal()
        try:
            stats = refresh_storage_cache(db)
            self._update_state(
                last_run_at=datetime.now(timezone.utc).isoformat(),
                last_run_files=int(stats.get("total_files", 0)),
                last_run_duration_s=round(time.monotonic() - started, 3),
                last_error=None,
                increment_runs=1,
            )
            logger.info(
                "StorageStatsWorker: walked %d files in %.2fs",
                stats.get("total_files", 0),
                time.monotonic() - started,
            )
        except Exception as exc:
            logger.exception("StorageStatsWorker pass crashed: %s", exc)
            db.rollback()
            self._update_state(last_error=str(exc))
        finally:
            db.close()

    def _update_state(self, **kwargs: Any) -> None:
        with self._state_lock:
            if "running" in kwargs:
                self._state["running"] = bool(kwargs.pop("running"))
            if "increment_runs" in kwargs:
                self._state["total_runs"] += int(kwargs.pop("increment_runs"))
            for key, value in kwargs.items():
                self._state[key] = value


_INSTANCE: StorageStatsWorker | None = None
_INSTANCE_LOCK = threading.Lock()


def get_storage_stats_worker() -> StorageStatsWorker:
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = StorageStatsWorker()
    return _INSTANCE
