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
        conn.execute(
            "INSERT OR IGNORE INTO piece_records "
            "(uuid, run_id, machine_id, seen_at, recorded_at, classification_status, "
            "part_id, part_name, color_id, color_name, category_id, confidence, "
            "bin_x, bin_y, bin_z, dead) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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


def listPieces(*, offset: int = 0, limit: int = 50) -> tuple[int, list[dict[str, Any]]]:
    offset = max(0, offset)
    limit = max(1, min(limit, 200))
    with _connection() as conn:
        total_row = conn.execute("SELECT COUNT(*) AS c FROM piece_records").fetchone()
        total = int(total_row["c"]) if total_row else 0
        rows = conn.execute(
            "SELECT uuid, run_id, seen_at, classification_status, part_id, part_name, "
            "color_id, color_name, category_id, confidence, bin_x, bin_y, bin_z, dead "
            "FROM piece_records ORDER BY seen_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    pieces: list[dict[str, Any]] = []
    for r in rows:
        dest = (
            [r["bin_x"], r["bin_y"], r["bin_z"]]
            if r["bin_x"] is not None
            else None
        )
        pieces.append(
            {
                "uuid": r["uuid"],
                "run_id": r["run_id"] or "",
                "seen_at": r["seen_at"],
                "classification_status": r["classification_status"],
                "part_id": r["part_id"],
                "part_name": r["part_name"],
                "color_id": r["color_id"],
                "color_name": r["color_name"],
                "category_id": r["category_id"],
                "confidence": r["confidence"],
                "destination_bin": dest,
                "dead": bool(r["dead"]),
            }
        )
    return total, pieces
