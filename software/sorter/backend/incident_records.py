from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from local_state import local_state_db_path

# Durable log of operator-facing incidents (classification-channel stalls,
# chute jams, feeder dropzone stuck pieces, distribution faults, stepper
# stalls, ...). RuntimeStatsCollector.setActiveIncident/clearActiveIncident is
# the single in-memory choke point every incident publisher and clearer goes
# through (see runtime_stats.py) — it is the sole caller of openIncident /
# updateIncident / resolveIncident below, so every incident kind is captured
# here regardless of which subsystem raised it. Common fields (kind, channel,
# severity, timing, resolution) are real columns for querying; the full raw
# incident payload is also kept as JSON so kind-specific fields (stalled_ms,
# bbox, steppers, ...) are never lost even before they earn their own column.

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
                "CREATE TABLE IF NOT EXISTS incidents ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "run_id TEXT, "
                "machine_id TEXT, "
                "kind TEXT NOT NULL, "
                "source TEXT, "
                "source_kind TEXT, "
                "severity TEXT, "
                "scope TEXT, "
                "channel TEXT, "
                "role TEXT, "
                "channel_label TEXT, "
                "piece_uuid TEXT, "
                "track_id INTEGER, "
                "reason TEXT, "
                "rule TEXT, "
                "resolution_hint TEXT, "
                "operator_message TEXT, "
                "status TEXT NOT NULL, "
                "triggered_at REAL NOT NULL, "
                "updated_at REAL, "
                "resolved_at REAL, "
                "resolved_by TEXT, "
                "duration_s REAL, "
                "details_json TEXT"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_incidents_triggered ON incidents(triggered_at)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_kind ON incidents(kind)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status)")
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def _machineId() -> Optional[str]:
    try:
        from local_state import get_machine_id

        return get_machine_id()
    except Exception:
        return None


def _trackId(payload: dict[str, Any]) -> Optional[int]:
    value = payload.get("track_id", payload.get("global_id"))
    return int(value) if isinstance(value, int) else None


def openIncident(payload: dict[str, Any], *, run_id: Optional[str] = None) -> int:
    now = time.time()
    triggered_at = payload.get("triggered_at")
    triggered_at = float(triggered_at) if isinstance(triggered_at, (int, float)) else now
    with _connection() as conn:
        cur = conn.execute(
            "INSERT INTO incidents "
            "(run_id, machine_id, kind, source, source_kind, severity, scope, channel, role, "
            "channel_label, piece_uuid, track_id, reason, rule, resolution_hint, operator_message, "
            "status, triggered_at, updated_at, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)",
            (
                run_id,
                _machineId(),
                str(payload.get("kind") or "unknown"),
                payload.get("source"),
                payload.get("source_kind"),
                payload.get("severity"),
                payload.get("scope"),
                payload.get("channel"),
                payload.get("role"),
                payload.get("channel_label"),
                payload.get("piece_uuid"),
                _trackId(payload),
                payload.get("reason"),
                payload.get("rule"),
                payload.get("resolution"),
                payload.get("operator_message"),
                triggered_at,
                now,
                json.dumps(payload, default=str),
            ),
        )
        conn.commit()
        return int(cur.lastrowid or 0)


def updateIncident(row_id: int, payload: dict[str, Any]) -> None:
    with _connection() as conn:
        conn.execute(
            "UPDATE incidents SET severity = ?, channel_label = ?, reason = ?, "
            "operator_message = ?, updated_at = ?, details_json = ? "
            "WHERE id = ? AND status = 'active'",
            (
                payload.get("severity"),
                payload.get("channel_label"),
                payload.get("reason"),
                payload.get("operator_message"),
                time.time(),
                json.dumps(payload, default=str),
                int(row_id),
            ),
        )
        conn.commit()


def resolveIncident(
    row_id: int,
    *,
    resolved_by: str = "system",
    resolved_at: Optional[float] = None,
) -> None:
    resolved_at = float(resolved_at) if isinstance(resolved_at, (int, float)) else time.time()
    with _connection() as conn:
        row = conn.execute(
            "SELECT triggered_at FROM incidents WHERE id = ? AND status = 'active'",
            (int(row_id),),
        ).fetchone()
        if row is None:
            return
        duration_s = max(0.0, resolved_at - float(row["triggered_at"] or resolved_at))
        conn.execute(
            "UPDATE incidents SET status = 'resolved', resolved_at = ?, resolved_by = ?, "
            "duration_s = ?, updated_at = ? WHERE id = ?",
            (resolved_at, resolved_by, duration_s, resolved_at, int(row_id)),
        )
        conn.commit()


_LIST_COLUMNS = (
    "id, kind, source, source_kind, severity, scope, channel, role, channel_label, "
    "piece_uuid, track_id, reason, operator_message, status, triggered_at, resolved_at, "
    "resolved_by, duration_s"
)


def _buildFilters(
    *,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    if date_from is not None:
        clauses.append("triggered_at >= ?")
        params.append(float(date_from))
    if date_to is not None:
        clauses.append("triggered_at <= ?")
        params.append(float(date_to))
    return clauses, params


def listIncidents(
    *,
    limit: int = 100,
    cursor: Optional[int] = None,
    kind: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[float] = None,
    date_to: Optional[float] = None,
) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    clauses, params = _buildFilters(
        kind=kind, status=status, date_from=date_from, date_to=date_to
    )
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    page_clauses = list(clauses)
    page_params = list(params)
    if cursor is not None:
        page_clauses.append("id < ?")
        page_params.append(int(cursor))
    page_where = (" WHERE " + " AND ".join(page_clauses)) if page_clauses else ""
    with _connection() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS c FROM incidents{where}", params
        ).fetchone()
        total = int(total_row["c"] or 0)
        rows = conn.execute(
            f"SELECT {_LIST_COLUMNS} FROM incidents{page_where} "
            "ORDER BY id DESC LIMIT ?",
            page_params + [limit + 1],
        ).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [dict(r) for r in rows]
    next_cursor = str(rows[-1]["id"]) if has_more and rows else None
    return {"items": items, "next_cursor": next_cursor, "total": total}


def incidentSummary(
    *, date_from: Optional[float] = None, date_to: Optional[float] = None
) -> dict[str, Any]:
    clauses, params = _buildFilters(date_from=date_from, date_to=date_to)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _connection() as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS c FROM incidents{where}", params
        ).fetchone()
        active_clauses = clauses + ["status = 'active'"]
        active_where = " WHERE " + " AND ".join(active_clauses)
        active_row = conn.execute(
            f"SELECT COUNT(*) AS c FROM incidents{active_where}", params
        ).fetchone()
        by_kind_rows = conn.execute(
            f"SELECT kind, COUNT(*) AS count, AVG(duration_s) AS avg_duration_s, "
            "SUM(CASE WHEN resolved_by = 'operator' THEN 1 ELSE 0 END) AS operator_resolved, "
            "SUM(CASE WHEN resolved_by IS NOT NULL AND resolved_by != 'operator' THEN 1 ELSE 0 END) "
            "AS auto_resolved "
            f"FROM incidents{where} GROUP BY kind ORDER BY count DESC",
            params,
        ).fetchall()
        by_day_rows = conn.execute(
            f"SELECT date(triggered_at, 'unixepoch', 'localtime') AS day, COUNT(*) AS count "
            f"FROM incidents{where} GROUP BY day ORDER BY day",
            params,
        ).fetchall()
        by_channel_rows = conn.execute(
            f"SELECT COALESCE(channel_label, channel, 'unknown') AS channel, COUNT(*) AS count "
            f"FROM incidents{where} GROUP BY channel ORDER BY count DESC LIMIT 20",
            params,
        ).fetchall()
    return {
        "total": int(total_row["c"] or 0),
        "active": int(active_row["c"] or 0),
        "by_kind": [
            {
                "kind": r["kind"],
                "count": int(r["count"] or 0),
                "avg_duration_s": r["avg_duration_s"],
                "operator_resolved": int(r["operator_resolved"] or 0),
                "auto_resolved": int(r["auto_resolved"] or 0),
            }
            for r in by_kind_rows
        ],
        "by_day": [
            {"date": r["day"], "count": int(r["count"] or 0)}
            for r in by_day_rows
            if r["day"] is not None
        ],
        "by_channel": [
            {"channel": r["channel"], "count": int(r["count"] or 0)} for r in by_channel_rows
        ],
    }
