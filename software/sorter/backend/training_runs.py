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
# The one kind of run so far is a colour run. The operator starts a run and
# ends it; pausing the machine does neither, and a run stays open across
# restarts. A run is a sequence of segments, one per colour (or set of
# colours) fed: choosing other colours while a run is open ends its segment and
# opens the next at once. A piece takes the colours of the segment whose window
# holds its seen_at, so pieces left over from before a change keep the colour
# they were fed with.
#
# The label lives on the piece's record (training_* columns), so it goes to
# Hive with the record; runs, with their segments, sync by sync_seq.

MODE_COLOR = "color"
MODES = (MODE_COLOR,)

# How a piece's label was chosen: a segment with one colour labels every piece
# with it; with several, the first of the piece's own colour predictions that
# is one of them, else the one nearest the machine's colour.
SOURCE_RUN = "run"
SOURCE_PREDICTION = "prediction"
SOURCE_NEAREST = "nearest"

RUNS_LISTED = 100

_lock = threading.Lock()
# The setting as last read or saved, for the distribution loop, which must not
# wait on the database: None until something reads it.
_config: Optional[dict[str, Any]] = None
# The open segment (uuid, started_at), for the sample collector, which
# captures a calibration frame as each one starts: None while no run is open.
_open_segment: Optional[tuple[str, float]] = None
_UNSET: Any = object()


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
        # Every colour its segments used, in order.
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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS training_segments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "uuid TEXT NOT NULL UNIQUE, "
        "run_uuid TEXT NOT NULL, "
        "color_ids TEXT NOT NULL, "
        "started_at REAL NOT NULL, "
        "ended_at REAL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_segments_run ON training_segments(run_uuid, started_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_training_segments_started_at ON training_segments(started_at)"
    )
    # Runs from before segments: each is one segment.
    for run in conn.execute(
        "SELECT uuid, color_ids, started_at, ended_at FROM training_runs r "
        "WHERE NOT EXISTS (SELECT 1 FROM training_segments s WHERE s.run_uuid = r.uuid)"
    ).fetchall():
        conn.execute(
            "INSERT INTO training_segments (uuid, run_uuid, color_ids, started_at, ended_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), run["uuid"], run["color_ids"], run["started_at"], run["ended_at"]),
        )


def _createTables(conn: sqlite3.Connection) -> None:
    piece_records._createTables(conn)
    # Pieces labelled before segments existed take their run's one segment.
    conn.execute(
        "UPDATE piece_records SET training_segment_id = (SELECT s.uuid FROM training_segments s "
        "WHERE s.run_uuid = piece_records.training_run_id ORDER BY s.started_at LIMIT 1) "
        "WHERE training_run_id IS NOT NULL AND training_segment_id IS NULL"
    )
    conn.commit()


def _connection():
    return db.connect(_createTables)


# --- the setting -------------------------------------------------------------


def _normalizeConfig(raw: Any) -> dict[str, Any]:
    state = raw if isinstance(raw, dict) else {}
    mode = state.get("mode") if state.get("mode") in MODES else MODE_COLOR
    color_ids = [str(c) for c in state.get("color_ids") or [] if _isColorId(c)]
    return {
        "enabled": bool(state.get("enabled")),
        "mode": mode,
        "color_ids": _unique(color_ids),
        "bin": _normalizeBin(state.get("bin")),
    }


def _normalizeBin(raw: Any) -> Optional[dict[str, int]]:
    # The one bin every piece goes to while training mode is on, the chute
    # staying put; None routes pieces by the sorting profile as usual.
    if not isinstance(raw, dict):
        return None
    try:
        out = {key: int(raw[key]) for key in ("layer", "section", "bin")}
    except (KeyError, TypeError, ValueError):
        return None
    return out if min(out.values()) >= 0 else None


def _isColorId(value: Any) -> bool:
    return isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).isdigit()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    return [v for v in values if not (v in seen or seen.add(v))]


def getConfig() -> dict[str, Any]:
    global _config
    _config = _normalizeConfig(local_state.get_training_mode_state())
    _noteOpenSegment()
    return dict(_config)


def _noteOpenSegment() -> None:
    global _open_segment
    with _connection() as conn:
        row = conn.execute(
            "SELECT uuid, started_at FROM training_segments WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    _open_segment = (str(row["uuid"]), float(row["started_at"])) if row is not None else None


def openSegment() -> Optional[tuple[str, float]]:
    """(uuid, started_at) of the segment collecting now, or None. Reads no
    database."""
    return _open_segment


def loadSoon() -> None:
    """Read the setting on the database writer thread, so the distribution loop
    knows the bin from the start. Called by the sorter controller at start."""
    db.defer("training_runs.load", getConfig)


def fixedBin() -> Optional[tuple[int, int, int]]:
    """(layer, section, bin) every piece goes to now, or None. Reads no
    database: the setting as last read or saved."""
    config = _config
    if not config or not config["enabled"] or config["bin"] is None:
        return None
    return config["bin"]["layer"], config["bin"]["section"], config["bin"]["bin"]


def setConfig(
    *,
    enabled: Optional[bool] = None,
    mode: Optional[str] = None,
    color_ids: Optional[list[Any]] = None,
    bin: Any = _UNSET,
) -> dict[str, Any]:
    global _config
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
        if bin is not _UNSET:
            updated["bin"] = _normalizeBin(bin)
            if bin is not None and updated["bin"] is None:
                raise TrainingError(400, "A bin is its layer, section and bin numbers")
        now = time.time()
        with _connection() as conn:
            open_run = _openRunRow(conn)
            if open_run is not None:
                if updated["mode"] != current["mode"]:
                    raise TrainingError(409, "End the run to change the mode")
                if not updated["color_ids"] and updated["enabled"]:
                    raise TrainingError(400, "A run needs a color: end the run instead")
                if not updated["enabled"]:
                    _endRun(conn, str(open_run["uuid"]), now)
                elif updated["color_ids"] != current["color_ids"]:
                    _startSegment(conn, str(open_run["uuid"]), updated["color_ids"], now)
            local_state.write_training_mode_state(conn, updated)
            conn.commit()
        _config = dict(updated)
        _noteOpenSegment()
        return updated


# --- runs and segments -------------------------------------------------------


def startRun() -> dict[str, Any]:
    with _lock:
        config = getConfig()
        if not config["enabled"]:
            raise TrainingError(400, "Turn training mode on first")
        if not config["color_ids"]:
            raise TrainingError(400, "Pick the color you're feeding first")
        now = time.time()
        with _connection() as conn:
            if _openRunRow(conn) is not None:
                raise TrainingError(409, "A run is already collecting")
            run_uuid = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO training_runs (uuid, mode, color_ids, started_at, updated_at, sync_seq) "
                "VALUES (?, ?, '[]', ?, ?, ?)",
                (run_uuid, config["mode"], now, now, sync_seq.nextSeq(conn)),
            )
            _startSegment(conn, run_uuid, config["color_ids"], now)
            conn.commit()
        _noteOpenSegment()
    return getRun(run_uuid)


def endRun(run_id: str) -> Optional[dict[str, Any]]:
    with _lock:
        with _connection() as conn:
            row = conn.execute("SELECT uuid FROM training_runs WHERE uuid = ?", (run_id,)).fetchone()
            if row is None:
                return None
            _endRun(conn, run_id, time.time())
            conn.commit()
        _noteOpenSegment()
    return getRun(run_id)


def _openRunRow(conn: sqlite3.Connection) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM training_runs WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
    ).fetchone()


def _startSegment(conn: sqlite3.Connection, run_uuid: str, color_ids: list[str], at: float) -> None:
    conn.execute(
        "UPDATE training_segments SET ended_at = MAX(started_at, ?) WHERE run_uuid = ? AND ended_at IS NULL",
        (at, run_uuid),
    )
    conn.execute(
        "INSERT INTO training_segments (uuid, run_uuid, color_ids, started_at) VALUES (?, ?, ?, ?)",
        (str(uuid.uuid4()), run_uuid, json.dumps(color_ids), at),
    )
    used = _colorIds(
        conn.execute("SELECT color_ids FROM training_runs WHERE uuid = ?", (run_uuid,)).fetchone()["color_ids"]
    )
    conn.execute(
        "UPDATE training_runs SET color_ids = ?, updated_at = ?, sync_seq = ? WHERE uuid = ?",
        (json.dumps(_unique(used + color_ids)), time.time(), sync_seq.nextSeq(conn), run_uuid),
    )


def _endRun(conn: sqlite3.Connection, run_uuid: str, at: float) -> None:
    conn.execute(
        "UPDATE training_segments SET ended_at = MAX(started_at, ?) WHERE run_uuid = ? AND ended_at IS NULL",
        (at, run_uuid),
    )
    conn.execute(
        "UPDATE training_runs SET ended_at = MAX(started_at, ?), updated_at = ?, sync_seq = ? "
        "WHERE uuid = ? AND ended_at IS NULL",
        (at, time.time(), sync_seq.nextSeq(conn), run_uuid),
    )


def openRun() -> Optional[dict[str, Any]]:
    with _connection() as conn:
        row = _openRunRow(conn)
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


def _placeholders(values: list[Any]) -> str:
    return ", ".join("?" for _ in values)


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
            f"FROM piece_records WHERE training_run_id IN ({_placeholders(ids)}) "
            "GROUP BY training_run_id",
            ids,
        ).fetchall()
    }
    segment_pieces = {
        str(c["training_segment_id"]): int(c["pieces"])
        for c in conn.execute(
            "SELECT training_segment_id, COUNT(*) AS pieces FROM piece_records "
            f"WHERE training_run_id IN ({_placeholders(ids)}) GROUP BY training_segment_id",
            ids,
        ).fetchall()
    }
    segments: dict[str, list[dict[str, Any]]] = {}
    for s in conn.execute(
        f"SELECT * FROM training_segments WHERE run_uuid IN ({_placeholders(ids)}) ORDER BY started_at, id",
        ids,
    ).fetchall():
        segments.setdefault(str(s["run_uuid"]), []).append(
            {
                "id": str(s["uuid"]),
                "color_ids": _colorIds(s["color_ids"]),
                "started_at": s["started_at"],
                "ended_at": s["ended_at"],
                "pieces": segment_pieces.get(str(s["uuid"]), 0),
            }
        )
    return [_runToDict(r, counts.get(str(r["uuid"])), segments.get(str(r["uuid"]), [])) for r in rows]


def _runToDict(row: sqlite3.Row, counts: Optional[sqlite3.Row], segments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": str(row["uuid"]),
        "mode": row["mode"],
        "color_ids": _colorIds(row["color_ids"]),
        "segments": segments,
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
) -> Optional[tuple[str, str, Optional[str], Optional[str]]]:
    """(run uuid, segment uuid, label colour id or None, how it was chosen) for
    a piece seen at `seen_at`, or None when no segment covers it. In the
    caller's transaction: piece_records.recordPiece stamps the record with it."""
    if seen_at is None:
        return None
    segment = conn.execute(
        "SELECT s.uuid, s.run_uuid, s.color_ids, r.mode FROM training_segments s "
        "JOIN training_runs r ON r.uuid = s.run_uuid WHERE s.started_at <= ? "
        "AND (s.ended_at IS NULL OR ? < s.ended_at) ORDER BY s.started_at DESC LIMIT 1",
        (float(seen_at), float(seen_at)),
    ).fetchone()
    if segment is None or segment["mode"] != MODE_COLOR:
        return None
    run_uuid, segment_uuid = str(segment["run_uuid"]), str(segment["uuid"])
    colors = _colorIds(segment["color_ids"])
    if not colors:
        return run_uuid, segment_uuid, None, None
    if len(colors) == 1:
        return run_uuid, segment_uuid, colors[0], SOURCE_RUN
    for value_id in _predictedColors(conn, piece_uuid):
        if value_id in colors:
            return run_uuid, segment_uuid, value_id, SOURCE_PREDICTION
    nearest = _nearest(colors, machine_color_id)
    if nearest is not None:
        return run_uuid, segment_uuid, nearest, SOURCE_NEAREST
    return run_uuid, segment_uuid, None, None


def _predictedColors(conn: sqlite3.Connection, piece_uuid: str) -> list[str]:
    try:
        # The machine's own (live) predictions: a later run over the piece's
        # images never changes what a training run labelled it.
        rows = conn.execute(
            "SELECT a.value_id FROM piece_predictions a "
            "JOIN piece_prediction_requests q ON q.id = a.request_id "
            "WHERE a.piece_uuid = ? AND a.kind = 'color' AND q.source = 'live' "
            "ORDER BY a.applied DESC, a.created_at DESC, a.rank ASC",
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
            "SELECT r.uuid, r.training_run_id, r.training_segment_id, r.seen_at, r.part_id, r.part_name, r.color_id, "
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
        "segment_id": row["training_segment_id"],
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
            "SELECT r.uuid, r.training_run_id, r.training_segment_id, r.seen_at, r.part_id, r.part_name, r.color_id, "
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
        ids = [str(r["uuid"]) for r in rows]
        segments: dict[str, list[dict[str, Any]]] = {}
        if ids:
            for seg in conn.execute(
                f"SELECT * FROM training_segments WHERE run_uuid IN ({_placeholders(ids)}) ORDER BY started_at, id",
                ids,
            ).fetchall():
                segments.setdefault(str(seg["run_uuid"]), []).append(
                    {
                        "segment_uuid": str(seg["uuid"]),
                        "color_ids": _colorIds(seg["color_ids"]),
                        "started_at": seg["started_at"],
                        "ended_at": seg["ended_at"],
                    }
                )
    return [
        {
            "run_uuid": str(r["uuid"]),
            "sync_seq": int(r["sync_seq"]),
            "mode": r["mode"],
            "color_ids": _colorIds(r["color_ids"]),
            "segments": segments.get(str(r["uuid"]), []),
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
