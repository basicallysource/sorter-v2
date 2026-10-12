from __future__ import annotations

import sqlite3
import time
import uuid
from typing import Any, Optional

import db
import piece_records

# Sorting runs and lots: what the operator says a stretch of sorting was.
#
# A lot is a collection of pieces that came in together (a Goodwill box, a
# customer's bulk order). A sorting run is one stretch of putting pieces
# through: it starts when the operator starts it and lasts across pauses,
# restarts and shutdowns until the next run starts. A piece belongs to the run
# whose stretch holds its seen_at, so a run can also be started after the fact
# for sorting already done.
#
# A run can name a lot and either add its pieces to it or not: putting a lot's
# pieces through again (a finer sort of some of its bins) names the lot without
# adding to it, so the lot still counts each piece once.
#
# These are not piece_records.run_id (one backend process) nor bin_contents'
# sorting_sessions (what the bins hold since a profile was applied).
#
# A run's pieces are counted from piece_records. When retention removes old
# records, foldPieces first adds them to their run's folded counts (by the runs'
# stretches at that moment), and no run may start before the newest piece
# folded, so a folded piece never changes runs.


def _createTables(conn: sqlite3.Connection) -> None:
    # A run's pieces are counted from piece_records.
    piece_records._createTables(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS lots ("
        "id TEXT PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "description TEXT, "
        "created_at REAL NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sorting_runs ("
        "id TEXT PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "note TEXT, "
        "lot_id TEXT REFERENCES lots(id), "
        "adds_to_lot INTEGER NOT NULL DEFAULT 1, "
        "started_at REAL NOT NULL, "
        "created_at REAL NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sorting_runs_started_at "
        "ON sorting_runs(started_at)"
    )
    # Pieces retention removed, counted per run as _RUNS_SQL and lotParts
    # count live ones.
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sorting_run_folds ("
        "run_id TEXT PRIMARY KEY REFERENCES sorting_runs(id), "
        "pieces INTEGER NOT NULL DEFAULT 0, "
        "distributed_pieces INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sorting_run_part_folds ("
        "run_id TEXT NOT NULL REFERENCES sorting_runs(id), "
        "part_id TEXT NOT NULL, "
        # The corrected colour if any, else the predicted one; '' for none.
        "color TEXT NOT NULL, "
        "part_name TEXT, "
        "color_name TEXT, "
        "n INTEGER NOT NULL, "
        "PRIMARY KEY (run_id, part_id, color)"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sorting_run_fold_state ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "folded_until REAL NOT NULL"
        ")"
    )


def _connection():
    return db.connect(_createTables)


class RunError(ValueError):
    pass


def _lotRow(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "created_at": row["created_at"],
    }


def _check_lot(conn: sqlite3.Connection, lot_id: Optional[str]) -> None:
    if lot_id is None:
        return
    if conn.execute("SELECT 1 FROM lots WHERE id = ?", (lot_id,)).fetchone() is None:
        raise RunError(f"No lot {lot_id}.")


def _clean_name(name: Any, what: str) -> str:
    text = str(name or "").strip()
    if not text:
        raise RunError(f"A {what} needs a name.")
    return text


def createLot(name: str, description: Optional[str] = None) -> dict[str, Any]:
    lot_id = str(uuid.uuid4())
    with _connection() as conn:
        conn.execute(
            "INSERT INTO lots (id, name, description, created_at) VALUES (?, ?, ?, ?)",
            (lot_id, _clean_name(name, "lot"), (description or "").strip() or None, time.time()),
        )
        conn.commit()
    return getLot(lot_id)


def updateLot(lot_id: str, *, name: Optional[str] = None, description: Optional[str] = None) -> dict[str, Any]:
    with _connection() as conn:
        _check_lot(conn, lot_id)
        if name is not None:
            conn.execute("UPDATE lots SET name = ? WHERE id = ?", (_clean_name(name, "lot"), lot_id))
        if description is not None:
            conn.execute(
                "UPDATE lots SET description = ? WHERE id = ?", (description.strip() or None, lot_id)
            )
        conn.commit()
    return getLot(lot_id)


def startRun(
    name: str,
    *,
    lot_id: Optional[str] = None,
    adds_to_lot: bool = True,
    note: Optional[str] = None,
    started_at: Optional[float] = None,
) -> dict[str, Any]:
    """Start a run now, ending the current one. `started_at` in the past records
    a run for sorting already done: it takes the pieces from then until the next
    run's start."""
    run_id = str(uuid.uuid4())
    now = time.time()
    start = now if started_at is None else float(started_at)
    if start > now + 60:
        raise RunError("A run can't start in the future.")
    with _connection() as conn:
        folded = conn.execute("SELECT folded_until FROM sorting_run_fold_state WHERE id = 1").fetchone()
        if folded is not None and start <= float(folded["folded_until"]):
            raise RunError(
                "A run can't start that far back: the piece history before "
                f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(float(folded['folded_until'])))} "
                "is kept only as totals."
            )
        _check_lot(conn, lot_id)
        if conn.execute("SELECT 1 FROM sorting_runs WHERE started_at = ?", (start,)).fetchone():
            raise RunError("Another run starts at that exact time.")
        conn.execute(
            "INSERT INTO sorting_runs (id, name, note, lot_id, adds_to_lot, started_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                _clean_name(name, "run"),
                (note or "").strip() or None,
                lot_id,
                1 if adds_to_lot else 0,
                start,
                now,
            ),
        )
        conn.commit()
    return getRun(run_id)


_UNSET: Any = object()


def updateRun(
    run_id: str,
    *,
    name: Optional[str] = None,
    note: Optional[str] = None,
    lot_id: Any = _UNSET,
    adds_to_lot: Optional[bool] = None,
) -> dict[str, Any]:
    with _connection() as conn:
        if conn.execute("SELECT 1 FROM sorting_runs WHERE id = ?", (run_id,)).fetchone() is None:
            raise RunError(f"No run {run_id}.")
        if name is not None:
            conn.execute("UPDATE sorting_runs SET name = ? WHERE id = ?", (_clean_name(name, "run"), run_id))
        if note is not None:
            conn.execute("UPDATE sorting_runs SET note = ? WHERE id = ?", (note.strip() or None, run_id))
        if lot_id is not _UNSET:
            _check_lot(conn, lot_id)
            conn.execute("UPDATE sorting_runs SET lot_id = ? WHERE id = ?", (lot_id, run_id))
        if adds_to_lot is not None:
            conn.execute(
                "UPDATE sorting_runs SET adds_to_lot = ? WHERE id = ?", (1 if adds_to_lot else 0, run_id)
            )
        conn.commit()
    return getRun(run_id)


# Each run's stretch: from its start to the next run's start (None for the
# current run).
_SPANS_SQL = (
    "SELECT r.*, LEAD(r.started_at) OVER (ORDER BY r.started_at) AS ended_at "
    "FROM sorting_runs r"
)

# Each run with its stretch and the pieces seen in it (not those reaped as
# stuck), folded ones included.
_RUNS_SQL = (
    f"WITH spans AS ({_SPANS_SQL}) "
    "SELECT spans.*, lots.name AS lot_name, "
    "  (SELECT COUNT(*) FROM piece_records p WHERE p.seen_at >= spans.started_at "
    "     AND (spans.ended_at IS NULL OR p.seen_at < spans.ended_at) AND p.dead = 0) "
    "  + COALESCE(f.pieces, 0) AS pieces, "
    "  (SELECT COUNT(*) FROM piece_records p WHERE p.seen_at >= spans.started_at "
    "     AND (spans.ended_at IS NULL OR p.seen_at < spans.ended_at) "
    "     AND p.bin_x IS NOT NULL) "
    "  + COALESCE(f.distributed_pieces, 0) AS distributed_pieces "
    "FROM spans LEFT JOIN lots ON lots.id = spans.lot_id "
    "LEFT JOIN sorting_run_folds f ON f.run_id = spans.id"
)


def _runRow(row: sqlite3.Row, current_id: Optional[str]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "note": row["note"],
        "lot_id": row["lot_id"],
        "lot_name": row["lot_name"],
        "adds_to_lot": bool(row["adds_to_lot"]),
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "is_current": row["id"] == current_id,
        "pieces": int(row["pieces"] or 0),
        "distributed_pieces": int(row["distributed_pieces"] or 0),
    }


def _runs(conn: sqlite3.Connection, where: str = "", params: tuple = ()) -> list[dict[str, Any]]:
    current = conn.execute(
        "SELECT id FROM sorting_runs WHERE started_at <= ? ORDER BY started_at DESC LIMIT 1",
        (time.time(),),
    ).fetchone()
    current_id = current["id"] if current else None
    rows = conn.execute(
        f"SELECT * FROM ({_RUNS_SQL}) {where} ORDER BY started_at DESC", params
    ).fetchall()
    return [_runRow(row, current_id) for row in rows]


def listRuns() -> list[dict[str, Any]]:
    with _connection() as conn:
        return _runs(conn)


def getRun(run_id: str) -> dict[str, Any]:
    with _connection() as conn:
        runs = _runs(conn, "WHERE id = ?", (run_id,))
    if not runs:
        raise RunError(f"No run {run_id}.")
    return runs[0]


def currentRun() -> Optional[dict[str, Any]]:
    for run in listRuns():
        if run["is_current"]:
            return run
    return None


def _lotTotals(conn: sqlite3.Connection) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    for run in _runs(conn):
        if run["lot_id"] is None:
            continue
        t = totals.setdefault(run["lot_id"], {"pieces": 0, "runs": 0, "passes": 0})
        if run["adds_to_lot"]:
            t["pieces"] += run["pieces"]
            t["runs"] += 1
        else:
            t["passes"] += 1
    return totals


def listLots() -> list[dict[str, Any]]:
    with _connection() as conn:
        totals = _lotTotals(conn)
        rows = conn.execute("SELECT * FROM lots ORDER BY created_at DESC").fetchall()
    return [
        {**_lotRow(row), **totals.get(row["id"], {"pieces": 0, "runs": 0, "passes": 0})}
        for row in rows
    ]


def getLot(lot_id: str) -> dict[str, Any]:
    for lot in listLots():
        if lot["id"] == lot_id:
            return lot
    raise RunError(f"No lot {lot_id}.")


def lotParts(lot_id: str) -> dict[str, Any]:
    """The lot's parts in each color, counted in each of its runs, so a part the
    lot counted once and a later pass saw again shows in both."""
    with _connection() as conn:
        _check_lot(conn, lot_id)
        runs = sorted(
            (r for r in _runs(conn) if r["lot_id"] == lot_id), key=lambda r: r["started_at"]
        )
        parts: dict[tuple[str, str], dict[str, Any]] = {}
        for run in runs:
            rows = conn.execute(
                "SELECT part_id, COALESCE(color_corrected_id, color_id) AS color, "
                "MAX(part_name) AS part_name, MAX(color_name) AS color_name, COUNT(*) AS n "
                "FROM piece_records WHERE seen_at >= ? AND (? IS NULL OR seen_at < ?) "
                "AND classification_status = 'classified' AND dead = 0 "
                "AND COALESCE(part_correct, 1) != 0 AND part_id IS NOT NULL "
                "GROUP BY part_id, color",
                (run["started_at"], run["ended_at"], run["ended_at"]),
            ).fetchall()
            folded = conn.execute(
                "SELECT part_id, color, part_name, color_name, n FROM sorting_run_part_folds "
                "WHERE run_id = ?",
                (run["id"],),
            ).fetchall()
            for row in [*rows, *folded]:
                key = (row["part_id"], str(row["color"]) if row["color"] is not None else "")
                part = parts.setdefault(
                    key,
                    {
                        "part_id": row["part_id"],
                        "part_name": row["part_name"],
                        "color_id": key[1] or None,
                        "color_name": row["color_name"],
                        "counts": {},
                        "in_lot": 0,
                    },
                )
                part["counts"][run["id"]] = part["counts"].get(run["id"], 0) + int(row["n"])
                if run["adds_to_lot"]:
                    part["in_lot"] += int(row["n"])
    ordered = sorted(parts.values(), key=lambda p: (-p["in_lot"], -sum(p["counts"].values())))
    return {
        "runs": [
            {"id": r["id"], "name": r["name"], "adds_to_lot": r["adds_to_lot"], "started_at": r["started_at"]}
            for r in runs
        ],
        "parts": ordered,
    }


def foldPieces(conn: sqlite3.Connection, record_ids: list[int]) -> None:
    """Count the piece_records rows about to be removed into their runs'
    folded counts, in the caller's transaction (see the note at the top)."""
    if not record_ids:
        return
    placeholders = ", ".join("?" for _ in record_ids)
    pieces = (
        f"WITH spans AS ({_SPANS_SQL}), "
        "folded AS ("
        "  SELECT spans.id AS run_id, p.* FROM piece_records p JOIN spans "
        "  ON p.seen_at >= spans.started_at AND (spans.ended_at IS NULL OR p.seen_at < spans.ended_at) "
        f"  WHERE p.id IN ({placeholders})"
        ") "
    )
    conn.execute(
        "INSERT INTO sorting_run_folds (run_id, pieces, distributed_pieces) "
        f"{pieces}SELECT run_id, SUM(dead = 0), SUM(bin_x IS NOT NULL) FROM folded "
        "WHERE true GROUP BY run_id "
        "ON CONFLICT(run_id) DO UPDATE SET "
        "pieces = pieces + excluded.pieces, "
        "distributed_pieces = distributed_pieces + excluded.distributed_pieces",
        record_ids,
    )
    # The same filter lotParts applies to live records.
    conn.execute(
        "INSERT INTO sorting_run_part_folds (run_id, part_id, color, part_name, color_name, n) "
        f"{pieces}SELECT run_id, part_id, COALESCE(color_corrected_id, color_id, '') AS color, "
        "MAX(part_name), MAX(color_name), COUNT(*) FROM folded "
        "WHERE classification_status = 'classified' AND dead = 0 "
        "AND COALESCE(part_correct, 1) != 0 AND part_id IS NOT NULL "
        "GROUP BY run_id, part_id, color "
        "ON CONFLICT(run_id, part_id, color) DO UPDATE SET n = n + excluded.n, "
        "part_name = COALESCE(excluded.part_name, part_name), "
        "color_name = COALESCE(excluded.color_name, color_name)",
        record_ids,
    )
    newest = conn.execute(
        f"SELECT MAX(seen_at) FROM piece_records WHERE id IN ({placeholders})", record_ids
    ).fetchone()[0]
    if newest is not None:
        conn.execute(
            "INSERT INTO sorting_run_fold_state (id, folded_until) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET folded_until = MAX(folded_until, excluded.folded_until)",
            (float(newest),),
        )
