from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from local_state import local_state_db_path

# Per-second diagnostic metric snapshots, split out of local_state.sqlite so
# they can never bloat the live state DB again (they reached 1.9GB / 6.8M rows
# on GBL). Writes are buffered in memory and flushed every ~15s in a single
# transaction on ONE long-lived connection owned by the writer thread — opening
# and closing a connection per write would checkpoint + fsync the WAL on every
# close, which is the exact eMMC stall local_state's keeper-connection comment
# warns about. Diagnostics-only data: losing up to a flush interval of buffered
# rows on crash is fine.

_FLUSH_INTERVAL_S = 15.0
_RETENTION_INTERVAL_S = 600.0
_RETENTION_MAX_AGE_S = 86400.0
_RETENTION_MAX_ROWS = 2_500_000
_RETENTION_DELETE_BATCH = 5000
_RETENTION_DELETE_PACING_S = 0.05
_MAX_BUFFERED_ROWS = 50_000

_RUNTIME_PERF_TABLE = "runtime_perf_metric_snapshots"
_PROFILER_TABLE = "profiler_metric_snapshots"

_buffer_lock = threading.Lock()
_runtime_perf_buffer: list[tuple[Any, ...]] = []
_profiler_buffer: list[tuple[Any, ...]] = []

_writer_lock = threading.Lock()
_writer_started = False


def localMetricsDbPath() -> Path:
    env_path = os.getenv("LOCAL_METRICS_DB_PATH")
    if isinstance(env_path, str) and env_path.strip():
        return Path(env_path).expanduser()
    return local_state_db_path().with_name("local_metrics.sqlite")


def _connect() -> sqlite3.Connection:
    db_path = localMetricsDbPath()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass
    return conn


def _ensureSchema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_PROFILER_TABLE} ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "run_id TEXT NOT NULL, "
        "recorded_at REAL NOT NULL, "
        "metric_kind TEXT NOT NULL, "
        "metric_name TEXT NOT NULL, "
        "count INTEGER NOT NULL DEFAULT 0, "
        "total_ms REAL, "
        "min_ms REAL, "
        "max_ms REAL, "
        "last_ms REAL, "
        "total_value REAL, "
        "max_value REAL, "
        "last_value REAL"
        ")"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_PROFILER_TABLE}_time "
        f"ON {_PROFILER_TABLE}(recorded_at)"
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_RUNTIME_PERF_TABLE} ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "run_id TEXT NOT NULL, "
        "recorded_at REAL NOT NULL, "
        "metric_name TEXT NOT NULL, "
        "sample_count INTEGER NOT NULL DEFAULT 0, "
        "avg_ms REAL, "
        "med_ms REAL, "
        "p90_ms REAL, "
        "min_ms REAL, "
        "max_ms REAL, "
        "last_ms REAL"
        ")"
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{_RUNTIME_PERF_TABLE}_time "
        f"ON {_RUNTIME_PERF_TABLE}(recorded_at)"
    )
    conn.commit()


def _deleteBatched(conn: sqlite3.Connection, table: str, where_sql: str, params: tuple[Any, ...]) -> int:
    removed = 0
    while True:
        cur = conn.execute(
            f"DELETE FROM {table} WHERE id IN ("
            f"SELECT id FROM {table} WHERE {where_sql} ORDER BY id LIMIT ?)",
            (*params, _RETENTION_DELETE_BATCH),
        )
        n = cur.rowcount or 0
        conn.commit()
        removed += n
        if n < _RETENTION_DELETE_BATCH:
            return removed
        time.sleep(_RETENTION_DELETE_PACING_S)


def _applyRetention(conn: sqlite3.Connection) -> None:
    cutoff = time.time() - _RETENTION_MAX_AGE_S
    for table in (_RUNTIME_PERF_TABLE, _PROFILER_TABLE):
        _deleteBatched(conn, table, "recorded_at < ?", (cutoff,))
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        excess = int(row[0] or 0) - _RETENTION_MAX_ROWS
        while excess > 0:
            cur = conn.execute(
                f"DELETE FROM {table} WHERE id IN ("
                f"SELECT id FROM {table} ORDER BY id LIMIT ?)",
                (min(excess, _RETENTION_DELETE_BATCH),),
            )
            n = cur.rowcount or 0
            conn.commit()
            if n <= 0:
                break
            excess -= n
            if excess > 0:
                time.sleep(_RETENTION_DELETE_PACING_S)


def _flushBuffers(conn: sqlite3.Connection) -> None:
    with _buffer_lock:
        perf_rows = list(_runtime_perf_buffer)
        _runtime_perf_buffer.clear()
        profiler_rows = list(_profiler_buffer)
        _profiler_buffer.clear()
    if not perf_rows and not profiler_rows:
        return
    if perf_rows:
        conn.executemany(
            f"INSERT INTO {_RUNTIME_PERF_TABLE}("
            "run_id, recorded_at, metric_name, sample_count, avg_ms, med_ms, p90_ms, min_ms, max_ms, last_ms"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            perf_rows,
        )
    if profiler_rows:
        conn.executemany(
            f"INSERT INTO {_PROFILER_TABLE}("
            "run_id, recorded_at, metric_kind, metric_name, count, total_ms, min_ms, max_ms, last_ms, total_value, max_value, last_value"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            profiler_rows,
        )
    conn.commit()


def _writerLoop() -> None:
    # The thread must never die: a transient "database is locked" (e.g. an
    # ad-hoc script poking the file) would otherwise silently end all metric
    # persistence for the process lifetime. Retry the connection instead.
    conn: sqlite3.Connection | None = None
    last_retention_mono = float("-inf")
    while True:
        time.sleep(_FLUSH_INTERVAL_S)
        if conn is None:
            try:
                new_conn = _connect()
                _ensureSchema(new_conn)
                conn = new_conn
            except Exception:
                continue
        try:
            _flushBuffers(conn)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            continue
        now_mono = time.monotonic()
        if now_mono - last_retention_mono >= _RETENTION_INTERVAL_S:
            last_retention_mono = now_mono
            try:
                _applyRetention(conn)
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass


def _ensureWriterStarted() -> None:
    global _writer_started
    if _writer_started:
        return
    with _writer_lock:
        if _writer_started:
            return
        thread = threading.Thread(target=_writerLoop, name="local-metrics-writer", daemon=True)
        thread.start()
        _writer_started = True


def _appendRows(buffer: list[tuple[Any, ...]], rows: list[tuple[Any, ...]]) -> None:
    with _buffer_lock:
        buffer.extend(rows)
        # Bound memory if the writer thread stalls (e.g. eMMC hang) — oldest
        # diagnostics rows are the least valuable, drop them first.
        overflow = len(buffer) - _MAX_BUFFERED_ROWS
        if overflow > 0:
            del buffer[:overflow]
    _ensureWriterStarted()


def recordRuntimePerfMetricSnapshot(
    run_id: str,
    recorded_at: float,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    _appendRows(
        _runtime_perf_buffer,
        [
            (
                str(run_id),
                float(recorded_at),
                str(row.get("metric_name") or ""),
                int(row.get("sample_count") or 0),
                row.get("avg_ms"),
                row.get("med_ms"),
                row.get("p90_ms"),
                row.get("min_ms"),
                row.get("max_ms"),
                row.get("last_ms"),
            )
            for row in rows
        ],
    )


def recordProfilerMetricSnapshot(
    run_id: str,
    recorded_at: float,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    _appendRows(
        _profiler_buffer,
        [
            (
                str(run_id),
                float(recorded_at),
                str(row.get("metric_kind") or ""),
                str(row.get("metric_name") or ""),
                int(row.get("count") or 0),
                row.get("total_ms"),
                row.get("min_ms"),
                row.get("max_ms"),
                row.get("last_ms"),
                row.get("total_value"),
                row.get("max_value"),
                row.get("last_value"),
            )
            for row in rows
        ],
    )
