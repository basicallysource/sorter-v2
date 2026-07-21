"""Durable store for feeder-dynamics ("sim data") capture segments.

A segment is a gzipped JSONL file of timestamped records — perception piece
states, stepper commands, config changes, dispense events — captured while the
machine is actively sorting. The first record of every segment is a `meta`
snapshot of everything needed to interpret it (machine id, code version,
machine setup, feeder/classification modes, live tuning configs, channel
polygons), so a segment is self-describing even once it leaves the machine.

Rows carry an autoincrement id (the Hive sync cursor) plus sync markers
(synced_at / hive_segment_id) mirroring channel_crop_store, so the shared
HiveSyncWorker drains segments to every Hive target and retention prefers
evicting already-synced files. The byte cap bounds disk even if sync is absent.

Writers append via ``record()`` from any thread; it is a cheap no-op unless a
segment is open (i.e. the collector decided the machine is sorting).
"""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from local_state import local_state_db_path

_INIT_LOCK = threading.Lock()
_initialized = False

_RETENTION_MAX_TOTAL_BYTES = 1024 * 1024 * 1024

_logger: Any = None

_write_lock = threading.Lock()
_active_file: Any = None
_active_path: Optional[Path] = None
_active_meta: dict[str, Any] = {}
_active_started_at: float = 0.0
_active_records: int = 0
_active_bytes: int = 0

_stats_lock = threading.Lock()
_stats = {
    "records_written": 0,
    "write_errors": 0,
    "segments_closed": 0,
    "evicted_files": 0,
}


def configure(logger: Any) -> None:
    global _logger
    _logger = logger


def _log(level: str, message: str) -> None:
    logger = _logger
    if logger is None:
        return
    try:
        getattr(logger, level)(message)
    except Exception:
        pass


def sim_data_dir() -> Path:
    return local_state_db_path().parent / "sim_data"


def _active_dir() -> Path:
    return sim_data_dir() / "active"


def _connect() -> sqlite3.Connection:
    db_path = local_state_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    _ensureInitialized()
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def _ensureInitialized() -> None:
    global _initialized
    if _initialized:
        return
    with _INIT_LOCK:
        if _initialized:
            return
        conn = _connect()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS sim_data_segments ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "created_at REAL NOT NULL, "
                "started_at REAL, "
                "ended_at REAL, "
                "records INTEGER NOT NULL DEFAULT 0, "
                "bytes INTEGER NOT NULL DEFAULT 0, "
                # Summary of the context the segment was captured under, so Hive
                # can filter without opening files (full snapshot is the meta
                # record inside the file).
                "machine_setup TEXT, "
                "feeder_mode TEXT, "
                "classification_mode TEXT, "
                "autotune_mode TEXT, "
                # Path relative to sim_data_dir().
                "file_path TEXT NOT NULL, "
                "deleted_at REAL, "
                "synced_at REAL, "
                "hive_segment_id TEXT"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sim_data_segments_live "
                "ON sim_data_segments(created_at) WHERE deleted_at IS NULL"
            )
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def beginSegment(meta: dict[str, Any]) -> bool:
    global _active_file, _active_path, _active_meta, _active_started_at
    global _active_records, _active_bytes
    with _write_lock:
        if _active_file is not None:
            return False
        try:
            _active_dir().mkdir(parents=True, exist_ok=True)
            path = _active_dir() / f"seg_{int(time.time() * 1000)}.jsonl"
            handle = open(path, "a", encoding="utf-8")
        except OSError as exc:
            _log("warning", f"sim_data_store: failed to open segment: {exc}")
            return False
        _active_file = handle
        _active_path = path
        _active_meta = dict(meta)
        _active_started_at = time.time()
        _active_records = 0
        _active_bytes = 0
        _writeLocked({"type": "meta", **meta})
    _log("info", f"sim_data_store: segment started ({path.name})")
    return True


def record(obj: dict[str, Any]) -> None:
    """Append one record to the active segment. Never raises; drops the record
    when no segment is open (not sorting / capture off)."""
    with _write_lock:
        if _active_file is None:
            return
        _writeLocked(obj)


def _writeLocked(obj: dict[str, Any]) -> None:
    global _active_records, _active_bytes
    try:
        line = json.dumps(obj, separators=(",", ":"), default=str)
        _active_file.write(line + "\n")
        _active_records += 1
        _active_bytes += len(line) + 1
        with _stats_lock:
            _stats["records_written"] += 1
    except Exception as exc:
        with _stats_lock:
            _stats["write_errors"] += 1
        _log("warning", f"sim_data_store: write failed: {exc}")


def flush() -> None:
    with _write_lock:
        if _active_file is None:
            return
        try:
            _active_file.flush()
        except Exception:
            pass


def activeBytes() -> int:
    with _write_lock:
        return _active_bytes if _active_file is not None else 0


def segmentOpen() -> bool:
    with _write_lock:
        return _active_file is not None


def endSegment() -> Optional[int]:
    """Close the active segment: gzip it, register the row, name the file by
    its assigned rowid (the sync cursor). Returns the segment id."""
    global _active_file, _active_path, _active_meta, _active_started_at
    global _active_records, _active_bytes
    with _write_lock:
        if _active_file is None:
            return None
        try:
            _active_file.close()
        except Exception:
            pass
        raw_path = _active_path
        meta = _active_meta
        started_at = _active_started_at
        records = _active_records
        _active_file = None
        _active_path = None
        _active_meta = {}
        _active_records = 0
        _active_bytes = 0
    if raw_path is None:
        return None
    segment_id = _finalizeSegmentFile(raw_path, meta, started_at, records, time.time())
    try:
        _retentionSweep()
    except Exception as exc:
        _log("warning", f"sim_data_store: retention sweep failed: {exc}")
    return segment_id


def _finalizeSegmentFile(
    raw_path: Path,
    meta: dict[str, Any],
    started_at: float | None,
    records: int,
    ended_at: float,
) -> Optional[int]:
    gz_tmp = raw_path.with_suffix(".jsonl.gz.tmp")
    try:
        with open(raw_path, "rb") as src, gzip.open(gz_tmp, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        gz_bytes = gz_tmp.stat().st_size
    except OSError as exc:
        _log("warning", f"sim_data_store: compress failed for {raw_path.name}: {exc}")
        return None

    with _connection() as conn:
        cur = conn.execute(
            "INSERT INTO sim_data_segments "
            "(created_at, started_at, ended_at, records, bytes, machine_setup, "
            "feeder_mode, classification_mode, autotune_mode, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '')",
            (
                time.time(),
                started_at,
                ended_at,
                int(records),
                int(gz_bytes),
                meta.get("machine_setup"),
                meta.get("feeder_mode"),
                meta.get("classification_mode"),
                (meta.get("autotune") or {}).get("mode"),
            ),
        )
        segment_id = int(cur.lastrowid or 0)
        rel_path = f"{segment_id}.jsonl.gz"
        abs_path = sim_data_dir() / rel_path
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            gz_tmp.rename(abs_path)
            raw_path.unlink(missing_ok=True)
        except OSError as exc:
            _log("warning", f"sim_data_store: finalize move failed: {exc}")
            conn.execute("DELETE FROM sim_data_segments WHERE id = ?", (segment_id,))
            conn.commit()
            return None
        conn.execute(
            "UPDATE sim_data_segments SET file_path = ? WHERE id = ?",
            (rel_path, segment_id),
        )
        conn.commit()
    with _stats_lock:
        _stats["segments_closed"] += 1
    _log(
        "info",
        f"sim_data_store: segment {segment_id} closed "
        f"({records} records, {gz_bytes / 1024:.0f} KB gzipped)",
    )
    return segment_id


def recoverOrphanedSegments() -> int:
    """Register raw segments left in active/ by a crash or restart. The meta
    record is the first line of the file, so context survives recovery."""
    recovered = 0
    try:
        orphans = sorted(_active_dir().glob("seg_*.jsonl"))
    except OSError:
        return 0
    for path in orphans:
        with _write_lock:
            if _active_path is not None and path == _active_path:
                continue
        meta: dict[str, Any] = {}
        records = 0
        started_at: float | None = None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for i, line in enumerate(handle):
                    if i == 0:
                        try:
                            first = json.loads(line)
                            if isinstance(first, dict) and first.get("type") == "meta":
                                meta = first
                                started_at = first.get("t")
                        except json.JSONDecodeError:
                            pass
                    records += 1
        except OSError:
            continue
        if records <= 1:
            path.unlink(missing_ok=True)
            continue
        if _finalizeSegmentFile(path, meta, started_at, records, path.stat().st_mtime if path.exists() else time.time()) is not None:
            recovered += 1
    for stale in sim_data_dir().glob("active/*.jsonl.gz.tmp"):
        stale.unlink(missing_ok=True)
    if recovered:
        _log("info", f"sim_data_store: recovered {recovered} orphaned segments")
    return recovered


def _retentionSweep() -> None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(bytes), 0) AS total FROM sim_data_segments WHERE deleted_at IS NULL"
        ).fetchone()
        total = int(row["total"]) if row is not None else 0
        if total <= _RETENTION_MAX_TOTAL_BYTES:
            return
        overage = total - _RETENTION_MAX_TOTAL_BYTES
        rows = conn.execute(
            "SELECT id, file_path, bytes FROM sim_data_segments WHERE deleted_at IS NULL "
            "ORDER BY (synced_at IS NULL) ASC, created_at ASC LIMIT 500"
        ).fetchall()
        now = time.time()
        freed = 0
        evicted = 0
        for r in rows:
            if freed >= overage:
                break
            abs_path = sim_data_dir() / str(r["file_path"])
            try:
                abs_path.unlink(missing_ok=True)
            except OSError:
                pass
            conn.execute(
                "UPDATE sim_data_segments SET deleted_at = ? WHERE id = ?",
                (now, int(r["id"])),
            )
            freed += int(r["bytes"] or 0)
            evicted += 1
        conn.commit()
    if evicted:
        with _stats_lock:
            _stats["evicted_files"] += evicted
        _log(
            "info",
            f"sim_data_store: retention evicted {evicted} segments ({freed / 1024 / 1024:.1f} MB)",
        )


def _rowToDict(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "created_at": r["created_at"],
        "started_at": r["started_at"],
        "ended_at": r["ended_at"],
        "records": int(r["records"] or 0),
        "bytes": int(r["bytes"] or 0),
        "machine_setup": r["machine_setup"],
        "feeder_mode": r["feeder_mode"],
        "classification_mode": r["classification_mode"],
        "autotune_mode": r["autotune_mode"],
    }


def listSegmentsAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, created_at, started_at, ended_at, records, bytes, machine_setup, "
            "feeder_mode, classification_mode, autotune_mode, deleted_at "
            "FROM sim_data_segments WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    out = []
    for r in rows:
        d = _rowToDict(r)
        d["evicted_locally"] = r["deleted_at"] is not None
        out.append(d)
    return out


def getSegmentFileById(segment_id: int) -> Optional[Path]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT file_path, deleted_at FROM sim_data_segments WHERE id = ?",
            (int(segment_id),),
        ).fetchone()
    if row is None or row["deleted_at"] is not None or not row["file_path"]:
        return None
    abs_path = sim_data_dir() / str(row["file_path"])
    return abs_path if abs_path.is_file() else None


def getMaxSegmentId() -> int:
    with _connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM sim_data_segments").fetchone()
    return int(row["m"] or 0)


def markSyncedUpTo(max_id: int, synced_at: float) -> None:
    if max_id <= 0:
        return
    with _connection() as conn:
        conn.execute(
            "UPDATE sim_data_segments SET synced_at = ? WHERE id <= ? AND synced_at IS NULL",
            (float(synced_at), int(max_id)),
        )
        conn.commit()


def getStats() -> dict[str, Any]:
    with _stats_lock:
        stats: dict[str, Any] = dict(_stats)
    with _write_lock:
        stats["active_segment"] = _active_path.name if _active_path is not None else None
        stats["active_records"] = _active_records if _active_file is not None else 0
        stats["active_bytes"] = _active_bytes if _active_file is not None else 0
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS total FROM sim_data_segments "
            "WHERE deleted_at IS NULL"
        ).fetchone()
        stats["live_segments"] = int(row["n"]) if row is not None else 0
        stats["live_bytes"] = int(row["total"]) if row is not None else 0
    return stats
