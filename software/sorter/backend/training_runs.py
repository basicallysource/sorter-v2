from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any, Optional

import color_rank
import db
import hive_metadata_cache
import local_state
import piece_records
import sync_seq

# Training data collection: the machine sorts as usual, and while a training
# run is on, every piece it sees is labelled with what the run is for.
#
# The one kind of run so far is a colour run: the operator says which colour
# (or which few colours) they are feeding, and each piece seen during the run
# takes that colour as its label. A run starts when the machine starts running
# with training mode on and its colours chosen, and ends when the machine stops
# running (a pause, a stop, an incident) or training mode is turned off; a run
# a crash left open is closed at the next start. A piece belongs to the run
# whose window holds its seen_at, so pieces left over from before a run started
# are not labelled, and pieces seen during a run but distributed after it keep
# its label.
#
# The label lives on the piece's record (training_* columns), so it goes to
# Hive with the record; the runs themselves sync by sync_seq.

MODE_COLOR = "color"
MODES = (MODE_COLOR,)

# How a piece's label was chosen: a run with one colour labels every piece with
# it; with several, the first of the piece's own colour predictions that is one
# of them, else the one nearest the machine's colour.
SOURCE_RUN = "run"
SOURCE_PREDICTION = "prediction"
SOURCE_NEAREST = "nearest"

RUNS_LISTED = 100

_lock = threading.Lock()


class TrainingError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def createRunTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS training_runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "uuid TEXT NOT NULL UNIQUE, "
        "mode TEXT NOT NULL, "
        "color_ids TEXT NOT NULL, "
        "started_at REAL NOT NULL, "
        "ended_at REAL, "
        "excluded INTEGER NOT NULL DEFAULT 0, "
        "updated_at REAL NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_runs_started_at ON training_runs(started_at)"
    )
    sync_seq.addColumn(conn, "training_runs")


def _createTables(conn: sqlite3.Connection) -> None:
    piece_records._createTables(conn)
    # Runs a crash left open end at their last piece; this runs once per
    # process, before this process can have started one.
    if conn.execute("SELECT 1 FROM training_runs WHERE ended_at IS NULL").fetchone() is not None:
        conn.execute(
            "UPDATE training_runs SET "
            "ended_at = MAX(started_at, COALESCE((SELECT MAX(p.seen_at) FROM piece_records p "
            "WHERE p.training_run_id = training_runs.uuid), started_at)), "
            "updated_at = ?, sync_seq = ? WHERE ended_at IS NULL",
            (time.time(), sync_seq.nextSeq(conn)),
        )
        conn.commit()


def _connection():
    return db.connect(_createTables)


# --- the setting -------------------------------------------------------------


def _normalizeConfig(raw: Any) -> dict[str, Any]:
    state = raw if isinstance(raw, dict) else {}
    mode = state.get("mode") if state.get("mode") in MODES else MODE_COLOR
    color_ids = [str(c) for c in state.get("color_ids") or [] if _isColorId(c)]
    return {"enabled": bool(state.get("enabled")), "mode": mode, "color_ids": _unique(color_ids)}


def _isColorId(value: Any) -> bool:
    return isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).isdigit()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    return [v for v in values if not (v in seen or seen.add(v))]


def getConfig() -> dict[str, Any]:
    return _normalizeConfig(local_state.get_training_mode_state())


def setConfig(
    *,
    enabled: Optional[bool] = None,
    mode: Optional[str] = None,
    color_ids: Optional[list[Any]] = None,
    running: bool,
) -> dict[str, Any]:
    with _lock:
        current = getConfig()
        updated = dict(current)
        if mode is not None:
            if mode not in MODES:
                raise TrainingError(400, f"Unknown training mode: {mode}")
            updated["mode"] = mode
        if color_ids is not None:
            if not all(_isColorId(c) for c in color_ids):
                raise TrainingError(400, "Colors are BrickLink color ids")
            updated["color_ids"] = _unique([str(c) for c in color_ids])
        if enabled is not None:
            updated["enabled"] = bool(enabled)
        changes_run = updated["color_ids"] != current["color_ids"] or updated["mode"] != current["mode"]
        if changes_run and openRun() is not None:
            raise TrainingError(409, "Pause the machine to change the colors")
        local_state.set_training_mode_state(updated)
        _reconcileLocked(running, time.time())
        return updated


# --- runs --------------------------------------------------------------------


def onLifecycle(running: bool) -> None:
    """Called by the sorter controller on every lifecycle change. It may be the
    control loop calling, so the write goes to the database writer thread."""
    at = time.time()
    db.defer("training_runs.lifecycle", lambda: reconcile(running, at))


def reconcile(running: bool, at: float) -> None:
    with _lock:
        _reconcileLocked(running, at)


def _reconcileLocked(running: bool, at: float) -> None:
    config = getConfig()
    wanted = running and config["enabled"] and bool(config["color_ids"])
    with _connection() as conn:
        open_row = conn.execute(
            "SELECT uuid FROM training_runs WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        if open_row is not None and not wanted:
            conn.execute(
                "UPDATE training_runs SET ended_at = MAX(started_at, ?), updated_at = ?, sync_seq = ? "
                "WHERE ended_at IS NULL",
                (at, time.time(), sync_seq.nextSeq(conn)),
            )
        elif open_row is None and wanted:
            conn.execute(
                "INSERT INTO training_runs (uuid, mode, color_ids, started_at, updated_at, sync_seq) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    config["mode"],
                    json.dumps(config["color_ids"]),
                    at,
                    time.time(),
                    sync_seq.nextSeq(conn),
                ),
            )
        conn.commit()


def openRun() -> Optional[dict[str, Any]]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM training_runs WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return _runsWithCounts(conn, [row])[0] if row is not None else None


def listRuns(limit: int = RUNS_LISTED) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM training_runs ORDER BY started_at DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return _runsWithCounts(conn, rows)


def getRun(run_id: str) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        row = conn.execute("SELECT * FROM training_runs WHERE uuid = ?", (run_id,)).fetchone()
        return _runsWithCounts(conn, [row])[0] if row is not None else None


def setRunExcluded(run_id: str, excluded: bool) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        cur = conn.execute(
            "UPDATE training_runs SET excluded = ?, updated_at = ?, sync_seq = ? WHERE uuid = ?",
            (1 if excluded else 0, time.time(), sync_seq.nextSeq(conn), run_id),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return None
        conn.commit()
    return getRun(run_id)


def _runsWithCounts(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    if not rows:
        return []
    ids = [str(r["uuid"]) for r in rows]
    counts = {
        str(c["training_run_id"]): c
        for c in conn.execute(
            "SELECT training_run_id, COUNT(*) AS pieces, "
            "SUM(training_color_id IS NOT NULL AND training_excluded = 0) AS labeled, "
            "SUM(training_excluded) AS excluded_pieces "
            f"FROM piece_records WHERE training_run_id IN ({', '.join('?' for _ in ids)}) "
            "GROUP BY training_run_id",
            ids,
        ).fetchall()
    }
    return [_runToDict(r, counts.get(str(r["uuid"]))) for r in rows]


def _runToDict(row: sqlite3.Row, counts: Optional[sqlite3.Row]) -> dict[str, Any]:
    return {
        "id": str(row["uuid"]),
        "mode": row["mode"],
        "color_ids": _colorIds(row["color_ids"]),
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "collecting": row["ended_at"] is None,
        "excluded": bool(row["excluded"]),
        "pieces": int(counts["pieces"] or 0) if counts else 0,
        "labeled": int(counts["labeled"] or 0) if counts else 0,
        "excluded_pieces": int(counts["excluded_pieces"] or 0) if counts else 0,
    }


def _colorIds(text: Any) -> list[str]:
    try:
        values = json.loads(text) if isinstance(text, str) else []
    except ValueError:
        return []
    return [str(v) for v in values if _isColorId(v)] if isinstance(values, list) else []


# --- labelling pieces --------------------------------------------------------


def labelFor(
    conn: sqlite3.Connection,
    piece_uuid: str,
    seen_at: Optional[float],
    machine_color_id: Optional[str],
) -> Optional[tuple[str, Optional[str], Optional[str]]]:
    """(run uuid, label colour id or None, how it was chosen) for a piece seen
    at `seen_at`, or None when no run covers it. In the caller's transaction:
    piece_records.recordPiece stamps the record with it."""
    if seen_at is None:
        return None
    run = conn.execute(
        "SELECT uuid, mode, color_ids FROM training_runs WHERE started_at <= ? "
        "AND (ended_at IS NULL OR ended_at >= ?) ORDER BY started_at DESC LIMIT 1",
        (float(seen_at), float(seen_at)),
    ).fetchone()
    if run is None or run["mode"] != MODE_COLOR:
        return None
    colors = _colorIds(run["color_ids"])
    if not colors:
        return str(run["uuid"]), None, None
    if len(colors) == 1:
        return str(run["uuid"]), colors[0], SOURCE_RUN
    for value_id in _predictedColors(conn, piece_uuid):
        if value_id in colors:
            return str(run["uuid"]), value_id, SOURCE_PREDICTION
    nearest = _nearest(colors, machine_color_id)
    if nearest is not None:
        return str(run["uuid"]), nearest, SOURCE_NEAREST
    return str(run["uuid"]), None, None


def _predictedColors(conn: sqlite3.Connection, piece_uuid: str) -> list[str]:
    try:
        rows = conn.execute(
            "SELECT value_id FROM piece_predictions WHERE piece_uuid = ? AND kind = 'color' "
            "ORDER BY applied DESC, created_at DESC, rank ASC",
            (piece_uuid,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [str(r["value_id"]) for r in rows]


def _nearest(colors: list[str], machine_color_id: Optional[str]) -> Optional[str]:
    if machine_color_id is None:
        return None
    palette = {str(c.get("id")): c for c in hive_metadata_cache.get_cached_palette() or []}
    machine = palette.get(str(machine_color_id))
    if machine is None:
        return None
    best: Optional[tuple[float, str]] = None
    for color_id in colors:
        candidate = palette.get(color_id)
        measured = color_rank.color_distance(machine, candidate) if candidate else None
        if measured is not None and (best is None or measured[0] < best[0]):
            best = (measured[0], color_id)
    return best[1] if best else None


# --- a run's pieces ----------------------------------------------------------

FILTERS = ("all", "disagree", "excluded")

_FILTER_SQL = {
    "all": "",
    "disagree": (
        " AND r.training_color_id IS NOT NULL AND r.training_excluded = 0 "
        "AND COALESCE(r.color_corrected_id, r.color_id) IS NOT r.training_color_id"
    ),
    "excluded": " AND r.training_excluded = 1",
}


def listRunPieces(
    run_id: str, *, limit: int = 200, offset: int = 0, filter_name: str = "all"
) -> tuple[list[dict[str, Any]], int]:
    where = "r.training_run_id = ?" + _FILTER_SQL.get(filter_name, "")
    with _connection() as conn:
        total = int(
            conn.execute(f"SELECT COUNT(*) FROM piece_records r WHERE {where}", (run_id,)).fetchone()[0]
        )
        rows = conn.execute(
            "SELECT r.uuid, r.training_run_id, r.seen_at, r.part_id, r.part_name, r.color_id, "
            "r.color_name, r.color_corrected_id, r.training_color_id, r.training_label_source, "
            "r.training_excluded, "
            "(SELECT i.id FROM piece_images i WHERE i.piece_uuid = r.uuid AND i.deleted_at IS NULL "
            "AND COALESCE(i.source, '') != 'link_match' "
            "ORDER BY i.used DESC, i.sharpness IS NULL, i.sharpness DESC, i.seq ASC LIMIT 1) AS image_id "
            f"FROM piece_records r WHERE {where} ORDER BY r.seen_at DESC, r.id DESC LIMIT ? OFFSET ?",
            (run_id, int(limit), int(offset)),
        ).fetchall()
    return [_pieceToDict(r) for r in rows], total


def _pieceToDict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "uuid": row["uuid"],
        "run_id": row["training_run_id"],
        "seen_at": row["seen_at"],
        "part_id": row["part_id"],
        "part_name": row["part_name"],
        "color_id": row["color_id"],
        "color_name": row["color_name"],
        "color_corrected_id": row["color_corrected_id"],
        "training_color_id": row["training_color_id"],
        "training_label_source": row["training_label_source"],
        "training_excluded": bool(row["training_excluded"]),
        "image_id": int(row["image_id"]) if row["image_id"] is not None else None,
    }


def getRunPiece(piece_uuid: str) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT r.uuid, r.training_run_id, r.seen_at, r.part_id, r.part_name, r.color_id, "
            "r.color_name, r.color_corrected_id, r.training_color_id, r.training_label_source, "
            "r.training_excluded, "
            "(SELECT i.id FROM piece_images i WHERE i.piece_uuid = r.uuid AND i.deleted_at IS NULL "
            "AND COALESCE(i.source, '') != 'link_match' "
            "ORDER BY i.used DESC, i.sharpness IS NULL, i.sharpness DESC, i.seq ASC LIMIT 1) AS image_id "
            "FROM piece_records r WHERE r.uuid = ? AND r.training_run_id IS NOT NULL",
            (piece_uuid,),
        ).fetchone()
    return _pieceToDict(row) if row is not None else None


def setPieceExcluded(piece_uuid: str, excluded: bool) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        cur = conn.execute(
            "UPDATE piece_records SET training_excluded = ?, training_updated_at = ?, sync_seq = ? "
            "WHERE uuid = ? AND training_run_id IS NOT NULL",
            (1 if excluded else 0, time.time(), sync_seq.nextSeq(conn), piece_uuid),
        )
        if cur.rowcount == 0:
            conn.rollback()
            return None
        conn.commit()
    return getRunPiece(piece_uuid)


# --- Hive sync ---------------------------------------------------------------


def listRunsAfter(seq_cursor: int, limit: int) -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM training_runs WHERE sync_seq > ? ORDER BY sync_seq ASC LIMIT ?",
            (int(seq_cursor), int(limit)),
        ).fetchall()
    return [
        {
            "run_uuid": str(r["uuid"]),
            "sync_seq": int(r["sync_seq"]),
            "mode": r["mode"],
            "color_ids": _colorIds(r["color_ids"]),
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "excluded": bool(r["excluded"]),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def countRunsAfter(seq_cursor: int) -> int:
    with _connection() as conn:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM training_runs WHERE sync_seq > ?", (int(seq_cursor),)
            ).fetchone()[0]
        )
