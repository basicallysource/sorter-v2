from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from local_state import local_state_db_path

# Durable per-piece sorting history. Lives in the shared local_state SQLite DB
# (same file as the rest of the machine's persistent state) but owns its own
# table and module. Replaces the old run_recorder JSON dumps, which only landed
# on a graceful shutdown — the dev soft-restart calls os._exit(0) and skipped
# the save, so the overwhelming majority of sorted pieces were never recorded.
# Here each piece is written the instant it commits in distribution, so the
# history survives any restart. Everything is a typed column — no JSON blobs.

_INIT_LOCK = threading.Lock()
_initialized = False


def _connect() -> sqlite3.Connection:
    db_path = local_state_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
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
                "CREATE TABLE IF NOT EXISTS piece_records ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "uuid TEXT UNIQUE, "
                "run_id TEXT, "
                "machine_id TEXT, "
                "seen_at REAL, "
                "recorded_at REAL, "
                "classification_status TEXT, "
                "part_id TEXT, "
                "part_name TEXT, "
                "color_id TEXT, "
                "color_name TEXT, "
                "category_id TEXT, "
                "confidence REAL, "
                "bin_x INTEGER, "
                "bin_y INTEGER, "
                "bin_z INTEGER, "
                # 1 when the piece was reaped for going silent without ever
                # reaching the distributed stage (see reapStuckPieces). Such
                # rows have no bin; they are recorded so the history still shows
                # what got stuck instead of silently dropping it.
                "dead INTEGER NOT NULL DEFAULT 0"
                ")"
            )
            # Migrate DBs created before the dead column existed.
            try:
                conn.execute("ALTER TABLE piece_records ADD COLUMN dead INTEGER NOT NULL DEFAULT 0")
            except sqlite3.OperationalError:
                pass  # column already present
            existing_columns = {
                r["name"]
                for r in conn.execute("PRAGMA table_info(piece_records)").fetchall()
            }
            if "brickognize_preview_url" not in existing_columns:
                conn.execute(
                    "ALTER TABLE piece_records ADD COLUMN brickognize_preview_url TEXT"
                )
            # Brickognize-correction columns. The first four are provenance copied
            # from the applied classification request (needed to address a
            # correction to Brickognize's feedback API). The rest hold the user's
            # correction: part_correct is NULL (unreviewed) / 1 (right) / 0
            # (wrong); color_corrected_id is the user-picked true BrickLink color;
            # the *_feedback_submitted flags record whether we sent it to
            # Brickognize; correction_updated_at is the last correction edit time.
            for _col, _ddl in (
                ("brickognize_listing_id", "TEXT"),
                ("brickognize_item_rank", "INTEGER"),
                ("brickognize_item_type", "TEXT"),
                ("brickognize_color_rank", "INTEGER"),
                ("part_correct", "INTEGER"),
                ("color_corrected_id", "TEXT"),
                ("part_feedback_submitted", "INTEGER NOT NULL DEFAULT 0"),
                ("color_feedback_submitted", "INTEGER NOT NULL DEFAULT 0"),
                ("correction_updated_at", "REAL"),
                # Which service actually produced this piece's color / mold (see
                # classification.providers). NULL on rows written before the
                # providers were selectable.
                ("color_provider", "TEXT"),
                ("mold_provider", "TEXT"),
            ):
                if _col not in existing_columns:
                    conn.execute(
                        f"ALTER TABLE piece_records ADD COLUMN {_col} {_ddl}"
                    )
            # Append-only log of correction edits, drained to Hive by the sync
            # worker on its own watermark (id). Each edit appends a fresh row so
            # the monotonic id advances even when the same piece is corrected
            # twice (e.g. mark, then submit); Hive upserts the latest per piece.
            conn.execute(
                "CREATE TABLE IF NOT EXISTS piece_corrections ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "piece_uuid TEXT NOT NULL, "
                "part_correct INTEGER, "
                "color_corrected_id TEXT, "
                "part_feedback_submitted INTEGER NOT NULL DEFAULT 0, "
                "color_feedback_submitted INTEGER NOT NULL DEFAULT 0, "
                "updated_at REAL NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_piece_corrections_uuid "
                "ON piece_corrections(piece_uuid)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_piece_records_seen "
                "ON piece_records(seen_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_piece_records_part "
                "ON piece_records(part_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_piece_records_run "
                "ON piece_records(run_id)"
            )
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def recordPiece(
    piece: dict[str, Any],
    *,
    run_id: Optional[str] = None,
    machine_id: Optional[str] = None,
) -> None:
    uuid_val = piece.get("uuid")
    if not isinstance(uuid_val, str):
        return
    dest = piece.get("destination_bin")
    bin_x = bin_y = bin_z = None
    if isinstance(dest, (list, tuple)) and len(dest) == 3:
        bin_x, bin_y, bin_z = (int(dest[0]), int(dest[1]), int(dest[2]))
    seen_at = piece.get("created_at")
    recorded_at = piece.get("distributed_at") or time.time()
    dead = 1 if piece.get("dead") else 0
    with _connection() as conn:
        # Upsert (not INSERT OR IGNORE): a piece can be recorded early by the
        # correction API straight from memory (so a just-classified piece is
        # correctable before it distributes), then re-recorded at distribution
        # with its bin. On conflict we refresh the classification/bin columns but
        # NEVER touch the correction columns (part_correct, color_corrected_id,
        # *_feedback_submitted, correction_updated_at) so a recorded correction
        # survives the distribution write.
        conn.execute(
            "INSERT INTO piece_records "
            "(uuid, run_id, machine_id, seen_at, recorded_at, classification_status, "
            "part_id, part_name, color_id, color_name, category_id, confidence, "
            "bin_x, bin_y, bin_z, dead, brickognize_preview_url, "
            "brickognize_listing_id, brickognize_item_rank, brickognize_item_type, "
            "brickognize_color_rank, color_provider, mold_provider) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(uuid) DO UPDATE SET "
            "run_id=excluded.run_id, machine_id=excluded.machine_id, "
            "seen_at=excluded.seen_at, recorded_at=excluded.recorded_at, "
            "classification_status=excluded.classification_status, "
            "part_id=excluded.part_id, part_name=excluded.part_name, "
            "color_id=excluded.color_id, color_name=excluded.color_name, "
            "category_id=excluded.category_id, confidence=excluded.confidence, "
            "bin_x=excluded.bin_x, bin_y=excluded.bin_y, bin_z=excluded.bin_z, "
            "dead=excluded.dead, brickognize_preview_url=excluded.brickognize_preview_url, "
            "brickognize_listing_id=excluded.brickognize_listing_id, "
            "brickognize_item_rank=excluded.brickognize_item_rank, "
            "brickognize_item_type=excluded.brickognize_item_type, "
            "brickognize_color_rank=excluded.brickognize_color_rank, "
            "color_provider=excluded.color_provider, "
            "mold_provider=excluded.mold_provider",
            (
                uuid_val,
                run_id,
                machine_id,
                float(seen_at) if isinstance(seen_at, (int, float)) else None,
                float(recorded_at) if isinstance(recorded_at, (int, float)) else None,
                piece.get("classification_status"),
                piece.get("part_id"),
                piece.get("part_name"),
                piece.get("color_id"),
                piece.get("color_name"),
                piece.get("category_id"),
                piece.get("confidence"),
                bin_x,
                bin_y,
                bin_z,
                dead,
                piece.get("brickognize_preview_url"),
                piece.get("brickognize_listing_id"),
                piece.get("brickognize_item_rank"),
                piece.get("brickognize_item_type"),
                piece.get("brickognize_color_rank"),
                piece.get("color_provider"),
                piece.get("mold_provider"),
            ),
        )
        conn.commit()


def getOverview() -> dict[str, Any]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT "
            "COUNT(*) AS total_pieces, "
            "COUNT(DISTINCT run_id) AS total_runs, "
            "SUM(CASE WHEN classification_status = 'classified' THEN 1 ELSE 0 END) AS classified_pieces, "
            "SUM(CASE WHEN bin_x IS NOT NULL THEN 1 ELSE 0 END) AS distributed_pieces, "
            "COUNT(DISTINCT CASE WHEN part_id IS NOT NULL THEN part_id END) AS unique_parts, "
            "COUNT(DISTINCT CASE WHEN color_id IS NOT NULL THEN color_id END) AS unique_colors, "
            "MIN(seen_at) AS first_seen, "
            "MAX(seen_at) AS last_seen "
            "FROM piece_records"
        ).fetchone()
    return {
        "total_runs": int(row["total_runs"] or 0),
        "total_pieces": int(row["total_pieces"] or 0),
        "classified_pieces": int(row["classified_pieces"] or 0),
        "distributed_pieces": int(row["distributed_pieces"] or 0),
        "unique_parts": int(row["unique_parts"] or 0),
        "unique_colors": int(row["unique_colors"] or 0),
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
    }


# Prices are static per (part_id, color_id) for a machine's lifetime, so a
# process-wide dict avoids re-hitting parts.db for every request. Misses (no
# metadata / no positive price) are cached as None so unknown parts don't
# retrigger lookups either.
_PRICE_CACHE: dict[tuple[Optional[str], Optional[str]], Optional[float]] = {}
_PRICE_CACHE_LOCK = threading.Lock()


def peekCachedPrice(part_id: Optional[str], color_id: Optional[str]) -> tuple[bool, Optional[float]]:
    key = (part_id, color_id)
    with _PRICE_CACHE_LOCK:
        if key in _PRICE_CACHE:
            return True, _PRICE_CACHE[key]
    return False, None


def getCachedPrice(gc: Any, part_id: Optional[str], color_id: Optional[str]) -> Optional[float]:
    key = (part_id, color_id)
    with _PRICE_CACHE_LOCK:
        if key in _PRICE_CACHE:
            return _PRICE_CACHE[key]
    if part_id is None:
        price_value: Optional[float] = None
    else:
        from piece_metadata_db import getLocalPieceMetadata

        metadata = getLocalPieceMetadata(gc, part_id, color_id)
        price = metadata.get("moving_avg_price") if metadata else None
        price_value = float(price) if isinstance(price, (int, float)) and price > 0 else None
    with _PRICE_CACHE_LOCK:
        _PRICE_CACHE[key] = price_value
    return price_value


_VALUE_STATS_TTL_S = 60.0
_VALUE_STATS_LOCK = threading.Lock()
_value_stats_memo: Optional[tuple[float, tuple[int, int], dict[str, Any]]] = None


def _pieceCountGuard(conn: sqlite3.Connection) -> tuple[int, int]:
    row = conn.execute(
        "SELECT COUNT(*) AS c, COALESCE(MAX(id), 0) AS m FROM piece_records"
    ).fetchone()
    return (int(row["c"] or 0), int(row["m"] or 0))


def getValueStats(gc: Any) -> dict[str, Any]:
    # Estimated BrickLink value of every identified piece ever recorded, computed
    # on the fly from the local price DB — no stored price column / backfill
    # needed. We group by (part_id, color_id) so each distinct part is priced
    # once and multiplied by its count, all-time and last-24h. The full result is
    # memoized (short TTL because the 24h window drifts) and invalidated the
    # moment the table changes, so repeated dashboard polls are near-free.
    global _value_stats_memo

    cutoff = time.time() - 86400.0
    with _connection() as conn:
        guard = _pieceCountGuard(conn)
        with _VALUE_STATS_LOCK:
            memo = _value_stats_memo
            if memo is not None and memo[1] == guard and time.time() < memo[0]:
                return memo[2]
        rows = conn.execute(
            "SELECT part_id, color_id, COUNT(*) AS n, "
            "SUM(CASE WHEN COALESCE(recorded_at, seen_at) >= ? THEN 1 ELSE 0 END) AS n24 "
            "FROM piece_records "
            "WHERE part_id IS NOT NULL AND dead = 0 "
            "GROUP BY part_id, color_id",
            (cutoff,),
        ).fetchall()

    all_total = all_priced = 0
    d24_total = d24_priced = 0
    all_value = d24_value = 0.0
    for r in rows:
        n = int(r["n"] or 0)
        n24 = int(r["n24"] or 0)
        all_total += n
        d24_total += n24
        price = getCachedPrice(gc, r["part_id"], r["color_id"])
        if price is not None:
            all_value += price * n
            all_priced += n
            d24_value += price * n24
            d24_priced += n24

    result = {
        "currency": "USD",
        "all_time": {
            "pieces": all_total,
            "priced_pieces": all_priced,
            "value_usd": round(all_value, 2),
        },
        "last_24h": {
            "pieces": d24_total,
            "priced_pieces": d24_priced,
            "value_usd": round(d24_value, 2),
        },
    }
    with _VALUE_STATS_LOCK:
        _value_stats_memo = (time.time() + _VALUE_STATS_TTL_S, guard, result)
    return result


# piece_images lives in the same DB file but is created lazily by
# piece_image_store — a fresh install can query pieces before any image was
# ever written, so the EXISTS subquery must be guarded. Once the table exists
# it never goes away, so a positive check is cached for the process lifetime.
_piece_images_table_seen = False


def _hasPieceImagesTable(conn: sqlite3.Connection) -> bool:
    global _piece_images_table_seen
    if _piece_images_table_seen:
        return True
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'piece_images'"
    ).fetchone()
    if row is not None:
        _piece_images_table_seen = True
        return True
    return False


_SUMMARY_COLUMNS = (
    "id, uuid, run_id, seen_at, recorded_at, classification_status, "
    "part_id, part_name, color_id, color_name, category_id, confidence, "
    "bin_x, bin_y, bin_z, dead, brickognize_preview_url, "
    "brickognize_listing_id, part_correct, color_corrected_id, "
    "part_feedback_submitted, color_feedback_submitted, "
    "color_provider, mold_provider"
)


def _summarySelect(conn: sqlite3.Connection) -> str:
    has_images_expr = (
        "EXISTS(SELECT 1 FROM piece_images pi WHERE pi.piece_uuid = piece_records.uuid)"
        if _hasPieceImagesTable(conn)
        else "0"
    )
    return f"SELECT {_SUMMARY_COLUMNS}, {has_images_expr} AS has_images FROM piece_records"


def _estValue(gc: Any, part_id: Optional[str], color_id: Optional[str]) -> Optional[float]:
    if part_id is None:
        return None
    if gc is None:
        _, price = peekCachedPrice(part_id, color_id)
        return price
    return getCachedPrice(gc, part_id, color_id)


def _rowToSummary(gc: Any, row: sqlite3.Row) -> dict[str, Any]:
    bin_ref = (
        {"x": int(row["bin_x"]), "y": int(row["bin_y"]), "z": int(row["bin_z"])}
        if row["bin_x"] is not None
        else None
    )
    return {
        "uuid": row["uuid"],
        "run_id": row["run_id"],
        "seen_at": row["seen_at"],
        "recorded_at": row["recorded_at"],
        "classification_status": row["classification_status"],
        "part_id": row["part_id"],
        "part_name": row["part_name"],
        "color_id": row["color_id"],
        "color_name": row["color_name"],
        "category_id": row["category_id"],
        "confidence": row["confidence"],
        "bin": bin_ref,
        "dead": bool(row["dead"]),
        "has_images": bool(row["has_images"]),
        "preview_url": row["brickognize_preview_url"],
        "est_value": _estValue(gc, row["part_id"], row["color_id"]),
        # Brickognize-correction state. correctable is True when we captured a
        # listing id for this piece (only then can a correction be submitted).
        # part_correct is None (unreviewed) / True / False; color_corrected_id is
        # the user-picked true color; the submitted flags say whether we sent the
        # correction to Brickognize.
        "correctable": row["brickognize_listing_id"] is not None,
        "part_correct": (
            None if row["part_correct"] is None else bool(row["part_correct"])
        ),
        "color_corrected_id": row["color_corrected_id"],
        "part_feedback_submitted": bool(row["part_feedback_submitted"]),
        "color_feedback_submitted": bool(row["color_feedback_submitted"]),
        "color_provider": row["color_provider"],
        "mold_provider": row["mold_provider"],
    }


def _buildFilters(
    *,
    status: Optional[list[str]] = None,
    part_id: Optional[str] = None,
    color_id: Optional[str] = None,
    run_id: Optional[str] = None,
    dead: Optional[bool] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        placeholders = ", ".join("?" for _ in status)
        clauses.append(f"classification_status IN ({placeholders})")
        params.extend(status)
    if part_id is not None:
        clauses.append("part_id = ?")
        params.append(part_id)
    if color_id is not None:
        clauses.append("color_id = ?")
        params.append(color_id)
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if dead is not None:
        clauses.append("dead = ?")
        params.append(1 if dead else 0)
    if date_from is not None:
        clauses.append("seen_at >= ?")
        params.append(float(date_from))
    if date_to is not None:
        clauses.append("seen_at <= ?")
        params.append(float(date_to))
    return clauses, params


def listPieces(
    gc: Any,
    *,
    limit: int = 100,
    cursor: Optional[int] = None,
    status: Optional[list[str]] = None,
    part_id: Optional[str] = None,
    color_id: Optional[str] = None,
    run_id: Optional[str] = None,
    dead: Optional[bool] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
    sort: str = "recent",
) -> dict[str, Any]:
    # Keyset pagination on the autoincrement id: non-null, unique, and ≈
    # recording order — unlike seen_at, which is nullable (NULL rows would
    # silently vanish from a seen_at-keyed cursor).
    limit = max(1, min(limit, 200))
    clauses, params = _buildFilters(
        status=status,
        part_id=part_id,
        color_id=color_id,
        run_id=run_id,
        dead=dead,
        date_from=date_from,
        date_to=date_to,
    )
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    page_clauses = list(clauses)
    page_params = list(params)
    if cursor is not None:
        page_clauses.append("id < ?" if sort == "recent" else "id > ?")
        page_params.append(int(cursor))
    page_where = (" WHERE " + " AND ".join(page_clauses)) if page_clauses else ""
    order = "id DESC" if sort == "recent" else "id ASC"
    with _connection() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS c FROM piece_records{where}", params
        ).fetchone()
        total = int(total_row["c"] or 0)
        rows = conn.execute(
            f"{_summarySelect(conn)}{page_where} ORDER BY {order} LIMIT ?",
            page_params + [limit + 1],
        ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [_rowToSummary(gc, r) for r in rows]
    next_cursor = str(rows[-1]["id"]) if has_more and rows else None
    return {"items": items, "next_cursor": next_cursor, "total": total}


def getPieceSummaryByUuid(gc: Any, uuid_val: str) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        row = conn.execute(
            f"{_summarySelect(conn)} WHERE uuid = ?", (uuid_val,)
        ).fetchone()
    if row is None:
        return None
    return _rowToSummary(gc, row)


def iterPieceSummaries(
    gc: Any,
    *,
    status: Optional[list[str]] = None,
    part_id: Optional[str] = None,
    color_id: Optional[str] = None,
    run_id: Optional[str] = None,
    dead: Optional[bool] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
    sort: str = "recent",
    chunk_size: int = 1000,
) -> Iterator[dict[str, Any]]:
    # Full filtered export: keyset chunks on a short-lived connection each, so
    # a multi-minute CSV download never pins one read transaction open against
    # the live write path.
    clauses, params = _buildFilters(
        status=status,
        part_id=part_id,
        color_id=color_id,
        run_id=run_id,
        dead=dead,
        date_from=date_from,
        date_to=date_to,
    )
    order = "id DESC" if sort == "recent" else "id ASC"
    cursor_id: Optional[int] = None
    while True:
        page_clauses = list(clauses)
        page_params = list(params)
        if cursor_id is not None:
            page_clauses.append("id < ?" if sort == "recent" else "id > ?")
            page_params.append(cursor_id)
        page_where = (" WHERE " + " AND ".join(page_clauses)) if page_clauses else ""
        with _connection() as conn:
            rows = conn.execute(
                f"{_summarySelect(conn)}{page_where} ORDER BY {order} LIMIT ?",
                page_params + [chunk_size],
            ).fetchall()
        for row in rows:
            yield _rowToSummary(gc, row)
        if len(rows) < chunk_size:
            return
        cursor_id = int(rows[-1]["id"])


_SYNC_COLUMNS = (
    "id, uuid, run_id, machine_id, seen_at, recorded_at, classification_status, "
    "part_id, part_name, color_id, color_name, category_id, confidence, "
    "bin_x, bin_y, bin_z, dead, brickognize_preview_url, "
    "brickognize_listing_id, brickognize_item_rank, brickognize_item_type, "
    "brickognize_color_rank, color_provider, mold_provider"
)


def listRecordsAfter(id_cursor: int, limit: int) -> list[dict[str, Any]]:
    # Full-fidelity rows ASC by id for the Hive sync worker's watermark cursor.
    # id is the monotonic sync cursor; uuid is the natural upsert key on Hive.
    with _connection() as conn:
        rows = conn.execute(
            f"SELECT {_SYNC_COLUMNS} FROM piece_records WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(id_cursor), int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def getMaxRecordId() -> int:
    with _connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM piece_records").fetchone()
    return int(row["m"] or 0)


# --- Brickognize corrections -------------------------------------------------

# Fields the correction API needs to build a Brickognize feedback call and to
# render current state, resolved by uuid.
_CORRECTION_CONTEXT_COLUMNS = (
    "uuid, part_id, color_id, color_name, "
    "brickognize_listing_id, brickognize_item_rank, brickognize_item_type, "
    "brickognize_color_rank, part_correct, color_corrected_id, "
    "part_feedback_submitted, color_feedback_submitted"
)


def _appendCorrectionLog(conn: sqlite3.Connection, uuid_val: str) -> None:
    # Snapshot the current correction state into the append-only sync log so the
    # Hive sync worker's watermark advances and picks up this edit.
    row = conn.execute(
        "SELECT part_correct, color_corrected_id, part_feedback_submitted, "
        "color_feedback_submitted, correction_updated_at "
        "FROM piece_records WHERE uuid = ?",
        (uuid_val,),
    ).fetchone()
    if row is None:
        return
    conn.execute(
        "INSERT INTO piece_corrections "
        "(piece_uuid, part_correct, color_corrected_id, part_feedback_submitted, "
        "color_feedback_submitted, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            uuid_val,
            row["part_correct"],
            row["color_corrected_id"],
            row["part_feedback_submitted"],
            row["color_feedback_submitted"],
            row["correction_updated_at"] if row["correction_updated_at"] is not None else time.time(),
        ),
    )


def getCorrectionContext(uuid_val: str) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        row = conn.execute(
            f"SELECT {_CORRECTION_CONTEXT_COLUMNS} FROM piece_records WHERE uuid = ?",
            (uuid_val,),
        ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["part_correct"] = None if d["part_correct"] is None else bool(d["part_correct"])
    d["part_feedback_submitted"] = bool(d["part_feedback_submitted"])
    d["color_feedback_submitted"] = bool(d["color_feedback_submitted"])
    return d


def setPieceCorrection(
    uuid_val: str,
    *,
    set_part: bool = False,
    part_correct: Optional[bool] = None,
    set_color: bool = False,
    color_corrected_id: Optional[str] = None,
) -> bool:
    # Update the user's correction verdict on a piece. ``set_part``/``set_color``
    # gate which fields change so the part check/x and the color dropdown can be
    # edited independently. Appends to the sync log. Returns False if no such
    # piece exists.
    now = time.time()
    sets = ["correction_updated_at = ?"]
    params: list[Any] = [now]
    if set_part:
        sets.append("part_correct = ?")
        params.append(None if part_correct is None else (1 if part_correct else 0))
    if set_color:
        sets.append("color_corrected_id = ?")
        params.append(str(color_corrected_id) if color_corrected_id is not None else None)
    params.append(uuid_val)
    with _connection() as conn:
        cur = conn.execute(
            f"UPDATE piece_records SET {', '.join(sets)} WHERE uuid = ?", params
        )
        if cur.rowcount == 0:
            conn.commit()
            return False
        _appendCorrectionLog(conn, uuid_val)
        conn.commit()
    return True


def markFeedbackSubmitted(
    uuid_val: str, *, part: bool = False, color: bool = False
) -> bool:
    # Flag that a part and/or color correction was sent to Brickognize. Only ever
    # turns the flags on. Appends to the sync log. Returns False if unknown piece.
    if not part and not color:
        return False
    now = time.time()
    sets = ["correction_updated_at = ?"]
    params: list[Any] = [now]
    if part:
        sets.append("part_feedback_submitted = 1")
    if color:
        sets.append("color_feedback_submitted = 1")
    params.append(uuid_val)
    with _connection() as conn:
        cur = conn.execute(
            f"UPDATE piece_records SET {', '.join(sets)} WHERE uuid = ?", params
        )
        if cur.rowcount == 0:
            conn.commit()
            return False
        _appendCorrectionLog(conn, uuid_val)
        conn.commit()
    return True


def listCorrectionsAfter(id_cursor: int, limit: int) -> list[dict[str, Any]]:
    # Append-only correction log rows ASC by id for the Hive sync watermark.
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, piece_uuid, part_correct, color_corrected_id, "
            "part_feedback_submitted, color_feedback_submitted, updated_at "
            "FROM piece_corrections WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(id_cursor), int(limit)),
        ).fetchall()
    return [dict(r) for r in rows]


def getMaxCorrectionId() -> int:
    with _connection() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) AS m FROM piece_corrections"
        ).fetchone()
    return int(row["m"] or 0)


_AGGREGATES_TTL_S = 60.0
_AGGREGATES_LOCK = threading.Lock()
_aggregates_memo: dict[int, tuple[float, tuple[int, int], dict[str, Any]]] = {}


def getAggregates(gc: Any, *, days: int = 365) -> dict[str, Any]:
    # One cached payload feeding every records-page chart. Same memo policy as
    # getValueStats: short TTL plus a cheap row-count guard so a new piece
    # invalidates immediately while idle dashboard polls stay near-free.
    days = max(1, min(days, 3650))
    now = time.time()
    cutoff = now - days * 86400.0
    with _connection() as conn:
        guard = _pieceCountGuard(conn)
        with _AGGREGATES_LOCK:
            memo = _aggregates_memo.get(days)
            if memo is not None and memo[1] == guard and now < memo[0]:
                return memo[2]

        per_day_rows = conn.execute(
            "SELECT date(seen_at, 'unixepoch', 'localtime') AS day, COUNT(*) AS cnt "
            "FROM piece_records "
            "WHERE dead = 0 AND seen_at IS NOT NULL AND seen_at >= ? "
            "GROUP BY day ORDER BY day",
            (cutoff,),
        ).fetchall()
        status_rows = conn.execute(
            "SELECT CASE WHEN dead = 1 THEN 'dead' "
            "ELSE COALESCE(classification_status, 'unknown') END AS status, "
            "COUNT(*) AS cnt FROM piece_records GROUP BY 1 ORDER BY cnt DESC"
        ).fetchall()
        first_seen_rows = conn.execute(
            "SELECT day, COUNT(*) AS cnt FROM ("
            "SELECT date(MIN(seen_at), 'unixepoch', 'localtime') AS day "
            "FROM piece_records "
            "WHERE part_id IS NOT NULL AND seen_at IS NOT NULL "
            "GROUP BY part_id"
            ") WHERE day IS NOT NULL GROUP BY day ORDER BY day"
        ).fetchall()
        # lifetime_hourly is created lazily by lifetime_stats' first flush — a
        # fresh install can hit this endpoint before it exists.
        has_lifetime_table = (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'lifetime_hourly'"
            ).fetchone()
            is not None
        )
        sorted_seconds_rows = (
            conn.execute(
                "SELECT date(hour_start, 'unixepoch', 'localtime') AS day, "
                "SUM(seconds_sorted) AS seconds_sorted "
                "FROM lifetime_hourly WHERE hour_start >= ? GROUP BY day",
                (cutoff,),
            ).fetchall()
            if has_lifetime_table
            else []
        )
        distributed_rows = conn.execute(
            "SELECT date(seen_at, 'unixepoch', 'localtime') AS day, COUNT(*) AS cnt "
            "FROM piece_records "
            "WHERE dead = 0 AND bin_x IS NOT NULL AND seen_at IS NOT NULL AND seen_at >= ? "
            "GROUP BY day",
            (cutoff,),
        ).fetchall()
        color_rows = conn.execute(
            "SELECT color_id, MAX(color_name) AS color_name, COUNT(*) AS cnt "
            "FROM piece_records WHERE color_id IS NOT NULL "
            "GROUP BY color_id ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        part_rows = conn.execute(
            "SELECT part_id, MAX(part_name) AS part_name, COUNT(*) AS cnt "
            "FROM piece_records WHERE part_id IS NOT NULL "
            "GROUP BY part_id ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        value_group_rows = conn.execute(
            "SELECT date(COALESCE(recorded_at, seen_at), 'unixepoch', 'localtime') AS day, "
            "part_id, color_id, COUNT(*) AS cnt "
            "FROM piece_records "
            "WHERE dead = 0 AND part_id IS NOT NULL "
            "AND COALESCE(recorded_at, seen_at) >= ? "
            "GROUP BY day, part_id, color_id",
            (cutoff,),
        ).fetchall()

    unique_cumulative: list[dict[str, Any]] = []
    running = 0
    for r in first_seen_rows:
        running += int(r["cnt"] or 0)
        unique_cumulative.append({"date": r["day"], "count": running})

    seconds_by_day = {
        r["day"]: float(r["seconds_sorted"] or 0.0)
        for r in sorted_seconds_rows
        if r["day"] is not None
    }
    ppm_per_day: list[dict[str, Any]] = []
    for r in distributed_rows:
        day = r["day"]
        seconds_sorted = seconds_by_day.get(day, 0.0)
        # Under a minute of tracked sorting can't support a rate — mirrors the
        # best-hour PPM guard so a stray piece in an idle day isn't a spike.
        if day is None or seconds_sorted < 60.0:
            continue
        ppm_per_day.append(
            {"date": day, "ppm": round(int(r["cnt"] or 0) * 60.0 / seconds_sorted, 2)}
        )

    value_by_day: dict[str, float] = {}
    for r in value_group_rows:
        day = r["day"]
        if day is None:
            continue
        price = _estValue(gc, r["part_id"], r["color_id"])
        if price is None:
            continue
        value_by_day[day] = value_by_day.get(day, 0.0) + price * int(r["cnt"] or 0)

    result = {
        "per_day": [
            {"date": r["day"], "count": int(r["cnt"] or 0)}
            for r in per_day_rows
            if r["day"] is not None
        ],
        "status_breakdown": [
            {"status": r["status"], "count": int(r["cnt"] or 0)} for r in status_rows
        ],
        "unique_parts_cumulative": unique_cumulative,
        "ppm_per_day": ppm_per_day,
        "per_color": [
            {
                "color_id": r["color_id"],
                "color_name": r["color_name"],
                "count": int(r["cnt"] or 0),
            }
            for r in color_rows
        ],
        "top_parts": [
            {
                "part_id": r["part_id"],
                "part_name": r["part_name"],
                "count": int(r["cnt"] or 0),
            }
            for r in part_rows
        ],
        "value_per_day": [
            {"date": day, "value": round(value, 2)}
            for day, value in sorted(value_by_day.items())
        ],
    }
    with _AGGREGATES_LOCK:
        _aggregates_memo[days] = (time.time() + _AGGREGATES_TTL_S, guard, result)
    return result
