from __future__ import annotations

import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from local_state import local_state_db_path

# Durable store for UNLABELED channel bbox crops. Unlike piece_image_store
# (which keys every crop to a known piece_uuid gathered during classification),
# this store holds crops of pieces seen on the upstream feeder channels (C2/C3)
# where we do NOT yet know which piece it is. Each crop is tagged with the
# metadata a cheap time/angle heuristic can later use to guess "possibly the
# same piece": the channel, the frame timestamp, the piece's signed
# center-of-mass distance to the exit zone in output degrees
# (com_forward_to_exit_deg), the zone the COM sits in, and the advisory
# per-pass ByteTrack id (crops sharing one (channel, track_id) over a short
# window are the same physical piece).
#
# Rows carry an autoincrement id (the sync cursor) plus hive sync markers
# (synced_at / hive_crop_id) mirroring piece_image_store, so the shared
# HiveSyncWorker can drain them to the Hive and retention prefers evicting
# already-synced files. The cap bounds disk at ~512 MB even if sync is absent.
#
# Writes never happen on the perception hot path: the capture collector
# enqueues already-encoded JPEG bytes + metadata (bounded, drop-on-full) and a
# single daemon worker does the file write, insert, and retention sweep.

_INIT_LOCK = threading.Lock()
_initialized = False

_QUEUE_MAX_ITEMS = 512
_RETENTION_SWEEP_INTERVAL_S = 60.0
# Retention: over the cap, oldest files are deleted first, already-synced files
# before unsynced ones. 512 MB is the budget Spencer set for these crops.
_MAX_TOTAL_BYTES = 512 * 1024 * 1024

_queue: "queue.Queue[tuple[bytes, dict[str, Any]]]" = queue.Queue(maxsize=_QUEUE_MAX_ITEMS)
_worker_started = threading.Event()
_logger: Any = None

_stats_lock = threading.Lock()
_stats = {
    "enqueued": 0,
    "dropped_queue_full": 0,
    "written": 0,
    "write_errors": 0,
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


def channel_crops_dir() -> Path:
    return local_state_db_path().parent / "channel_crops"


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
                "CREATE TABLE IF NOT EXISTS channel_crops ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "channel INTEGER, "
                # Frame capture time (epoch seconds) and row insert time.
                "ts REAL, "
                "created_at REAL NOT NULL, "
                # Advisory per-pass ByteTrack id — same physical piece keeps one
                # id across frames on a channel. NULL when tracking unavailable.
                "track_id INTEGER, "
                # Signed COM distance to the exit zone in output degrees; the key
                # field the time/angle same-piece heuristic reads. NULL if unknown.
                "com_forward_to_exit_deg REAL, "
                "com_section INTEGER, "
                # 0=none, 1=drop, 2=exit_only, 3=precise (perception.arcs LUT).
                "zone_code INTEGER, "
                "sharpness REAL, "
                "bbox_x1 INTEGER, bbox_y1 INTEGER, bbox_x2 INTEGER, bbox_y2 INTEGER, "
                "bytes INTEGER NOT NULL, "
                # Path relative to channel_crops_dir().
                "file_path TEXT NOT NULL, "
                # Set when retention removed the local file; the row (and any hive
                # pointer) survives so the crop stays addressable.
                "deleted_at REAL, "
                # Hive sync markers, written by the shared HiveSyncWorker.
                "synced_at REAL, "
                "hive_crop_id TEXT"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_channel_crops_live "
                "ON channel_crops(created_at) WHERE deleted_at IS NULL"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_channel_crops_channel_ts "
                "ON channel_crops(channel, ts)"
            )
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def enqueue(jpeg: bytes, meta: dict[str, Any]) -> None:
    """Persist one already-encoded JPEG crop with its metadata. Called off the
    perception hot path by the capture collector; bounded + drop-on-full so a
    slow disk never stalls capture."""
    if not jpeg:
        return
    _ensureWorker()
    try:
        _queue.put_nowait((jpeg, dict(meta)))
        with _stats_lock:
            _stats["enqueued"] += 1
    except queue.Full:
        with _stats_lock:
            _stats["dropped_queue_full"] += 1


def _ensureWorker() -> None:
    if _worker_started.is_set():
        return
    with _INIT_LOCK:
        if _worker_started.is_set():
            return
        thread = threading.Thread(target=_workerLoop, daemon=True, name="channel-crop-store")
        thread.start()
        _worker_started.set()


def _workerLoop() -> None:
    last_sweep = 0.0
    while True:
        item: tuple[bytes, dict[str, Any]] | None
        try:
            item = _queue.get(timeout=_RETENTION_SWEEP_INTERVAL_S)
        except queue.Empty:
            item = None
        if item is not None:
            jpeg, meta = item
            try:
                _writeCrop(jpeg, meta)
                with _stats_lock:
                    _stats["written"] += 1
            except Exception as exc:
                with _stats_lock:
                    _stats["write_errors"] += 1
                _log("warning", f"channel_crop_store: failed to persist crop: {exc}")
        now = time.monotonic()
        if now - last_sweep >= _RETENTION_SWEEP_INTERVAL_S:
            last_sweep = now
            try:
                _retentionSweep()
            except Exception as exc:
                _log("warning", f"channel_crop_store: retention sweep failed: {exc}")


def _asInt(value: Any) -> Optional[int]:
    return int(value) if isinstance(value, (int, float)) else None


def _asFloat(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) else None


def _writeCrop(jpeg: bytes, meta: dict[str, Any]) -> None:
    created_at = meta.get("created_at")
    if not isinstance(created_at, (int, float)):
        created_at = time.time()
    channel = _asInt(meta.get("channel"))
    bbox = meta.get("bbox") or (None, None, None, None)
    # Insert first (file_path filled with a placeholder), then name the file by
    # the assigned rowid so the on-disk name matches the sync cursor.
    with _connection() as conn:
        cur = conn.execute(
            "INSERT INTO channel_crops "
            "(channel, ts, created_at, track_id, com_forward_to_exit_deg, com_section, "
            "zone_code, sharpness, bbox_x1, bbox_y1, bbox_x2, bbox_y2, bytes, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')",
            (
                channel,
                _asFloat(meta.get("ts")),
                float(created_at),
                _asInt(meta.get("track_id")),
                _asFloat(meta.get("com_forward_to_exit_deg")),
                _asInt(meta.get("com_section")),
                _asInt(meta.get("zone_code")),
                _asFloat(meta.get("sharpness")),
                _asInt(bbox[0]),
                _asInt(bbox[1]),
                _asInt(bbox[2]),
                _asInt(bbox[3]),
                len(jpeg),
            ),
        )
        crop_id = int(cur.lastrowid or 0)
        rel_path = f"ch{channel if channel is not None else 'x'}/{crop_id}.jpg"
        abs_path = channel_crops_dir() / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(jpeg)
        conn.execute(
            "UPDATE channel_crops SET file_path = ? WHERE id = ?", (rel_path, crop_id)
        )
        conn.commit()


def _retentionSweep() -> None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(bytes), 0) AS total FROM channel_crops WHERE deleted_at IS NULL"
        ).fetchone()
        total = int(row["total"]) if row is not None else 0
        if total <= _MAX_TOTAL_BYTES:
            return
        overage = total - _MAX_TOTAL_BYTES
        # Synced files go first ((synced_at IS NULL)=0 sorts before 1), oldest
        # first within each group.
        rows = conn.execute(
            "SELECT id, file_path, bytes FROM channel_crops WHERE deleted_at IS NULL "
            "ORDER BY (synced_at IS NULL) ASC, created_at ASC LIMIT 1000"
        ).fetchall()
        now = time.time()
        freed = 0
        evicted = 0
        for r in rows:
            if freed >= overage:
                break
            abs_path = channel_crops_dir() / str(r["file_path"])
            try:
                abs_path.unlink(missing_ok=True)
                parent = abs_path.parent
                if parent != channel_crops_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
            conn.execute(
                "UPDATE channel_crops SET deleted_at = ? WHERE id = ?",
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
            f"channel_crop_store: retention evicted {evicted} files ({freed / 1024 / 1024:.1f} MB)",
        )


def _rowToDict(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "channel": r["channel"],
        "ts": r["ts"],
        "created_at": r["created_at"],
        "track_id": r["track_id"],
        "com_forward_to_exit_deg": r["com_forward_to_exit_deg"],
        "com_section": r["com_section"],
        "zone_code": r["zone_code"],
        "sharpness": r["sharpness"],
        "bbox": [r["bbox_x1"], r["bbox_y1"], r["bbox_x2"], r["bbox_y2"]],
        "bytes": int(r["bytes"] or 0),
    }


def listCropsAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    # Rows ASC by id for the Hive sync worker; the cursor is id > after_id.
    # Includes deleted_at so the worker knows file-present vs evicted.
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, channel, ts, created_at, track_id, com_forward_to_exit_deg, "
            "com_section, zone_code, sharpness, bbox_x1, bbox_y1, bbox_x2, bbox_y2, "
            "bytes, deleted_at FROM channel_crops WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    out = []
    for r in rows:
        d = _rowToDict(r)
        d["evicted_locally"] = r["deleted_at"] is not None
        out.append(d)
    return out


def listCropsByTimeRange(t_start: float, t_end: float) -> list[dict[str, Any]]:
    # Live (non-evicted) crops whose frame ts falls in [t_start, t_end], newest
    # first. Backs the 'possibly the same piece' time/angle lookup.
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, channel, ts, created_at, track_id, com_forward_to_exit_deg, "
            "com_section, zone_code, sharpness, bbox_x1, bbox_y1, bbox_x2, bbox_y2, bytes "
            "FROM channel_crops WHERE deleted_at IS NULL AND ts >= ? AND ts <= ? "
            "ORDER BY ts DESC",
            (float(t_start), float(t_end)),
        ).fetchall()
    return [_rowToDict(r) for r in rows]


def getCropFileById(crop_id: int) -> Optional[Path]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT file_path, deleted_at FROM channel_crops WHERE id = ?",
            (int(crop_id),),
        ).fetchone()
    if row is None or row["deleted_at"] is not None:
        return None
    abs_path = channel_crops_dir() / str(row["file_path"])
    return abs_path if abs_path.is_file() else None


def getMaxCropId() -> int:
    with _connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM channel_crops").fetchone()
    return int(row["m"] or 0)


def markSyncedUpTo(max_id: int, synced_at: float) -> None:
    # Retention hint only (mirrors piece_image_store.markImagesSyncedUpTo): stamp
    # synced_at on rows at/below the min watermark across all enabled hive
    # targets so retention only evicts a crop once every hive has it.
    if max_id <= 0:
        return
    with _connection() as conn:
        conn.execute(
            "UPDATE channel_crops SET synced_at = ? WHERE id <= ? AND synced_at IS NULL",
            (float(synced_at), int(max_id)),
        )
        conn.commit()


def getStats() -> dict[str, Any]:
    with _stats_lock:
        stats = dict(_stats)
    stats["queue_depth"] = _queue.qsize()
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS total FROM channel_crops "
            "WHERE deleted_at IS NULL"
        ).fetchone()
        stats["live_files"] = int(row["n"]) if row is not None else 0
        stats["live_bytes"] = int(row["total"]) if row is not None else 0
        row = conn.execute("SELECT COUNT(*) AS n FROM channel_crops").fetchone()
        stats["total_rows"] = int(row["n"]) if row is not None else 0
    return stats
