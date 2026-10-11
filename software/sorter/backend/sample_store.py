from __future__ import annotations

import json
import queue
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

import db
import hive_limits

# Durable store for training samples: whole camera frames the sample collector
# takes while sorting, each the camera's own JPEG plus what is needed to use it
# later (the camera's settings and live readout, the lamp's brightness, the
# channel outline, detections). Built like channel_crop_store: rows carry an
# autoincrement id (the Hive sync cursor) and sync markers, files live beside
# the database, one daemon worker does every write, and retention keeps the
# store under its cap, evicting files every Hive already has first.
#
# The SD card is protected twice: the store never grows past its cap (the
# strictest of the local setting and each Hive's limit), and a sample is not
# written at all while the disk's free space is under MIN_FREE_BYTES.

_QUEUE_MAX_ITEMS = 16  # whole frames are large; a slow disk drops, never stalls capture
_RETENTION_SWEEP_INTERVAL_S = 60.0
MIN_FREE_BYTES = 2 * 1024 * 1024 * 1024

_queue: "queue.Queue[tuple[bytes, dict[str, Any]]]" = queue.Queue(maxsize=_QUEUE_MAX_ITEMS)
_worker_started = threading.Event()
_worker_lock = threading.Lock()
_logger: Any = None
# Local cap in bytes set from the machine's settings; None = Hive's limit alone.
_local_cap_bytes: Optional[int] = None

_counts_lock = threading.Lock()
_counts = {"dropped_queue_full": 0, "skipped_low_disk": 0}
_warned: set[str] = set()


def configure(logger: Any, local_cap_bytes: Optional[int] = None) -> None:
    global _logger, _local_cap_bytes
    _logger = logger
    _local_cap_bytes = local_cap_bytes


def setLocalCapBytes(cap_bytes: Optional[int]) -> None:
    global _local_cap_bytes
    _local_cap_bytes = cap_bytes if isinstance(cap_bytes, int) and cap_bytes > 0 else None


def capBytes() -> int:
    cap = int(hive_limits.machineLimits()["sample_store_max_bytes"])
    return min(cap, _local_cap_bytes) if _local_cap_bytes else cap


def _log(level: str, message: str) -> None:
    logger = _logger
    if logger is None:
        return
    try:
        getattr(logger, level)(message)
    except Exception:
        pass


def _warnOnce(key: str, message: str) -> None:
    if key in _warned:
        return
    _warned.add(key)
    _log("warning", message)


def samplesDir() -> Path:
    return db.local_state_db_path().parent / "samples"


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sample_frames ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        # The camera role the frame came from (classification_channel, ...).
        "camera TEXT NOT NULL, "
        # Frame capture time and row insert time, epoch seconds.
        "captured_at REAL NOT NULL, "
        "created_at REAL NOT NULL, "
        "width INTEGER, height INTEGER, "
        "bytes INTEGER NOT NULL, "
        # Path relative to samplesDir().
        "file_path TEXT NOT NULL, "
        # Everything else Hive is sent with the frame, as JSON.
        "meta_json TEXT NOT NULL, "
        # Set when retention removed the local file.
        "deleted_at REAL, "
        # Set once every enabled Hive target has the sample (the sync worker's
        # retention sweep).
        "synced_at REAL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sample_frames_live "
        "ON sample_frames(created_at) WHERE deleted_at IS NULL"
    )


def _connection():
    return db.connect(_createTables)


def _freeBytes() -> Optional[int]:
    try:
        directory = samplesDir()
        directory.mkdir(parents=True, exist_ok=True)
        return int(shutil.disk_usage(directory).free)
    except OSError:
        return None


def enqueue(jpeg: bytes, meta: dict[str, Any]) -> bool:
    """Persist one camera frame with its metadata. Returns False when it was
    dropped: the write queue was full, or the disk is nearly full."""
    if not jpeg:
        return False
    free = _freeBytes()
    if free is not None and free < MIN_FREE_BYTES + len(jpeg):
        with _counts_lock:
            _counts["skipped_low_disk"] += 1
        _warnOnce(
            "low_disk",
            f"sample_store: under {MIN_FREE_BYTES // (1024 * 1024)} MB free on disk; not saving samples until there is room",
        )
        return False
    _warned.discard("low_disk")
    _ensureWorker()
    try:
        _queue.put_nowait((jpeg, dict(meta)))
    except queue.Full:
        with _counts_lock:
            _counts["dropped_queue_full"] += 1
        _warnOnce("queue_full", "sample_store: the write queue is full; dropping samples until it drains")
        return False
    _warned.discard("queue_full")
    return True


def _ensureWorker() -> None:
    if _worker_started.is_set():
        return
    with _worker_lock:
        if _worker_started.is_set():
            return
        thread = threading.Thread(target=_workerLoop, daemon=True, name="sample-store")
        thread.start()
        _worker_started.set()


def _workerLoop() -> None:
    last_sweep = 0.0
    while True:
        try:
            item: Optional[tuple[bytes, dict[str, Any]]] = _queue.get(timeout=_RETENTION_SWEEP_INTERVAL_S)
        except queue.Empty:
            item = None
        wrote = False
        if item is not None:
            try:
                _writeSample(*item)
                wrote = True
            except Exception as exc:
                _log("warning", f"sample_store: failed to persist a sample: {exc}")
        now = time.monotonic()
        # Sweep after every write too: a whole frame is up to a few MB, so the
        # store must not wait a minute to come back under its cap.
        if wrote or now - last_sweep >= _RETENTION_SWEEP_INTERVAL_S:
            last_sweep = now
            try:
                _retentionSweep()
            except Exception as exc:
                _log("warning", f"sample_store: retention sweep failed: {exc}")


def _asInt(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _writeSample(jpeg: bytes, meta: dict[str, Any]) -> None:
    camera = str(meta.get("camera") or "unknown")
    captured_at = meta.get("captured_at")
    if not isinstance(captured_at, (int, float)):
        captured_at = time.time()
    meta_json = json.dumps(meta.get("meta") or {}, sort_keys=True, default=str)
    with _connection() as conn:
        cur = conn.execute(
            "INSERT INTO sample_frames "
            "(camera, captured_at, created_at, width, height, bytes, file_path, meta_json) "
            "VALUES (?, ?, ?, ?, ?, ?, '', ?)",
            (camera, float(captured_at), time.time(), _asInt(meta.get("width")), _asInt(meta.get("height")), len(jpeg), meta_json),
        )
        sample_id = int(cur.lastrowid or 0)
        rel_path = f"{camera}/{sample_id}.jpg"
        abs_path = samplesDir() / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(jpeg)
        conn.execute("UPDATE sample_frames SET file_path = ? WHERE id = ?", (rel_path, sample_id))
        conn.commit()


def _retentionSweep() -> None:
    # As in channel_crop_store: pick victims in a short read, unlink outside
    # any transaction, then tombstone the rows in one short write.
    cap = capBytes()
    with _connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(bytes), 0) AS total FROM sample_frames WHERE deleted_at IS NULL"
        ).fetchone()
        total = int(row["total"]) if row is not None else 0
        if total <= cap:
            return
        overage = total - cap
        rows = conn.execute(
            "SELECT id, file_path, bytes FROM sample_frames WHERE deleted_at IS NULL "
            "ORDER BY (synced_at IS NULL) ASC, created_at ASC LIMIT 1000"
        ).fetchall()
    victims: list[tuple[int, str]] = []
    freed = 0
    for r in rows:
        if freed >= overage:
            break
        victims.append((int(r["id"]), str(r["file_path"])))
        freed += int(r["bytes"] or 0)
    if not victims:
        return
    base = samplesDir()
    for _, rel_path in victims:
        try:
            (base / rel_path).unlink(missing_ok=True)
        except OSError:
            pass
    now = time.time()
    with _connection() as conn:
        conn.executemany(
            "UPDATE sample_frames SET deleted_at = ? WHERE id = ?",
            [(now, sample_id) for sample_id, _ in victims],
        )
        conn.commit()
    _log("info", f"sample_store: retention evicted {len(victims)} samples ({freed / 1024 / 1024:.1f} MB)")


def removeLegacyArchive() -> None:
    """Delete the folder the previous sample pipeline archived frames in (up to
    1 GB of re-encoded copies, never uploaded once its in-memory queue was lost
    to a restart), in the background so startup does not wait on the SD card."""
    legacy = Path(__file__).resolve().parent / "blob" / "classification_training"
    if not legacy.is_dir():
        return

    def remove() -> None:
        try:
            shutil.rmtree(legacy)
            _log("info", f"sample_store: removed the old sample archive {legacy}")
        except OSError as exc:
            _log("warning", f"sample_store: could not remove the old sample archive {legacy}: {exc}")

    threading.Thread(target=remove, daemon=True, name="sample-legacy-cleanup").start()


def purgeAll() -> dict[str, Any]:
    """Delete every stored sample file, sent or not (the rows stay as
    tombstones so the sync cursor is unaffected)."""
    with _connection() as conn:
        rows = conn.execute("SELECT id, file_path, bytes FROM sample_frames WHERE deleted_at IS NULL").fetchall()
    base = samplesDir()
    for r in rows:
        try:
            (base / str(r["file_path"])).unlink(missing_ok=True)
        except OSError:
            pass
    now = time.time()
    with _connection() as conn:
        conn.executemany("UPDATE sample_frames SET deleted_at = ? WHERE id = ?", [(now, int(r["id"])) for r in rows])
        conn.commit()
    return {"deleted": len(rows), "freed_bytes": sum(int(r["bytes"] or 0) for r in rows)}


def listSamplesAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    """Rows in id order for the Hive sync worker (cursor: id > after_id)."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, camera, captured_at, created_at, width, height, bytes, meta_json, deleted_at "
            "FROM sample_frames WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    out = []
    for r in rows:
        try:
            meta = json.loads(r["meta_json"] or "{}")
        except ValueError:
            meta = {}
        out.append(
            {
                "id": int(r["id"]),
                "camera": r["camera"],
                "captured_at": r["captured_at"],
                "created_at": r["created_at"],
                "width": r["width"],
                "height": r["height"],
                "bytes": int(r["bytes"] or 0),
                "meta": meta if isinstance(meta, dict) else {},
                "evicted_locally": r["deleted_at"] is not None,
            }
        )
    return out


def getSampleFileById(sample_id: int) -> Optional[Path]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT file_path, deleted_at FROM sample_frames WHERE id = ?", (int(sample_id),)
        ).fetchone()
    if row is None or row["deleted_at"] is not None:
        return None
    abs_path = samplesDir() / str(row["file_path"])
    return abs_path if abs_path.is_file() else None


def getMaxSampleId() -> int:
    with _connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM sample_frames").fetchone()
    return int(row["m"] or 0)


def countAfter(after_id: int) -> int:
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM sample_frames WHERE id > ? AND deleted_at IS NULL", (int(after_id),)
        ).fetchone()
    return int(row["n"] or 0)


def markSyncedUpTo(max_id: int, synced_at: float) -> None:
    # Retention hint: rows at or below the lowest watermark across the enabled
    # Hive targets are on every Hive, so retention may evict them first.
    if max_id <= 0:
        return
    with _connection() as conn:
        conn.execute(
            "UPDATE sample_frames SET synced_at = ? WHERE id <= ? AND synced_at IS NULL",
            (float(synced_at), int(max_id)),
        )
        conn.commit()


def stats() -> dict[str, Any]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS b, "
            "COALESCE(SUM(CASE WHEN synced_at IS NULL THEN 1 ELSE 0 END), 0) AS unsynced "
            "FROM sample_frames WHERE deleted_at IS NULL"
        ).fetchone()
    with _counts_lock:
        counts = dict(_counts)
    return {
        "stored": int(row["n"] or 0),
        "stored_bytes": int(row["b"] or 0),
        "not_on_every_hive": int(row["unsynced"] or 0),
        "cap_bytes": capBytes(),
        "disk_free_bytes": _freeBytes(),
        "min_free_bytes": MIN_FREE_BYTES,
        **counts,
    }
