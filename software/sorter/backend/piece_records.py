from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any, Iterator, Optional

import db
import piece_image_store
import sync_seq

# Durable per-piece sorting history. Lives in the shared local_state SQLite DB
# (same file as the rest of the machine's persistent state) but owns its own
# table and module. Replaces the old run_recorder JSON dumps, which only landed
# on a graceful shutdown — the dev soft-restart calls os._exit(0) and skipped
# the save, so the overwhelming majority of sorted pieces were never recorded.
# Here each piece is written the instant it commits in distribution, so the
# history survives any restart. Everything is a typed column — no JSON blobs.
#
# A record changes after it is written (the distribution write after an early
# one, the reaper, the operator's verdict, a feedback flag), so it syncs to
# Hive by sync_seq (see sync_seq.py): every write takes a new one, and the
# record carries the operator's whole verdict, rejection reasons included.
#
# Retention removes records older than the piece history window once every
# Hive has them; what the totals (overview, charts, value) count from them is
# folded into piece_history_rollup first, and every total reads the
# piece_history view (live records plus the rollup).


# Every piece ever recorded, for totals: one row per live record (pieces = 1)
# and the rollup's groups. seen_at/last_seen bound each row; day is the local
# day seen; value_day the local day recorded.
_PIECE_HISTORY_VIEW = (
    "CREATE VIEW piece_history AS "
    "SELECT date(seen_at, 'unixepoch', 'localtime') AS day, "
    "date(COALESCE(recorded_at, seen_at), 'unixepoch', 'localtime') AS value_day, "
    "seen_at, seen_at AS last_seen, recorded_at, run_id, part_id, part_name, color_id, color_name, "
    "classification_status, dead, (bin_x IS NOT NULL) AS distributed, 1 AS pieces "
    "FROM piece_records "
    "UNION ALL "
    "SELECT day, day AS value_day, first_seen AS seen_at, last_seen, NULL AS recorded_at, run_id, "
    "part_id, part_name, color_id, color_name, classification_status, dead, distributed, pieces "
    "FROM piece_history_rollup"
)


def _createTables(conn: sqlite3.Connection) -> None:
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
    # Columns added after the table first shipped.
    db.add_columns(conn, "piece_records", {
        "dead": "INTEGER NOT NULL DEFAULT 0",
        "brickognize_preview_url": "TEXT",
        # Brickognize-correction columns. The first four are provenance copied
        # from the applied classification request (needed to address a
        # correction to Brickognize's feedback API). The rest hold the user's
        # correction: part_correct is NULL (unreviewed) / 1 (right) / 0
        # (wrong); color_corrected_id is the user-picked true BrickLink color;
        # the *_feedback_submitted flags record whether we sent it to
        # Brickognize; correction_updated_at is the last correction edit time.
        "brickognize_listing_id": "TEXT",
        "brickognize_item_rank": "INTEGER",
        "brickognize_item_type": "TEXT",
        "brickognize_color_rank": "INTEGER",
        "part_correct": "INTEGER",
        "color_corrected_id": "TEXT",
        "part_feedback_submitted": "INTEGER NOT NULL DEFAULT 0",
        "color_feedback_submitted": "INTEGER NOT NULL DEFAULT 0",
        "correction_updated_at": "REAL",
        # Which service actually produced this piece's color / mold (see
        # classification.providers). NULL on rows written before the
        # providers were selectable.
        "color_provider": "TEXT",
        "mold_provider": "TEXT",
        # The applied color's own score, kept apart from the mold score
        # in `confidence`. NULL on rows written before the split.
        "color_confidence": "REAL",
    })
    # Operator-flagged capture issues, one row per (piece, reason) so the
    # flags are queryable — "how many pieces were flagged blurry this
    # week" is a GROUP BY, not a scan-and-parse over blobs. Reason codes
    # are free-form slugs; the first three ("no_piece" / "multiple_pieces"
    # / "not_lego") match Hive's piece_rejections vocabulary so an
    # operator's verdict and a Hive labeler's verdict mean the same thing.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS piece_rejection_reasons ("
        "piece_uuid TEXT NOT NULL, "
        "reason TEXT NOT NULL, "
        "updated_at REAL NOT NULL, "
        "PRIMARY KEY (piece_uuid, reason)"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_piece_rejection_reasons_reason "
        "ON piece_rejection_reasons(reason)"
    )
    # Whether an image is ready to sync depends on its piece's record, so the
    # image tables are part of this schema.
    piece_image_store.createTables(conn)
    if sync_seq.addColumn(conn, "piece_records"):
        # Verdicts used to travel on their own stream (a correction journal);
        # a record carries its verdict now. Send every corrected record again
        # so a verdict that had not reached Hive yet still does.
        corrected = conn.execute(
            "SELECT id FROM piece_records WHERE correction_updated_at IS NOT NULL ORDER BY id"
        ).fetchall()
        for row in corrected:
            conn.execute(
                "UPDATE piece_records SET sync_seq = ? WHERE id = ?",
                (sync_seq.nextSeq(conn), int(row[0])),
            )
    conn.execute("DROP TABLE IF EXISTS piece_corrections")
    # What retention removed, still counted. One row per (local day seen,
    # backend run, part, colour, status, dead, distributed); group_key is
    # those joined, so a fold adds to the row it belongs to.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS piece_history_rollup ("
        "group_key TEXT PRIMARY KEY, "
        "day TEXT, "
        "run_id TEXT, "
        "part_id TEXT, "
        "color_id TEXT, "
        "classification_status TEXT, "
        "dead INTEGER NOT NULL, "
        "distributed INTEGER NOT NULL, "
        "pieces INTEGER NOT NULL, "
        "part_name TEXT, "
        "color_name TEXT, "
        "first_seen REAL, "
        "last_seen REAL"
        ")"
    )
    # Distributed pieces per hour among those retention removed, for the
    # best-hour rate (lifetime_stats).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS piece_history_hours ("
        "hour_start INTEGER PRIMARY KEY, "
        "distributed INTEGER NOT NULL"
        ")"
    )
    current = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = 'piece_history'"
    ).fetchone()
    # Replaced only when its definition changed (an upgrade), so a reader
    # never finds it missing while another module prepares this schema.
    if current is None or current[0] != _PIECE_HISTORY_VIEW:
        conn.execute("DROP VIEW IF EXISTS piece_history")
        conn.execute(_PIECE_HISTORY_VIEW)
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


def _connection():
    return db.connect(_createTables)


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
        seq = sync_seq.nextSeq(conn)
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
            "brickognize_color_rank, color_provider, mold_provider, color_confidence, sync_seq) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
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
            "mold_provider=excluded.mold_provider, "
            "color_confidence=excluded.color_confidence, "
            "sync_seq=excluded.sync_seq",
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
                piece.get("color_confidence"),
                seq,
            ),
        )
        # With its record written, the piece's images are ready for Hive.
        piece_image_store.sequenceImages(conn, uuid_val)
        conn.commit()


# The rollup group a record falls in; quote() keeps NULL apart from a value.
_ROLLUP_GROUP_KEY = (
    "printf('%s|%s|%s|%s|%s|%d|%d', quote(day), quote(run_id), quote(part_id), "
    "quote(color_id), quote(classification_status), dead, distributed)"
)


def foldIntoRollup(conn: sqlite3.Connection, record_ids: list[int]) -> None:
    """Count the records about to be removed into piece_history_rollup, in the
    caller's transaction, so every total read from piece_history stays the
    same after they are gone."""
    if not record_ids:
        return
    placeholders = ", ".join("?" for _ in record_ids)
    conn.execute(
        "INSERT INTO piece_history_rollup (group_key, day, run_id, part_id, color_id, "
        "classification_status, dead, distributed, pieces, part_name, color_name, first_seen, last_seen) "
        f"SELECT {_ROLLUP_GROUP_KEY}, day, run_id, part_id, color_id, classification_status, dead, "
        "distributed, COUNT(*), MAX(part_name), MAX(color_name), MIN(seen_at), MAX(seen_at) FROM ("
        "  SELECT date(seen_at, 'unixepoch', 'localtime') AS day, run_id, part_id, part_name, color_id, "
        "  color_name, classification_status, dead, (bin_x IS NOT NULL) AS distributed, seen_at "
        f"  FROM piece_records WHERE id IN ({placeholders})"
        ") WHERE true GROUP BY day, run_id, part_id, color_id, classification_status, dead, distributed "
        "ON CONFLICT(group_key) DO UPDATE SET pieces = pieces + excluded.pieces, "
        "part_name = COALESCE(excluded.part_name, part_name), "
        "color_name = COALESCE(excluded.color_name, color_name), "
        "first_seen = MIN(COALESCE(first_seen, excluded.first_seen), COALESCE(excluded.first_seen, first_seen)), "
        "last_seen = MAX(COALESCE(last_seen, excluded.last_seen), COALESCE(excluded.last_seen, last_seen))",
        record_ids,
    )
    conn.execute(
        "INSERT INTO piece_history_hours (hour_start, distributed) "
        "SELECT CAST(seen_at / 3600 AS INTEGER) * 3600, COUNT(*) FROM piece_records "
        f"WHERE id IN ({placeholders}) AND bin_x IS NOT NULL AND seen_at IS NOT NULL AND seen_at >= 0 "
        "GROUP BY 1 "
        "ON CONFLICT(hour_start) DO UPDATE SET distributed = distributed + excluded.distributed",
        record_ids,
    )


def getOverview() -> dict[str, Any]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT "
            "SUM(pieces) AS total_pieces, "
            "COUNT(DISTINCT run_id) AS total_runs, "
            "SUM(CASE WHEN classification_status = 'classified' THEN pieces ELSE 0 END) AS classified_pieces, "
            "SUM(CASE WHEN distributed THEN pieces ELSE 0 END) AS distributed_pieces, "
            "COUNT(DISTINCT CASE WHEN part_id IS NOT NULL THEN part_id END) AS unique_parts, "
            "COUNT(DISTINCT CASE WHEN color_id IS NOT NULL THEN color_id END) AS unique_colors, "
            "MIN(seen_at) AS first_seen, "
            "MAX(last_seen) AS last_seen "
            "FROM piece_history"
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
# process-wide dict avoids re-hitting Hive for every request. Misses (no
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
        from hive_metadata import getPieceMetadata

        metadata = getPieceMetadata(gc, part_id, color_id)
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
            "SELECT part_id, color_id, SUM(pieces) AS n, "
            "SUM(CASE WHEN COALESCE(recorded_at, seen_at) >= ? THEN pieces ELSE 0 END) AS n24 "
            "FROM piece_history "
            "WHERE part_id IS NOT NULL AND dead = 0 "
            "GROUP BY part_id, color_id",
            (cutoff,),
        ).fetchall()

    # Revalue every distinct (part, color) in one batch request to Hive (served
    # from the persistent price cache; misses filled in a single round-trip),
    # rather than a per-part lookup. Warm the in-process price cache from it so
    # later peekCachedPrice hits on the sorting hot path are free.
    from hive_metadata import getBatchMovingAvgPrices

    price_pairs = [(r["part_id"], r["color_id"]) for r in rows]
    batch_prices = getBatchMovingAvgPrices(gc, price_pairs)
    with _PRICE_CACHE_LOCK:
        for (part_id, color_id), value in batch_prices.items():
            _PRICE_CACHE[(part_id, color_id)] = value

    all_total = all_priced = 0
    d24_total = d24_priced = 0
    all_value = d24_value = 0.0
    for r in rows:
        n = int(r["n"] or 0)
        n24 = int(r["n24"] or 0)
        all_total += n
        d24_total += n24
        price = batch_prices.get((r["part_id"], r["color_id"]))
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


_SUMMARY_COLUMNS = (
    "id, uuid, run_id, seen_at, recorded_at, classification_status, "
    "part_id, part_name, color_id, color_name, category_id, confidence, "
    "bin_x, bin_y, bin_z, dead, brickognize_preview_url, "
    "brickognize_listing_id, part_correct, color_corrected_id, "
    "part_feedback_submitted, color_feedback_submitted, "
    "color_provider, mold_provider, color_confidence"
)


_SUMMARY_SELECT = (
    f"SELECT {_SUMMARY_COLUMNS}, "
    "EXISTS(SELECT 1 FROM piece_images pi WHERE pi.piece_uuid = piece_records.uuid) AS has_images, "
    "(SELECT GROUP_CONCAT(r.reason) FROM piece_rejection_reasons r "
    "WHERE r.piece_uuid = piece_records.uuid) AS rejection_reasons FROM piece_records"
)


def _writeRejectionReasons(
    conn: sqlite3.Connection, uuid_val: str, reasons: Optional[list[str]]
) -> None:
    # Replace-all: the UI sends the complete set it wants on the piece, so
    # clearing a flag is an absent code rather than a separate delete call.
    conn.execute("DELETE FROM piece_rejection_reasons WHERE piece_uuid = ?", (uuid_val,))
    now = time.time()
    for reason in dict.fromkeys(reasons or []):
        conn.execute(
            "INSERT INTO piece_rejection_reasons (piece_uuid, reason, updated_at) "
            "VALUES (?, ?, ?)",
            (uuid_val, str(reason), now),
        )


def _splitRejectionReasons(raw: Optional[str]) -> list[str]:
    # Reason codes are lowercase slugs, so a comma-joined GROUP_CONCAT (a
    # correlated subquery, so it composes with the filtered/paginated summary
    # queries without changing their row cardinality) round-trips safely. Its
    # order is unspecified in sqlite: sort here for a stable shape.
    return sorted(p for p in (raw or "").split(",") if p)


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
        "color_confidence": row["color_confidence"],
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
        "rejection_reasons": _splitRejectionReasons(row["rejection_reasons"]),
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
            f"{_SUMMARY_SELECT}{page_where} ORDER BY {order} LIMIT ?",
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
            f"{_SUMMARY_SELECT} WHERE uuid = ?", (uuid_val,)
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
                f"{_SUMMARY_SELECT}{page_where} ORDER BY {order} LIMIT ?",
                page_params + [chunk_size],
            ).fetchall()
        for row in rows:
            yield _rowToSummary(gc, row)
        if len(rows) < chunk_size:
            return
        cursor_id = int(rows[-1]["id"])


_SYNC_COLUMNS = (
    "id, sync_seq, uuid, run_id, machine_id, seen_at, recorded_at, classification_status, "
    "part_id, part_name, color_id, color_name, category_id, confidence, "
    "bin_x, bin_y, bin_z, dead, brickognize_preview_url, "
    "brickognize_listing_id, brickognize_item_rank, brickognize_item_type, "
    "brickognize_color_rank, color_provider, mold_provider, color_confidence, "
    "part_correct, color_corrected_id, part_feedback_submitted, color_feedback_submitted, "
    "correction_updated_at, "
    "(SELECT GROUP_CONCAT(r.reason) FROM piece_rejection_reasons r "
    "WHERE r.piece_uuid = piece_records.uuid) AS rejection_reasons"
)


def listRecordsAfter(seq_cursor: int, limit: int) -> list[dict[str, Any]]:
    # Full rows in sync_seq order for the Hive sync worker (see sync_seq.py):
    # the piece as it is now, the operator's verdict and rejection reasons
    # included. uuid is the natural upsert key on Hive.
    with _connection() as conn:
        rows = conn.execute(
            f"SELECT {_SYNC_COLUMNS} FROM piece_records WHERE sync_seq > ? ORDER BY sync_seq ASC LIMIT ?",
            (int(seq_cursor), int(limit)),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["rejection_reasons"] = _splitRejectionReasons(d["rejection_reasons"])
        out.append(d)
    return out


def countRecordsAfter(seq_cursor: int) -> int:
    """Records a target with this watermark has yet to receive."""
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM piece_records WHERE sync_seq > ?", (int(seq_cursor),)
        ).fetchone()
    return int(row["n"] or 0)


# --- Brickognize corrections -------------------------------------------------

# Fields the correction API needs to build a Brickognize feedback call and to
# render current state, resolved by uuid.
_CORRECTION_CONTEXT_COLUMNS = (
    "uuid, part_id, color_id, color_name, "
    "brickognize_listing_id, brickognize_item_rank, brickognize_item_type, "
    "brickognize_color_rank, part_correct, color_corrected_id, "
    "part_feedback_submitted, color_feedback_submitted"
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
    set_rejection_reasons: bool = False,
    rejection_reasons: Optional[list[str]] = None,
) -> bool:
    # Update the user's correction verdict on a piece. ``set_part``/``set_color``/
    # ``set_rejection_reasons`` gate which fields change so the part check/x, the
    # color dropdown, and the capture-issue flags can be edited independently.
    # The record takes a new sync_seq, so the verdict goes to Hive with it.
    # Returns False if no such piece exists.
    now = time.time()
    sets = ["correction_updated_at = ?", "sync_seq = ?"]
    with _connection() as conn:
        params: list[Any] = [now, sync_seq.nextSeq(conn)]
        if set_part:
            sets.append("part_correct = ?")
            params.append(None if part_correct is None else (1 if part_correct else 0))
        if set_color:
            sets.append("color_corrected_id = ?")
            params.append(str(color_corrected_id) if color_corrected_id is not None else None)
        params.append(uuid_val)
        cur = conn.execute(
            f"UPDATE piece_records SET {', '.join(sets)} WHERE uuid = ?", params
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False
        if set_rejection_reasons:
            _writeRejectionReasons(conn, uuid_val, rejection_reasons)
        conn.commit()
    return True


def markFeedbackSubmitted(
    uuid_val: str, *, part: bool = False, color: bool = False
) -> bool:
    # Flag that a part and/or color correction was sent to Brickognize. Only ever
    # turns the flags on. The record takes a new sync_seq. Returns False if
    # unknown piece.
    if not part and not color:
        return False
    now = time.time()
    sets = ["correction_updated_at = ?", "sync_seq = ?"]
    if part:
        sets.append("part_feedback_submitted = 1")
    if color:
        sets.append("color_feedback_submitted = 1")
    with _connection() as conn:
        cur = conn.execute(
            f"UPDATE piece_records SET {', '.join(sets)} WHERE uuid = ?",
            [now, sync_seq.nextSeq(conn), uuid_val],
        )
        if cur.rowcount == 0:
            conn.rollback()
            return False
        conn.commit()
    return True


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

        cutoff_day = time.strftime("%Y-%m-%d", time.localtime(cutoff))
        per_day_rows = conn.execute(
            "SELECT day, SUM(pieces) AS cnt FROM piece_history "
            "WHERE dead = 0 AND day IS NOT NULL AND day >= ? "
            "GROUP BY day ORDER BY day",
            (cutoff_day,),
        ).fetchall()
        status_rows = conn.execute(
            "SELECT CASE WHEN dead = 1 THEN 'dead' "
            "ELSE COALESCE(classification_status, 'unknown') END AS status, "
            "SUM(pieces) AS cnt FROM piece_history GROUP BY 1 ORDER BY cnt DESC"
        ).fetchall()
        first_seen_rows = conn.execute(
            "SELECT day, COUNT(*) AS cnt FROM ("
            "SELECT MIN(day) AS day FROM piece_history "
            "WHERE part_id IS NOT NULL AND day IS NOT NULL "
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
            "SELECT day, SUM(pieces) AS cnt FROM piece_history "
            "WHERE dead = 0 AND distributed AND day IS NOT NULL AND day >= ? "
            "GROUP BY day",
            (cutoff_day,),
        ).fetchall()
        color_rows = conn.execute(
            "SELECT color_id, MAX(color_name) AS color_name, SUM(pieces) AS cnt "
            "FROM piece_history WHERE color_id IS NOT NULL "
            "GROUP BY color_id ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        part_rows = conn.execute(
            "SELECT part_id, MAX(part_name) AS part_name, SUM(pieces) AS cnt "
            "FROM piece_history WHERE part_id IS NOT NULL "
            "GROUP BY part_id ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        value_group_rows = conn.execute(
            "SELECT value_day AS day, part_id, color_id, SUM(pieces) AS cnt "
            "FROM piece_history "
            "WHERE dead = 0 AND part_id IS NOT NULL AND value_day >= ? "
            "GROUP BY value_day, part_id, color_id",
            (cutoff_day,),
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


def rateBuckets(since: float, bucket_s: float) -> list[dict[str, Any]]:
    """Pieces seen, classified and multi-dropped per ``bucket_s`` since ``since``
    (epoch seconds): the dashboard's rate graph. Buckets with no pieces are
    left out."""
    bucket_s = max(10.0, float(bucket_s))
    with _connection() as conn:
        rows = conn.execute(
            "SELECT CAST((seen_at - ?) / ? AS INTEGER) AS b, COUNT(*), "
            "SUM(classification_status = 'classified'), "
            "SUM(classification_status = 'multi_drop_fail') "
            "FROM piece_records WHERE dead = 0 AND seen_at >= ? GROUP BY b ORDER BY b",
            (since, bucket_s, since),
        ).fetchall()
    return [
        {"t": since + b * bucket_s, "seen": seen, "classified": classified or 0, "multi_drop": multi or 0}
        for b, seen, classified, multi in rows
    ]
