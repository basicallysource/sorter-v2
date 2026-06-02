from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from local_state import local_state_db_path

# Durable per-run runtime-stats history, fully decomposed into typed relational
# tables — no JSON blobs. Replaces the old per-run JSON dumps that only landed on
# a graceful shutdown. A run row holds the summary scalars; child tables hold the
# flat metric dicts (counts, perf_total_counts), the perf_ms summaries, the
# per-state-machine occupancy times, and the recent state-transition timeline.
# getSnapshot() reconstitutes exactly the subset of the live snapshot() payload
# that the history pages (dashboard/runtime, settings/performance) consume.

_INIT_LOCK = threading.Lock()
_initialized = False

# group keys for the EAV runtime_metrics table
GROUP_COUNTS = "counts"
GROUP_PERF_TOTAL_COUNTS = "perf_total_counts"


def _connect() -> sqlite3.Connection:
    db_path = local_state_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
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
                "CREATE TABLE IF NOT EXISTS runtime_runs ("
                "run_id TEXT PRIMARY KEY, "
                "machine_id TEXT, "
                "sorting_profile_path TEXT, "
                "started_at REAL, "
                "ended_at REAL, "
                "total_pieces INTEGER, "
                "lifecycle_state TEXT, "
                "is_running INTEGER, "
                "updated_at REAL, "
                "running_time_s REAL, "
                "distributed_count INTEGER, "
                "overall_ppm REAL, "
                "rolling_5min_ppm REAL, "
                "pieces_seen INTEGER"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_runtime_runs_started "
                "ON runtime_runs(started_at)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime_metrics ("
                "run_id TEXT NOT NULL, "
                "metric_group TEXT NOT NULL, "
                "key TEXT NOT NULL, "
                "value REAL, "
                "PRIMARY KEY (run_id, metric_group, key)"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime_perf_ms ("
                "run_id TEXT NOT NULL, "
                "key TEXT NOT NULL, "
                "n INTEGER, "
                "avg_ms REAL, "
                "med_ms REAL, "
                "p90_ms REAL, "
                "min_ms REAL, "
                "max_ms REAL, "
                "last_ms REAL, "
                "PRIMARY KEY (run_id, key)"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime_state_machines ("
                "run_id TEXT NOT NULL, "
                "machine TEXT NOT NULL, "
                "current_state TEXT, "
                "entered_at REAL, "
                "PRIMARY KEY (run_id, machine)"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime_state_times ("
                "run_id TEXT NOT NULL, "
                "machine TEXT NOT NULL, "
                "state TEXT NOT NULL, "
                "time_s REAL, "
                "PRIMARY KEY (run_id, machine, state)"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS runtime_timeline ("
                "run_id TEXT NOT NULL, "
                "seq INTEGER NOT NULL, "
                "ts REAL, "
                "machine TEXT, "
                "to_state TEXT, "
                "PRIMARY KEY (run_id, seq)"
                ")"
            )
            conn.commit()
            _initialized = True
        finally:
            conn.close()


def _deleteRun(conn: sqlite3.Connection, run_id: str) -> None:
    for table in (
        "runtime_runs",
        "runtime_metrics",
        "runtime_perf_ms",
        "runtime_state_machines",
        "runtime_state_times",
        "runtime_timeline",
    ):
        conn.execute(f"DELETE FROM {table} WHERE run_id = ?", (run_id,))


def saveRun(
    run_id: str,
    snapshot: dict[str, Any],
    *,
    machine_id: Optional[str] = None,
    sorting_profile_path: Optional[str] = None,
    started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    total_pieces: Optional[int] = None,
) -> None:
    if not isinstance(run_id, str) or not run_id:
        return
    counts = snapshot.get("counts") or {}
    throughput = snapshot.get("throughput") or {}
    perf_total_counts = snapshot.get("perf_total_counts") or {}
    perf_ms = snapshot.get("perf_ms") or {}
    state_machines = snapshot.get("state_machines") or {}
    timeline = snapshot.get("timeline_recent") or []

    with _connection() as conn:
        _deleteRun(conn, run_id)
        conn.execute(
            "INSERT INTO runtime_runs "
            "(run_id, machine_id, sorting_profile_path, started_at, ended_at, "
            "total_pieces, lifecycle_state, is_running, updated_at, running_time_s, "
            "distributed_count, overall_ppm, rolling_5min_ppm, pieces_seen) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                machine_id,
                sorting_profile_path,
                started_at,
                ended_at,
                total_pieces,
                snapshot.get("lifecycle_state"),
                1 if snapshot.get("is_running") else 0,
                snapshot.get("updated_at"),
                throughput.get("running_time_s"),
                throughput.get("distributed_count"),
                throughput.get("overall_ppm"),
                throughput.get("rolling_5min_ppm"),
                counts.get("pieces_seen"),
            ),
        )

        metric_rows: list[tuple[str, str, str, Optional[float]]] = []
        for key, value in counts.items():
            if isinstance(value, (int, float)):
                metric_rows.append((run_id, GROUP_COUNTS, str(key), float(value)))
        for key, value in perf_total_counts.items():
            if isinstance(value, (int, float)):
                metric_rows.append((run_id, GROUP_PERF_TOTAL_COUNTS, str(key), float(value)))
        if metric_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO runtime_metrics "
                "(run_id, metric_group, key, value) VALUES (?, ?, ?, ?)",
                metric_rows,
            )

        perf_rows = []
        for key, summary in perf_ms.items():
            if not isinstance(summary, dict):
                continue
            perf_rows.append(
                (
                    run_id,
                    str(key),
                    summary.get("n"),
                    summary.get("avg_ms"),
                    summary.get("med_ms"),
                    summary.get("p90_ms"),
                    summary.get("min_ms"),
                    summary.get("max_ms"),
                    summary.get("last_ms"),
                )
            )
        if perf_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO runtime_perf_ms "
                "(run_id, key, n, avg_ms, med_ms, p90_ms, min_ms, max_ms, last_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                perf_rows,
            )

        sm_rows = []
        st_rows = []
        for machine, data in state_machines.items():
            if not isinstance(data, dict):
                continue
            sm_rows.append(
                (run_id, str(machine), data.get("current_state"), data.get("entered_at"))
            )
            for state, time_s in (data.get("state_time_s") or {}).items():
                if isinstance(time_s, (int, float)):
                    st_rows.append((run_id, str(machine), str(state), float(time_s)))
        if sm_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO runtime_state_machines "
                "(run_id, machine, current_state, entered_at) VALUES (?, ?, ?, ?)",
                sm_rows,
            )
        if st_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO runtime_state_times "
                "(run_id, machine, state, time_s) VALUES (?, ?, ?, ?)",
                st_rows,
            )

        tl_rows = []
        for seq, event in enumerate(timeline):
            if not isinstance(event, dict):
                continue
            tl_rows.append(
                (run_id, seq, event.get("ts"), event.get("machine"), event.get("to_state"))
            )
        if tl_rows:
            conn.executemany(
                "INSERT OR REPLACE INTO runtime_timeline "
                "(run_id, seq, ts, machine, to_state) VALUES (?, ?, ?, ?, ?)",
                tl_rows,
            )

        conn.commit()


def listRuns(*, limit: int = 500) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 2000))
    with _connection() as conn:
        rows = conn.execute(
            "SELECT run_id, started_at, ended_at, total_pieces FROM runtime_runs "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "record_id": r["run_id"],
            "run_id": r["run_id"],
            "started_at": float(r["started_at"] or 0.0),
            "ended_at": float(r["ended_at"] or 0.0),
            "total_pieces": int(r["total_pieces"] or 0),
        }
        for r in rows
    ]


def getSnapshot(run_id: str) -> Optional[dict[str, Any]]:
    with _connection() as conn:
        run = conn.execute(
            "SELECT * FROM runtime_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if run is None:
            return None
        metrics = conn.execute(
            "SELECT metric_group, key, value FROM runtime_metrics WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        perf = conn.execute(
            "SELECT key, n, avg_ms, med_ms, p90_ms, min_ms, max_ms, last_ms "
            "FROM runtime_perf_ms WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        machines = conn.execute(
            "SELECT machine, current_state, entered_at FROM runtime_state_machines "
            "WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        state_times = conn.execute(
            "SELECT machine, state, time_s FROM runtime_state_times WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        timeline = conn.execute(
            "SELECT ts, machine, to_state FROM runtime_timeline WHERE run_id = ? "
            "ORDER BY seq ASC",
            (run_id,),
        ).fetchall()

    counts: dict[str, Any] = {}
    perf_total_counts: dict[str, Any] = {}
    for m in metrics:
        if m["metric_group"] == GROUP_COUNTS:
            counts[m["key"]] = m["value"]
        elif m["metric_group"] == GROUP_PERF_TOTAL_COUNTS:
            perf_total_counts[m["key"]] = m["value"]

    perf_ms: dict[str, Any] = {}
    for p in perf:
        summary: dict[str, Any] = {"n": int(p["n"]) if p["n"] is not None else 0}
        for col in ("avg_ms", "med_ms", "p90_ms", "min_ms", "max_ms", "last_ms"):
            if p[col] is not None:
                summary[col] = p[col]
        perf_ms[p["key"]] = summary

    times_by_machine: dict[str, dict[str, float]] = {}
    for st in state_times:
        times_by_machine.setdefault(st["machine"], {})[st["state"]] = float(st["time_s"] or 0.0)

    state_machines: dict[str, Any] = {}
    for sm in machines:
        machine = sm["machine"]
        state_time_s = times_by_machine.get(machine, {})
        total_s = sum(state_time_s.values())
        share_pct = {
            state: (s / total_s) * 100.0 for state, s in state_time_s.items()
        } if total_s > 0 else {}
        state_machines[machine] = {
            "current_state": sm["current_state"],
            "entered_at": sm["entered_at"],
            "state_time_s": state_time_s,
            "state_share_pct": share_pct,
        }

    timeline_recent = [
        {"ts": t["ts"], "machine": t["machine"], "to_state": t["to_state"]}
        for t in timeline
    ]

    return {
        "updated_at": run["updated_at"],
        "lifecycle_state": run["lifecycle_state"],
        "is_running": bool(run["is_running"]),
        "counts": counts,
        "perf_ms": perf_ms,
        "perf_total_counts": perf_total_counts,
        "throughput": {
            "running_time_s": run["running_time_s"],
            "distributed_count": run["distributed_count"],
            "overall_ppm": run["overall_ppm"],
            "rolling_5min_ppm": run["rolling_5min_ppm"],
        },
        "state_machines": state_machines,
        "timeline_recent": timeline_recent,
    }
