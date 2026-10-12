from __future__ import annotations

import base64
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

import db
import sync_seq

# Durable per-piece image store. Every crop gathered for a piece (the C4 burst
# plus upstream C2/C3 match crops) is written to disk as a plain JPEG and
# indexed in the shared local_state SQLite DB, so piece images survive
# restarts and LRU eviction instead of living only in the runtime-stats
# in-memory lookup. An image is ready for Hive once its piece's record exists:
# by then its used / excluded_from_result flags are final, so it takes a
# sync_seq (see sync_seq.py) and goes once, with the right flags. Images of a
# piece that never gets a record never sync. synced_at marks rows every Hive
# has, so retention can prefer wiping those files. Rows outlive their files
# (deleted_at is set, the row stays) until piece history retention removes
# the whole piece.
#
# Writes never happen on the capture / state-machine threads: the broadcaster
# enqueues (bounded, drop-on-full) and a single daemon worker does base64
# decode, file writes, inserts, and retention sweeps.

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
# Pieces whose used/excluded_from_result/score flags were already flushed, oldest
# first. Those flags only settle once classification applies, well after the
# images themselves were written, so they land as one late UPDATE pass per piece.
_flags_done: dict[str, None] = {}
_worker_started = threading.Event()
_worker_lock = threading.Lock()
_logger: Any = None

# Whether the last enqueue found the queue full: one warning per stretch of drops.
_dropping = False


def configure(logger: Any) -> None:
    global _logger
    _logger = logger


def _enqueue(entry: tuple[str, str, Any]) -> bool:
    global _dropping
    try:
        _queue.put_nowait(entry)
    except queue.Full:
        if not _dropping:
            _dropping = True
            _log("warning", "piece_image_store: the write queue is full; dropping images until it drains")
        return False
    _dropping = False
    return True


def _log(level: str, message: str) -> None:
    logger = _logger
    if logger is None:
        return
    try:
        getattr(logger, level)(message)
    except Exception:
        pass


def piece_images_dir() -> Path:
    return db.local_state_db_path().parent / "piece_images"


def piece_link_images_dir() -> Path:
    # Model-guess crops live in their own tree so they can never be confused
    # with (or globbed up with) the ground-truth piece_images files.
    return db.local_state_db_path().parent / "piece_link_images"


def createTables(conn: sqlite3.Connection) -> None:
    """The image tables. Run as part of piece_records' schema: whether an image
    is ready to sync depends on its piece's record."""
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
        # Set when the local file was removed by retention. The row
        # survives so the image stays addressable.
        "deleted_at REAL, "
        # Set once every enabled Hive has the image (a retention hint).
        "synced_at REAL, "
        # Classification outcome flags, updated once per piece after
        # the applied Brickognize result settles (see enqueue path).
        "used INTEGER NOT NULL DEFAULT 0, "
        "excluded_from_result INTEGER NOT NULL DEFAULT 0, "
        "score REAL, "
        "UNIQUE(piece_uuid, seq)"
        ")"
    )
    db.add_columns(conn, "piece_images", {
        "used": "INTEGER NOT NULL DEFAULT 0",
        "excluded_from_result": "INTEGER NOT NULL DEFAULT 0",
        "score": "REAL",
    })
    conn.execute(
        # Piece-link model guesses. A separate table on purpose: no
        # synced_at / sync_seq columns exist here because these rows are
        # never uploaded as piece images.
        "CREATE TABLE IF NOT EXISTS piece_link_images ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "piece_uuid TEXT NOT NULL, "
        "seq INTEGER NOT NULL, "
        "channel INTEGER, "
        "ts REAL, "
        "created_at REAL NOT NULL, "
        "score REAL, "
        "used INTEGER NOT NULL DEFAULT 0, "
        "bytes INTEGER NOT NULL, "
        "file_path TEXT NOT NULL, "
        "deleted_at REAL, "
        "UNIQUE(piece_uuid, seq)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_piece_link_images_uuid "
        "ON piece_link_images(piece_uuid)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_piece_images_uuid "
        "ON piece_images(piece_uuid)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_piece_images_live "
        "ON piece_images(created_at) WHERE deleted_at IS NULL"
    )
    conn.execute("DROP INDEX IF EXISTS idx_piece_images_unsynced")
    sync_seq.addColumn(conn, "piece_images")


def _connection():
    import piece_records  # its schema includes these tables (see createTables)

    return db.connect(piece_records._createTables)


def sequenceImages(conn: sqlite3.Connection, piece_uuid: str) -> None:
    """Make a piece's waiting images ready to sync, each with its own seq (a
    batch of the sync cursor must never split rows sharing one). Called in the
    transaction that writes the piece's record."""
    rows = conn.execute(
        "SELECT id FROM piece_images WHERE piece_uuid = ? AND sync_seq IS NULL ORDER BY seq",
        (piece_uuid,),
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE piece_images SET sync_seq = ? WHERE id = ?",
            (sync_seq.nextSeq(conn), int(row[0])),
        )


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
            # HARD GUARD: piece_images is ground truth (C4 burst -> Hive ->
            # training data). Model guesses must never enter it, whatever a
            # caller puts in recognition_image_set.
            if entry.get("source") == "link_match":
                continue
            item = {
                "image": image_b64,
                "source": entry.get("source"),
                "channel": entry.get("channel"),
                "ts": entry.get("ts"),
                "created_at": entry.get("created_at"),
                "sharpness": entry.get("sharpness"),
            }
            _enqueue(("image", piece_uuid, (seq, item)))

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
    if not _enqueue(("flags", piece_uuid, flags)):
        return
    with _seen_lock:
        _flags_done[piece_uuid] = None
        while len(_flags_done) > _MAX_SEEN_UUIDS:
            del _flags_done[next(iter(_flags_done))]


def _ensureWorker() -> None:
    if _worker_started.is_set():
        return
    with _worker_lock:
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
                elif kind == "link_image":
                    seq, item = payload
                    _writeLinkImage(piece_uuid, seq, item)
                elif kind == "flags":
                    _updateImageFlags(piece_uuid, payload)
            except Exception as exc:
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
        cur = conn.execute(
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
        # Written after its piece's record (a late frame): ready now.
        if cur.rowcount and conn.execute(
            "SELECT 1 FROM piece_records WHERE uuid = ?", (piece_uuid,)
        ).fetchone() is not None:
            conn.execute(
                "UPDATE piece_images SET sync_seq = ? WHERE id = ?",
                (sync_seq.nextSeq(conn), int(cur.lastrowid)),
            )
        conn.commit()


_link_seen_lock = threading.Lock()
_link_seen_counts: dict[str, int] = {}
_link_seen_order: list[str] = []


def enqueueKnownObjectLinkImages(payload: dict[str, Any]) -> None:
    """Persist the piece-link model's guesses from link_match_image_set.

    Entirely parallel to enqueueKnownObjectImages but writing to the separate
    piece_link_images table + directory — these are model guesses, not ground
    truth, and nothing here is ever synced to Hive as a piece image."""
    piece_uuid = payload.get("uuid")
    images = payload.get("link_match_image_set")
    if not isinstance(piece_uuid, str) or not piece_uuid or not isinstance(images, list):
        return
    with _link_seen_lock:
        already = _link_seen_counts.get(piece_uuid)
        if already is None:
            _link_seen_order.append(piece_uuid)
            while len(_link_seen_order) > _MAX_SEEN_UUIDS:
                evicted = _link_seen_order.pop(0)
                _link_seen_counts.pop(evicted, None)
            already = 0
        if len(images) > already:
            _link_seen_counts[piece_uuid] = len(images)
    if len(images) <= already:
        return
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
            "channel": entry.get("channel"),
            "ts": entry.get("ts"),
            "created_at": entry.get("created_at"),
            "score": entry.get("score"),
            "used": entry.get("used"),
        }
        _enqueue(("link_image", piece_uuid, (seq, item)))


def _writeLinkImage(piece_uuid: str, seq: int, item: dict[str, Any]) -> None:
    raw = base64.b64decode(item["image"], validate=False)
    # Distinct filename shape from piece_images on purpose ("linkguess"), so a
    # stray glob or manual copy can never pass one off as a burst frame.
    rel_path = f"{piece_uuid}/{seq:02d}_linkguess.jpg"
    abs_path = piece_link_images_dir() / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(raw)

    created_at = item.get("created_at")
    if not isinstance(created_at, (int, float)):
        created_at = time.time()
    with _connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO piece_link_images "
            "(piece_uuid, seq, channel, ts, created_at, score, used, bytes, file_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                piece_uuid,
                seq,
                item.get("channel") if isinstance(item.get("channel"), int) else None,
                item.get("ts") if isinstance(item.get("ts"), (int, float)) else None,
                float(created_at),
                item.get("score") if isinstance(item.get("score"), (int, float)) else None,
                1 if item.get("used") else 0,
                len(raw),
                rel_path,
            ),
        )
        conn.commit()


def listPieceLinkImages(piece_uuid: str) -> list[dict[str, Any]]:
    if not isinstance(piece_uuid, str) or not piece_uuid:
        return []
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, piece_uuid, seq, channel, ts, created_at, score, used, "
            "bytes, deleted_at, file_path "
            "FROM piece_link_images WHERE piece_uuid = ? ORDER BY seq ASC",
            (piece_uuid,),
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "seq": int(r["seq"]),
            "channel": r["channel"],
            "ts": r["ts"],
            "created_at": r["created_at"],
            "score": r["score"],
            "used": bool(r["used"]),
            "available_locally": r["deleted_at"] is None,
        }
        for r in rows
    ]


def getLinkImageFileById(image_id: int) -> Optional[Path]:
    with _connection() as conn:
        r = conn.execute(
            "SELECT file_path, deleted_at FROM piece_link_images WHERE id = ?",
            (int(image_id),),
        ).fetchone()
    if r is None or r["deleted_at"] is not None or not r["file_path"]:
        return None
    path = piece_link_images_dir() / str(r["file_path"])
    return path if path.is_file() else None


def _updateImageFlags(piece_uuid: str, flags: list[tuple[int, int, int, Any]]) -> None:
    # Normally this lands before the piece's record (classification settles
    # before distribution), so the images are not yet sequenced. An image that
    # already was (its record came first) changed, so it takes a new seq and
    # goes again with the final flags.
    if not flags:
        return
    with _connection() as conn:
        for seq, used, excluded, score in flags:
            row = conn.execute(
                "SELECT id, used, excluded_from_result, score, sync_seq FROM piece_images "
                "WHERE piece_uuid = ? AND seq = ?",
                (piece_uuid, seq),
            ).fetchone()
            if row is None or (row["used"], row["excluded_from_result"], row["score"]) == (used, excluded, score):
                continue
            conn.execute(
                "UPDATE piece_images SET used = ?, excluded_from_result = ?, score = ?, sync_seq = ? "
                "WHERE id = ?",
                (
                    used,
                    excluded,
                    score,
                    sync_seq.nextSeq(conn) if row["sync_seq"] is not None else None,
                    int(row["id"]),
                ),
            )
        conn.commit()


def _unlinkEvictedFiles(rel_paths: list[str], base_dir: Path) -> None:
    # Unlink everything first, then try ONE rmdir per emptied parent. rmdir on a
    # non-empty directory just fails with ENOTEMPTY, so this never lists the
    # directory - the old per-file `any(parent.iterdir())` read all ~200k names
    # on every unlink, which under sorting load made a sweep take 15-30 minutes
    # and starved crop capture for the duration.
    parents: set[Path] = set()
    for rel_path in rel_paths:
        abs_path = base_dir / rel_path
        try:
            abs_path.unlink(missing_ok=True)
        except OSError:
            continue
        if abs_path.parent != base_dir:
            parents.add(abs_path.parent)
    for parent in parents:
        try:
            parent.rmdir()
        except OSError:
            pass


def _sweepTable(
    *,
    table: str,
    order_sql: str,
    max_total_bytes: int,
    base_dir: Path,
    label: str,
) -> None:
    # Filesystem work happens OUTSIDE any transaction - same shape and same
    # reason as channel_crop_store._retentionSweep: holding the SQLite write
    # lock across hundreds of unlinks starved every other writer of
    # local_state.sqlite for minutes at a time. Victims are chosen in a short
    # read, files are unlinked with no transaction open, then the rows are
    # tombstoned in one batch. A crash between unlink and tombstone is
    # harmless: the next sweep re-selects the rows and tombstones them.
    with _connection() as conn:
        row = conn.execute(
            f"SELECT COALESCE(SUM({db.on_disk_bytes_sql()}), 0) AS total FROM {table} WHERE deleted_at IS NULL"
        ).fetchone()
        total = int(row["total"]) if row is not None else 0
        if total <= max_total_bytes:
            return
        overage = total - max_total_bytes
        rows = conn.execute(
            f"SELECT id, file_path, bytes FROM {table} WHERE deleted_at IS NULL "
            f"ORDER BY {order_sql} LIMIT 500"
        ).fetchall()
    victims: list[tuple[int, str]] = []
    freed = 0
    for r in rows:
        if freed >= overage:
            break
        victims.append((int(r["id"]), str(r["file_path"])))
        freed += db.on_disk_bytes(r["bytes"])
    if not victims:
        return
    _unlinkEvictedFiles([rel_path for _, rel_path in victims], base_dir)
    now = time.time()
    with _connection() as conn:
        conn.executemany(
            f"UPDATE {table} SET deleted_at = ? WHERE id = ?",
            [(now, image_id) for image_id, _ in victims],
        )
        conn.commit()
    evicted = len(victims)
    _log(
        "info",
        f"piece_image_store: {label} evicted {evicted} files ({freed / 1024 / 1024:.1f} MB)",
    )


def _retentionSweep() -> None:
    _sweepTable(
        table="piece_images",
        # Synced files go first ((synced_at IS NULL)=0 sorts before 1), oldest
        # first within each group.
        order_sql="(synced_at IS NULL) ASC, created_at ASC",
        max_total_bytes=_MAX_TOTAL_BYTES,
        base_dir=piece_images_dir(),
        label="retention",
    )
    _linkRetentionSweep()


# Model guesses are strictly less precious than ground truth, so they get a
# smaller budget and evict oldest-first (nothing syncs, so no synced tier).
_MAX_LINK_TOTAL_BYTES = 200 * 1024 * 1024


def _linkRetentionSweep() -> None:
    _sweepTable(
        table="piece_link_images",
        order_sql="created_at ASC",
        max_total_bytes=_MAX_LINK_TOTAL_BYTES,
        base_dir=piece_link_images_dir(),
        label="link retention",
    )


def listPieceImages(piece_uuid: str) -> list[dict[str, Any]]:
    if not isinstance(piece_uuid, str) or not piece_uuid:
        return []
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, piece_uuid, seq, source, channel, ts, created_at, sharpness, "
            "bytes, deleted_at, synced_at, used, excluded_from_result, score "
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


def listImagesAfter(after_seq: int, limit: int) -> list[dict[str, Any]]:
    # Ready rows in sync_seq order for the Hive sync worker (cursor: sync_seq >
    # a per-target watermark, see sync_seq.py). Includes deleted_at so the
    # worker knows file-present (upload pixels) vs evicted (metadata-only).
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, sync_seq, piece_uuid, seq, source, channel, ts, created_at, sharpness, "
            "bytes, deleted_at, used, excluded_from_result, score "
            "FROM piece_images WHERE sync_seq > ? ORDER BY sync_seq ASC LIMIT ?",
            (int(after_seq), int(limit)),
        ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "sync_seq": int(r["sync_seq"]),
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


def countImagesAfter(after_seq: int) -> int:
    """Ready images a target with this watermark has yet to receive."""
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM piece_images WHERE sync_seq > ?", (int(after_seq),)
        ).fetchone()
    return int(row["n"] or 0)


def markImagesSyncedUpTo(max_seq: int, synced_at: float) -> None:
    # Retention hint only: stamp synced_at on rows at/below the min watermark
    # across all enabled hive targets, so retention only evicts a crop once
    # EVERY hive has it (retention prefers synced files). Not the sync cursor.
    if max_seq <= 0:
        return
    with _connection() as conn:
        conn.execute(
            "UPDATE piece_images SET synced_at = ? WHERE sync_seq <= ? AND synced_at IS NULL",
            (float(synced_at), int(max_seq)),
        )
        conn.commit()
