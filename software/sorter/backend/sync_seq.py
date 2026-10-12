"""The one cursor rule for what this machine sends to Hive.

A row that never changes after it is written syncs by its id (crops, control
data, samples, predictions). A row that changes syncs by its sync_seq: a value
from one machine-wide counter, taken inside the same write transaction every
time the row becomes ready to send or changes. SQLite has one writer, and the
counter is bumped with a write, so a transaction holds the write lock from the
moment it takes a value until it commits: commit order equals seq order. A
reader that sees seq N therefore sees every seq below N, and sending
`sync_seq > watermark` in seq order never skips a row.

Hive keeps, per data type, the highest value it accepted. When a table first
gets the column, its existing rows take sync_seq = id and the counter is raised
above every existing id, so the watermark Hive already holds (the highest id it
accepted) keeps meaning "everything at or below this is on Hive".
"""

from __future__ import annotations

import sqlite3
import time

import db

# The tables whose rows sync by sync_seq.
TABLES = ("piece_records", "piece_images")


def _createCounter(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sync_counter ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "value INTEGER NOT NULL"
        ")"
    )
    if conn.execute("SELECT 1 FROM sync_counter WHERE id = 1").fetchone() is None:
        start = 0
        for table in TABLES:
            if _hasTable(conn, table):
                start = max(start, _maxId(conn, table))
        conn.execute("INSERT INTO sync_counter (id, value) VALUES (1, ?)", (start,))


def _hasTable(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        is not None
    )


def _maxId(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0])


def addColumn(conn: sqlite3.Connection, table: str) -> bool:
    """Give `table` (one of TABLES, with an integer id) its sync_seq column and
    index. The first time, every existing row takes sync_seq = id and the
    counter is raised above the table's highest id. Returns True on that
    first time. Runs inside the caller's schema transaction."""
    if table not in TABLES:
        raise ValueError(f"{table} does not sync by sync_seq")
    _createCounter(conn)
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    added = "sync_seq" not in columns
    started = time.monotonic()
    if added:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN sync_seq INTEGER")
        rows = conn.execute(f"UPDATE {table} SET sync_seq = id").rowcount
        conn.execute(
            "UPDATE sync_counter SET value = MAX(value, ?) WHERE id = 1",
            (_maxId(conn, table),),
        )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_sync_seq ON {table}(sync_seq)")
    if added:
        db.note(f"[db] {table}: sync cursor added to {rows} rows in {time.monotonic() - started:.1f}s")
    return added


def nextSeq(conn: sqlite3.Connection) -> int:
    """The next value, taken inside the caller's write transaction (the UPDATE
    takes the write lock, which the transaction keeps until it commits)."""
    conn.execute("UPDATE sync_counter SET value = value + 1 WHERE id = 1")
    return int(conn.execute("SELECT value FROM sync_counter WHERE id = 1").fetchone()[0])
