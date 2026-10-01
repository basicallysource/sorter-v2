"""Every connection to the backend's SQLite database, local_state.sqlite.

All store modules open their connections through connect(): the same pragmas
everywhere, each module's tables created once per process before its first use,
and a log line for any connection held longer than SLOW_MS or opened on a
thread that must never wait on the disk (the control loop, the API's event loop).
Such a thread hands its writes to defer(), which runs them on one writer thread.
"""

from __future__ import annotations

import os
import queue
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

SLOW_MS = 250.0
REALTIME_LOG_INTERVAL_S = 60.0

Schema = Callable[[sqlite3.Connection], None]

_prepare_lock = threading.Lock()
_prepared: set[tuple[Path, Schema]] = set()
# Closing the last connection to a WAL database checkpoints it and fsyncs,
# which stalls the whole process on an SD card. One idle connection held open
# for the process lifetime keeps every other close from being the last one: a
# connection that has read a WAL database holds a shared lock on the file until
# it closes, and a close only checkpoints when it can lock the file exclusively.
_keeper: sqlite3.Connection | None = None
_keeper_path: Path | None = None

# Writes from threads that must never wait on the disk, run in order by one
# writer thread.
_deferred: "queue.Queue[tuple[str, Callable[[], Any]]]" = queue.Queue(maxsize=10_000)
_writer_lock = threading.Lock()
_writer: threading.Thread | None = None

_realtime_lock = threading.Lock()
_realtime_threads: set[int] = set()
_realtime_calls: dict[str, tuple[float, int]] = {}  # op -> (last logged at, calls since)
_logger: Any = None


def local_state_db_path() -> Path:
    env_path = os.getenv("LOCAL_STATE_DB_PATH")
    if isinstance(env_path, str) and env_path.strip():
        return Path(env_path).expanduser()
    return Path(__file__).resolve().parent / "local_state.sqlite"


def configure(logger: Any) -> None:
    global _logger
    _logger = logger


def report_failure(op: str, exc: BaseException) -> None:
    """For a caller that carries on when a database write fails: say so."""
    _warn(f"[db] {op} failed: {exc}")


def defer(op: str, write: Callable[[], Any]) -> None:
    """Run `write` on the database writer thread instead of the caller's, after
    every write deferred before it. A failure is logged, not raised."""
    global _writer
    with _writer_lock:
        if _writer is None:
            _writer = threading.Thread(target=_run_deferred, name="db-writer", daemon=True)
            _writer.start()
    try:
        _deferred.put_nowait((op, write))
    except queue.Full:
        _warn(f"[db] write queue full, dropped {op}")


def drain(timeout_s: float) -> bool:
    """Wait until every write deferred so far has run."""
    done = threading.Event()
    defer("drain", done.set)
    return done.wait(timeout_s)


def _run_deferred() -> None:
    while True:
        op, write = _deferred.get()
        try:
            write()
        except Exception as exc:
            report_failure(op, exc)


def watch_realtime_thread(watch: bool = True) -> None:
    """Log the connections the calling thread opens from now on (it must never
    wait on the disk), or stop."""
    (_realtime_threads.add if watch else _realtime_threads.discard)(threading.get_ident())


@contextmanager
def connect(schema: Schema | None = None, *, op: str | None = None) -> Iterator[sqlite3.Connection]:
    """A connection for one operation, closed on exit. `schema` creates the
    caller's tables; it runs once per database file, before its first use."""
    path = local_state_db_path()
    if path != _keeper_path or (schema is not None and (path, schema) not in _prepared):
        _prepare(path, schema)
    if threading.get_ident() in _realtime_threads:
        _note_realtime(op or _caller())
    started = time.perf_counter()
    conn = _open(path)
    try:
        yield conn
    finally:
        conn.close()
        held_ms = (time.perf_counter() - started) * 1000.0
        if held_ms > SLOW_MS:
            _warn(f"[db] slow {op or _caller()} {held_ms:.0f}ms on {threading.current_thread().name}")


def _open(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    # WAL with synchronous=NORMAL: a commit appends to the WAL without an
    # fsync; only checkpoints sync. A power cut can lose the last commits but
    # never corrupts the file. FULL (SQLite's default) fsyncs every commit,
    # which on an SD card costs more than the write itself.
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _prepare(path: Path, schema: Schema | None) -> None:
    global _keeper, _keeper_path
    with _prepare_lock:
        if path != _keeper_path:
            path.parent.mkdir(parents=True, exist_ok=True)
            keeper = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
            keeper.execute("PRAGMA journal_mode = WAL")
            keeper.execute("SELECT 1 FROM sqlite_master").fetchall()
            os.chmod(path, 0o600)
            if _keeper is not None:
                _keeper.close()
            _keeper, _keeper_path = keeper, path
        if schema is None or (path, schema) in _prepared:
            return
        conn = _open(path)
        try:
            schema(conn)
            conn.commit()
        finally:
            conn.close()
        _prepared.add((path, schema))


def _caller() -> str:
    # The function whose `with connect()` this is: past this helper, the
    # generator, and contextlib's __enter__/__exit__.
    frame = sys._getframe(3)
    module = str(frame.f_globals.get("__name__", "?"))
    return f"{module}.{frame.f_code.co_name}"


def _note_realtime(op: str) -> None:
    now = time.monotonic()
    with _realtime_lock:
        logged_at, calls = _realtime_calls.get(op, (float("-inf"), 0))
        calls += 1
        if now - logged_at < REALTIME_LOG_INTERVAL_S:
            _realtime_calls[op] = (logged_at, calls)
            return
        _realtime_calls[op] = (now, 0)
    _warn(
        f"[db] on realtime thread {op} ({threading.current_thread().name}, "
        f"{calls} call(s) since the last such line)"
    )


def _warn(message: str) -> None:
    if _logger is not None:
        _logger.warning(message)


def add_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """ALTER TABLE ... ADD COLUMN for each column a database made by an older version lacks."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for column, decl in columns.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
