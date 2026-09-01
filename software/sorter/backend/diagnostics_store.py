from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from local_state import local_state_db_path

# Machine-health diagnostics: lifecycle (restarts/crashes), a health time series,
# hardware faults, and the backend's own error log. Every table is an
# append-only stream with a monotonic id, which is the sync cursor the Hive
# worker walks — the same watermark scheme piece_records uses, so an hour spent
# offline uploads in full once the machine reconnects. That replay is the whole
# point: the window we most need is the one where the machine could not talk to
# us.
#
# Its own sqlite file, never local_state.sqlite: diagnostics volume must never
# be able to bloat live machine state (that is how local_state reached 1.9GB on
# GBL). Writes are buffered in memory and flushed on ONE long-lived connection
# owned by the writer thread — connecting per write checkpoints and fsyncs the
# WAL every time, the eMMC stall local_state's keeper-connection comment warns
# about. Losing a flush interval of rows on a hard kill is an acceptable trade
# for never touching the disk on a caller's thread; the one exception is the
# shutdown marker, which is written synchronously precisely because the process
# is about to disappear.

_FLUSH_INTERVAL_S = 20.0
_RETENTION_INTERVAL_S = 900.0
_RETENTION_DELETE_BATCH = 2000
_RETENTION_DELETE_PACING_S = 0.05
_MAX_BUFFERED_ROWS = 20_000

KIND_LIFECYCLE = "lifecycle_events"
KIND_HEALTH = "health_samples"
KIND_HARDWARE_FAULT = "hardware_faults"
KIND_ERROR = "error_events"

ALL_KINDS: tuple[str, ...] = (KIND_LIFECYCLE, KIND_HEALTH, KIND_HARDWARE_FAULT, KIND_ERROR)

# Per-table retention. Age bounds how far back an investigation can reach; the
# row cap is the backstop that bounds disk when something goes wrong and starts
# emitting far faster than its nominal rate.
_RETENTION: dict[str, tuple[float, int]] = {
    # Restarts are rare and are the highest-value rows we hold — keep a season.
    KIND_LIFECYCLE: (180.0 * 86400.0, 20_000),
    # 60s sampling => 1440 rows/day. 30 days ~ 43k rows, a few MB.
    KIND_HEALTH: (30.0 * 86400.0, 120_000),
    KIND_HARDWARE_FAULT: (30.0 * 86400.0, 50_000),
    KIND_ERROR: (14.0 * 86400.0, 50_000),
}

_COLUMNS: dict[str, tuple[str, ...]] = {
    KIND_LIFECYCLE: (
        "at", "kind", "boot_uuid", "os_boot_id", "os_rebooted", "previous_clean",
        "system_uptime_s", "process_uptime_s", "exit_signal", "exit_code",
        "restarter", "software_version", "detail",
    ),
    KIND_HEALTH: (
        "at", "cpu_temp_c", "cpu_temp_max_c", "load1", "load5",
        "mem_available_bytes", "mem_total_bytes", "disk_free_bytes",
        "disk_total_bytes", "proc_rss_bytes", "cpu_freq_khz", "throttle_state",
        "upload_queue_depth", "sorting", "detail",
    ),
    KIND_HARDWARE_FAULT: ("at", "first_at", "kind", "subsystem", "count", "detail"),
    KIND_ERROR: ("at", "first_at", "level", "source", "message", "traceback", "count"),
}

_SCHEMA: dict[str, str] = {
    KIND_LIFECYCLE: (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "at REAL NOT NULL, "
        "kind TEXT NOT NULL, "
        "boot_uuid TEXT, "
        "os_boot_id TEXT, "
        "os_rebooted INTEGER, "
        "previous_clean INTEGER, "
        "system_uptime_s REAL, "
        "process_uptime_s REAL, "
        "exit_signal INTEGER, "
        "exit_code INTEGER, "
        "restarter TEXT, "
        "software_version TEXT, "
        "detail TEXT"
    ),
    KIND_HEALTH: (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "at REAL NOT NULL, "
        "cpu_temp_c REAL, "
        "cpu_temp_max_c REAL, "
        "load1 REAL, "
        "load5 REAL, "
        "mem_available_bytes INTEGER, "
        "mem_total_bytes INTEGER, "
        "disk_free_bytes INTEGER, "
        "disk_total_bytes INTEGER, "
        "proc_rss_bytes INTEGER, "
        "cpu_freq_khz INTEGER, "
        "throttle_state INTEGER, "
        "upload_queue_depth INTEGER, "
        "sorting INTEGER, "
        "detail TEXT"
    ),
    KIND_HARDWARE_FAULT: (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "at REAL NOT NULL, "
        "first_at REAL, "
        "kind TEXT NOT NULL, "
        "subsystem TEXT, "
        "count INTEGER NOT NULL DEFAULT 1, "
        "detail TEXT"
    ),
    KIND_ERROR: (
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "at REAL NOT NULL, "
        "first_at REAL, "
        "level TEXT NOT NULL, "
        "source TEXT, "
        "message TEXT NOT NULL, "
        "traceback TEXT, "
        "count INTEGER NOT NULL DEFAULT 1"
    ),
}

_buffer_lock = threading.Lock()
_buffers: dict[str, list[tuple[Any, ...]]] = {kind: [] for kind in ALL_KINDS}
_dropped: dict[str, int] = {kind: 0 for kind in ALL_KINDS}

_writer_lock = threading.Lock()
_writer_started = False


def diagnosticsDbPath() -> Path:
    env_path = os.getenv("DIAGNOSTICS_DB_PATH")
    if isinstance(env_path, str) and env_path.strip():
        return Path(env_path).expanduser()
    return local_state_db_path().with_name("diagnostics.sqlite")


def _connect() -> sqlite3.Connection:
    db_path = diagnosticsDbPath()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass
    return conn


def _ensureSchema(conn: sqlite3.Connection) -> None:
    for kind, columns in _SCHEMA.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {kind} ({columns})")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{kind}_at ON {kind}(at)")
    conn.commit()


def _insertSql(kind: str) -> str:
    columns = _COLUMNS[kind]
    placeholders = ", ".join("?" for _ in columns)
    return f"INSERT INTO {kind}({', '.join(columns)}) VALUES({placeholders})"


def _rowTuple(kind: str, values: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(values.get(column) for column in _COLUMNS[kind])


def _append(kind: str, values: dict[str, Any]) -> None:
    with _buffer_lock:
        buffer = _buffers[kind]
        buffer.append(_rowTuple(kind, values))
        # Bound memory if the writer stalls (eMMC hang, disk full). Oldest rows
        # go first, and the drop is counted so the gap is visible rather than
        # silent — a health series with an unexplained hole reads as "the
        # machine was fine", which is the opposite of the truth.
        overflow = len(buffer) - _MAX_BUFFERED_ROWS
        if overflow > 0:
            del buffer[:overflow]
            _dropped[kind] += overflow
    _ensureWriterStarted()


def _flushBuffers(conn: sqlite3.Connection) -> None:
    with _buffer_lock:
        pending = {kind: list(rows) for kind, rows in _buffers.items() if rows}
        for kind in pending:
            _buffers[kind].clear()
    if not pending:
        return
    for kind, rows in pending.items():
        conn.executemany(_insertSql(kind), rows)
    conn.commit()


def _deleteBatched(conn: sqlite3.Connection, table: str, where_sql: str, params: tuple[Any, ...]) -> None:
    while True:
        cur = conn.execute(
            f"DELETE FROM {table} WHERE id IN ("
            f"SELECT id FROM {table} WHERE {where_sql} ORDER BY id LIMIT ?)",
            (*params, _RETENTION_DELETE_BATCH),
        )
        removed = cur.rowcount or 0
        conn.commit()
        if removed < _RETENTION_DELETE_BATCH:
            return
        time.sleep(_RETENTION_DELETE_PACING_S)


def _applyRetention(conn: sqlite3.Connection) -> None:
    now = time.time()
    for kind, (max_age_s, max_rows) in _RETENTION.items():
        _deleteBatched(conn, kind, "at < ?", (now - max_age_s,))
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {kind}").fetchone()
        excess = int(row["n"] or 0) - max_rows
        while excess > 0:
            cur = conn.execute(
                f"DELETE FROM {kind} WHERE id IN (SELECT id FROM {kind} ORDER BY id LIMIT ?)",
                (min(excess, _RETENTION_DELETE_BATCH),),
            )
            removed = cur.rowcount or 0
            conn.commit()
            if removed <= 0:
                break
            excess -= removed
            if excess > 0:
                time.sleep(_RETENTION_DELETE_PACING_S)


def _writerLoop() -> None:
    # Must never die: a transient "database is locked" would otherwise end all
    # diagnostics for the process lifetime — and the runs where that happens are
    # exactly the ones worth recording. Rebuild the connection and carry on.
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
            try:
                conn.close()
            except Exception:
                pass
            conn = None
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
        thread = threading.Thread(target=_writerLoop, name="diagnostics-writer", daemon=True)
        thread.start()
        _writer_started = True


def recordHealthSample(values: dict[str, Any]) -> None:
    _append(KIND_HEALTH, values)


def recordHardwareFault(
    kind: str,
    subsystem: str | None = None,
    detail: dict[str, Any] | None = None,
    *,
    first_at: float | None = None,
    count: int = 1,
) -> None:
    now = time.time()
    _append(
        KIND_HARDWARE_FAULT,
        {
            "at": now,
            "first_at": first_at if first_at is not None else now,
            "kind": kind,
            "subsystem": subsystem,
            "count": max(1, int(count)),
            "detail": json.dumps(detail) if detail else None,
        },
    )


def recordErrorEvent(
    level: str,
    message: str,
    *,
    source: str | None = None,
    traceback_text: str | None = None,
    first_at: float | None = None,
    count: int = 1,
) -> None:
    now = time.time()
    _append(
        KIND_ERROR,
        {
            "at": now,
            "first_at": first_at if first_at is not None else now,
            "level": level,
            "source": source,
            "message": message,
            "traceback": traceback_text,
            "count": max(1, int(count)),
        },
    )


def recordLifecycleEvent(values: dict[str, Any], *, immediate: bool = False) -> None:
    # immediate=True bypasses the buffer and commits on its own connection. Used
    # only for the shutdown marker: main.py exits via os._exit(0) from the signal
    # handler, so a buffered row would never reach disk — and that row's absence
    # on the next start is exactly what we read as "this was not a clean stop".
    # Rare enough that the extra fsync costs nothing.
    if not immediate:
        _append(KIND_LIFECYCLE, values)
        return
    try:
        conn = _connect()
    except Exception:
        return
    try:
        _ensureSchema(conn)
        conn.execute(_insertSql(KIND_LIFECYCLE), _rowTuple(KIND_LIFECYCLE, values))
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def flushNow() -> bool:
    try:
        conn = _connect()
    except Exception:
        return False
    try:
        _ensureSchema(conn)
        _flushBuffers(conn)
        return True
    except Exception:
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _readOnly() -> sqlite3.Connection | None:
    path = diagnosticsDbPath()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn
    except Exception:
        return None


def listRowsAfter(kind: str, id_cursor: int, limit: int) -> list[dict[str, Any]]:
    if kind not in _COLUMNS:
        return []
    conn = _readOnly()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            f"SELECT id, {', '.join(_COLUMNS[kind])} FROM {kind} "
            "WHERE id > ? ORDER BY id ASC LIMIT ?",
            (int(id_cursor), int(limit)),
        ).fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def getMaxId(kind: str) -> int:
    if kind not in _COLUMNS:
        return 0
    conn = _readOnly()
    if conn is None:
        return 0
    try:
        row = conn.execute(f"SELECT COALESCE(MAX(id), 0) AS m FROM {kind}").fetchone()
        return int(row["m"] or 0)
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def lastLifecycleEvent() -> dict[str, Any] | None:
    conn = _readOnly()
    if conn is None:
        return None
    try:
        row = conn.execute(
            f"SELECT id, {', '.join(_COLUMNS[KIND_LIFECYCLE])} FROM {KIND_LIFECYCLE} "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def droppedCounts() -> dict[str, int]:
    with _buffer_lock:
        return dict(_dropped)


def summary() -> dict[str, Any]:
    conn = _readOnly()
    counts: dict[str, int] = {kind: 0 for kind in ALL_KINDS}
    if conn is not None:
        try:
            for kind in ALL_KINDS:
                row = conn.execute(f"SELECT COUNT(*) AS n FROM {kind}").fetchone()
                counts[kind] = int(row["n"] or 0)
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    path = diagnosticsDbPath()
    return {
        "path": str(path),
        "bytes": path.stat().st_size if path.exists() else 0,
        "counts": counts,
        "dropped": droppedCounts(),
    }
