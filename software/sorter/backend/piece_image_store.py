from __future__ import annotations

import base64
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from local_state import local_state_db_path

# Durable per-piece image store. Every crop gathered for a piece (the C4 burst
# plus upstream C2/C3 match crops) is written to disk as a plain JPEG and
# indexed in the shared local_state SQLite DB, so piece images survive
# restarts and LRU eviction instead of living only in the runtime-stats
# in-memory lookup. Rows keep a hive sync marker (synced_at / hive_image_id)
# so a background uploader can push them to the Hive and retention can prefer
# wiping already-synced files. Rows outlive their files (deleted_at is set,
# the row stays) — an evicted-but-synced image remains addressable and can be
# re-fetched from the Hive later.
#
# Writes never happen on the capture / state-machine threads: the broadcaster
# enqueues (bounded, drop-on-full) and a single daemon worker does base64
# decode, file writes, inserts, and retention sweeps.

_INIT_LOCK = threading.Lock()
_initialized = False

_QUEUE_MAX_ITEMS = 512
_RETENTION_SWEEP_INTERVAL_S = 60.0
# Retention: over the cap, oldest files are deleted first, already-synced
# files before unsynced ones. The cap bounds disk even with hive sync absent.
_MAX_TOTAL_BYTES = 500 * 1024 * 1024

# Per-uuid count of images already enqueued, so each append-only
# recognition_image_set entry is persisted exactly once across the repeated
# cumulative KnownObject observations. Bounded FIFO like the runtime lookup.
_MAX_SEEN_UUIDS = 2000

# Queue items are ("image", uuid, (seq, item)) or ("flags", uuid, flags_list).
_queue: "queue.Queue[tuple[str, str, Any]]" = queue.Queue(maxsize=_QUEUE_MAX_ITEMS)
_seen_lock = threading.Lock()
_seen_counts: dict[str, int] = {}
_seen_order: list[str] = []
# Pieces whose used/excluded_from_result/score flags were already flushed.
# Those flags only settle once classification applies, well after the images
# themselves were written, so they land as one late UPDATE pass per piece.
_flags_done: set[str] = set()
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


def piece_images_dir() -> Path:
    return local_state_db_path().parent / "piece_images"


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
                "CREATE TABLE IF NOT EXISTS piece_images ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "piece_uuid TEXT NOT NULL, "
                "seq INTEGER NOT NULL, "
                "source TEXT, "
                "channel INTEGER, "
                "ts REAL, "
                "created_at REAL NOT NULL, "
                "sharpness REAL, "
                "bytes INTEGER NOT NULL, "
                # Path relative to piece_images_dir(); NULL only for legacy rows.
                "file_path TEXT NOT NULL, "
                # Set when the local file was removed by retention. The row (and
                # any hive pointer) survives so the image stays addressable.
                "deleted_at REAL, "
                # Hive sync markers, written by the uploader once it exists.
                "synced_at REAL, "
                "hive_image_id TEXT, "
                # Classification outcome flags, updated once per piece after
                # the applied Brickognize result settles (see enqueue path).
                "used INTEGER NOT NULL DEFAULT 0, "
                "excluded_from_result INTEGER NOT NULL DEFAULT 0, "
                "score REAL, "
                "UNIQUE(piece_uuid, seq)"
                ")"
            )
            for column, decl in (
                ("used", "INTEGER NOT NULL DEFAULT 0"),
                ("excluded_from_result", "INTEGER NOT NULL DEFAULT 0"),
                ("score", "REAL"),
            ):
                try:
                    conn.execute(f"ALTER TABLE piece_images ADD COLUMN {column} {decl}")
                except sqlite3.OperationalError:
                    pass
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_piece_images_uuid "
                "ON piece_images(piece_uuid)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_piece_images_live "
                "ON piece_images(created_at) WHERE deleted_at IS NULL"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_piece_images_unsynced "
                "ON piece_images(created_at) WHERE synced_at IS NULL AND deleted_at IS NULL"
            )
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def _noteNewImages(piece_uuid: str, total_images: int) -> int:
    with _seen_lock:
        already = _seen_counts.get(piece_uuid)
        if already is None:
            _seen_order.append(piece_uuid)
            while len(_seen_order) > _MAX_SEEN_UUIDS:
                evicted = _seen_order.pop(0)
                _seen_counts.pop(evicted, None)
            already = 0
        if total_images <= already:
            return already
        _seen_counts[piece_uuid] = total_images
        return already


def enqueueKnownObjectImages(payload: dict[str, Any]) -> None:
    piece_uuid = payload.get("uuid")
    images = payload.get("recognition_image_set")
    if not isinstance(piece_uuid, str) or not piece_uuid or not isinstance(images, list):
        return
    already = _noteNewImages(piece_uuid, len(images))
    if len(images) > already:
        _ensureWorker()
        for seq in range(already, len(images)):
            entry = images[seq]
            if not isinstance(entry, dict):
                continue
            image_b64 = entry.get("image")
            if not isinstance(image_b64, str) or not image_b64:
                continue
            item = {
                "image": image_b64,
                "source": entry.get("source"),
                "channel": entry.get("channel"),
                "ts": entry.get("ts"),
                "created_at": entry.get("created_at"),
                "sharpness": entry.get("sharpness"),
            }
            try:
                _queue.put_nowait(("image", piece_uuid, (seq, item)))
                with _stats_lock:
                    _stats["enqueued"] += 1
            except queue.Full:
                with _stats_lock:
                    _stats["dropped_queue_full"] += 1

    _maybeEnqueueFlags(piece_uuid, images)


def _maybeEnqueueFlags(piece_uuid: str, images: list[Any]) -> None:
    # The used/excluded flags only become meaningful once a Brickognize result
    # was applied; until then every image reads used=False. One observation
    # with any flag set marks the piece settled and flushes all its flags.
    with _seen_lock:
        if piece_uuid in _flags_done:
            return
    settled = any(
        isinstance(e, dict) and (e.get("used") or e.get("excluded_from_result"))
        for e in images
    )
    if not settled:
        return
    flags = [
        (
            seq,
            1 if entry.get("used") else 0,
            1 if entry.get("excluded_from_result") else 0,
            entry.get("score") if isinstance(entry.get("score"), (int, float)) else None,
        )
        for seq, entry in enumerate(images)
        if isinstance(entry, dict)
    ]
    _ensureWorker()
    try:
        _queue.put_nowait(("flags", piece_uuid, flags))
    except queue.Full:
        with _stats_lock:
            _stats["dropped_queue_full"] += 1
        return
    with _seen_lock:
        _flags_done.add(piece_uuid)
        while len(_flags_done) > _MAX_SEEN_UUIDS:
            _flags_done.pop()


def _ensureWorker() -> None:
    if _worker_started.is_set():
        return
    with _INIT_LOCK:
        if _worker_started.is_set():
            return
        thread = threading.Thread(target=_workerLoop, daemon=True, name="piece-image-store")
        thread.start()
        _worker_started.set()


def _workerLoop() -> None:
    last_sweep = 0.0
    while True:
        entry: tuple[str, str, Any] | None
        try:
            entry = _queue.get(timeout=_RETENTION_SWEEP_INTERVAL_S)
        except queue.Empty:
            entry = None
        if entry is not None:
            kind, piece_uuid, payload = entry
            try:
                if kind == "image":
                    seq, item = payload
                    _writeImage(piece_uuid, seq, item)
                    with _stats_lock:
                        _stats["written"] += 1
                elif kind == "flags":
                    _updateImageFlags(piece_uuid, payload)
            except Exception as exc:
                with _stats_lock:
                    _stats["write_errors"] += 1
                _log("warning", f"piece_image_store: failed to persist {kind} for {piece_uuid[:8]}: {exc}")
        now = time.monotonic()
        if now - last_sweep >= _RETENTION_SWEEP_INTERVAL_S:
            last_sweep = now
            try:
                _retentionSweep()
            except Exception as exc:
                _log("warning", f"piece_image_store: retention sweep failed: {exc}")


def _writeImage(piece_uuid: str, seq: int, item: dict[str, Any]) -> None:
    raw = base64.b64decode(item["image"], validate=False)
    source = item.get("source")
    suffix = str(source) if isinstance(source, str) and source else "img"
    rel_path = f"{piece_uuid}/{seq:02d}_{suffix}.jpg"
    abs_path = piece_images_dir() / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(raw)

    created_at = item.get("created_at")
    if not isinstance(created_at, (int, float)):
        created_at = time.time()
    with _connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO piece_images "
            "(piece_uuid, seq, source, channel, ts, created_at, sharpness, bytes, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                piece_uuid,
                seq,
                source if isinstance(source, str) else None,
                item.get("channel") if isinstance(item.get("channel"), int) else None,
                item.get("ts") if isinstance(item.get("ts"), (int, float)) else None,
                float(created_at),
                item.get("sharpness") if isinstance(item.get("sharpness"), (int, float)) else None,
                len(raw),
                rel_path,
            ),
        )
        conn.commit()


def _updateImageFlags(piece_uuid: str, flags: list[tuple[int, int, int, Any]]) -> None:
    if not flags:
        return
    with _connection() as conn:
        conn.executemany(
            "UPDATE piece_images SET used = ?, excluded_from_result = ?, score = ? "
            "WHERE piece_uuid = ? AND seq = ?",
            [(used, excluded, score, piece_uuid, seq) for seq, used, excluded, score in flags],
        )
        conn.commit()


def _retentionSweep() -> None:
    with _connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(bytes), 0) AS total FROM piece_images WHERE deleted_at IS NULL"
        ).fetchone()
        total = int(row["total"]) if row is not None else 0
        if total <= _MAX_TOTAL_BYTES:
            return
        overage = total - _MAX_TOTAL_BYTES
        # Synced files go first ((synced_at IS NULL)=0 sorts before 1), oldest
        # first within each group.
        rows = conn.execute(
            "SELECT id, file_path, bytes FROM piece_images WHERE deleted_at IS NULL "
            "ORDER BY (synced_at IS NULL) ASC, created_at ASC LIMIT 500"
        ).fetchall()
        now = time.time()
        freed = 0
        evicted = 0
        for r in rows:
            if freed >= overage:
                break
            abs_path = piece_images_dir() / str(r["file_path"])
            try:
                abs_path.unlink(missing_ok=True)
                parent = abs_path.parent
                if parent != piece_images_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                pass
            conn.execute(
                "UPDATE piece_images SET deleted_at = ? WHERE id = ?",
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
            f"piece_image_store: retention evicted {evicted} files ({freed / 1024 / 1024:.1f} MB)",
        )


def listPieceImages(piece_uuid: str) -> list[dict[str, Any]]:
    if not isinstance(piece_uuid, str) or not piece_uuid:
        return []
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, piece_uuid, seq, source, channel, ts, created_at, sharpness, "
            "bytes, deleted_at, synced_at, hive_image_id, used, excluded_from_result, score "
            "FROM piece_images WHERE piece_uuid = ? ORDER BY seq ASC",
            (piece_uuid,),
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "piece_uuid": r["piece_uuid"],
            "seq": int(r["seq"]),
            "source": r["source"],
            "channel": r["channel"],
            "ts": r["ts"],
            "created_at": r["created_at"],
            "sharpness": r["sharpness"],
            "bytes": int(r["bytes"] or 0),
            "available_locally": r["deleted_at"] is None,
            "synced": r["synced_at"] is not None,
            "hive_image_id": r["hive_image_id"],
            "used": bool(r["used"]),
            "excluded_from_result": bool(r["excluded_from_result"]),
            "score": r["score"],
        }
        for r in rows
    ]


def getImageFile(piece_uuid: str, image_id: int) -> Optional[Path]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT file_path, deleted_at FROM piece_images WHERE id = ? AND piece_uuid = ?",
            (int(image_id), piece_uuid),
        ).fetchone()
    if row is None or row["deleted_at"] is not None:
        return None
    abs_path = piece_images_dir() / str(row["file_path"])
    return abs_path if abs_path.is_file() else None


def listImagesAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    # Full rows ASC by id for the Hive sync worker. Includes deleted_at so the
    # worker knows file-present (upload pixels) vs evicted (metadata-only). The
    # cursor is id > after_id (a per-target watermark), NOT synced_at — syncing
    # to more than one hive means a row already sent to one target must still be
    # visible to the others.
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, piece_uuid, seq, source, channel, ts, created_at, sharpness, "
            "bytes, deleted_at, used, excluded_from_result, score "
            "FROM piece_images WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "piece_uuid": r["piece_uuid"],
            "seq": int(r["seq"]),
            "source": r["source"],
            "channel": r["channel"],
            "ts": r["ts"],
            "created_at": r["created_at"],
            "sharpness": r["sharpness"],
            "bytes": int(r["bytes"] or 0),
            "evicted_locally": r["deleted_at"] is not None,
            "used": bool(r["used"]),
            "excluded_from_result": bool(r["excluded_from_result"]),
            "score": r["score"],
        }
        for r in rows
    ]


def getImageFileById(image_id: int) -> Optional[Path]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT file_path, deleted_at FROM piece_images WHERE id = ?",
            (int(image_id),),
        ).fetchone()
    if row is None or row["deleted_at"] is not None:
        return None
    abs_path = piece_images_dir() / str(row["file_path"])
    return abs_path if abs_path.is_file() else None


def getMaxImageId() -> int:
    with _connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM piece_images").fetchone()
    return int(row["m"] or 0)


def markImagesSyncedUpTo(max_id: int, synced_at: float) -> None:
    # Retention hint only: stamp synced_at on rows at/below the min watermark
    # across all enabled hive targets, so retention only evicts a crop once
    # EVERY hive has it (retention prefers synced files). Not the sync cursor.
    if max_id <= 0:
        return
    with _connection() as conn:
        conn.execute(
            "UPDATE piece_images SET synced_at = ? WHERE id <= ? AND synced_at IS NULL",
            (float(synced_at), int(max_id)),
        )
        conn.commit()


def getStats() -> dict[str, Any]:
    with _stats_lock:
        stats = dict(_stats)
    stats["queue_depth"] = _queue.qsize()
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS total FROM piece_images "
            "WHERE deleted_at IS NULL"
        ).fetchone()
        stats["live_files"] = int(row["n"]) if row is not None else 0
        stats["live_bytes"] = int(row["total"]) if row is not None else 0
        row = conn.execute("SELECT COUNT(*) AS n FROM piece_images").fetchone()
        stats["total_rows"] = int(row["n"]) if row is not None else 0
    return stats
