"""The machine's telemetry records, kept until every Hive has them.

A record is one small JSON document about how the machine is set up or how it
runs, written by fleet_telemetry and sent by the sync worker's telemetry leg
(the machine_telemetry stream) to every Hive, by its id: records never change
once written. Three forms:

- snapshot: state (the machine specs), written only when it differs from the
  last one of its kind, so a quiet machine writes none.
- window: a distribution over a stretch of sorting (stepper load, camera
  readings), an hour at most, closed when sorting stops.
- event: something rare and discrete (a stall), with its context.

`kind` names what the record describes and `schema` the version of its data's
shape, so Hive can read old and new records side by side.

The table stays small: a sorting hour writes a few KB. A record goes once every
Hive has it and it is a week old, or after KEEP_DAYS whatever happened.
"""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any

import db

FORM_SNAPSHOT = "snapshot"
FORM_WINDOW = "window"
FORM_EVENT = "event"
FORMS = (FORM_SNAPSHOT, FORM_WINDOW, FORM_EVENT)

# Hive refuses a record whose data is larger than this.
MAX_DATA_BYTES = 64 * 1024
SYNCED_KEEP_DAYS = 7.0
KEEP_DAYS = 60.0


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS telemetry_records ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "kind TEXT NOT NULL, "
        "form TEXT NOT NULL, "
        "schema INTEGER NOT NULL, "
        "started_at REAL NOT NULL, "
        "ended_at REAL NOT NULL, "
        "data TEXT NOT NULL, "
        "created_at REAL NOT NULL, "
        "synced_at REAL"
        ")"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_telemetry_records_kind ON telemetry_records(kind, id)"
    )


def _connection():
    return db.connect(_createTables)


def write(
    kind: str,
    form: str,
    data: dict[str, Any],
    *,
    started_at: float,
    ended_at: float | None = None,
    schema: int = 1,
) -> int | None:
    """Keep one record; returns its id, or None when it is not one Hive would
    take (an unknown form, or data over MAX_DATA_BYTES)."""
    if form not in FORMS:
        raise ValueError(f"Unknown telemetry form '{form}'.")
    encoded = json.dumps(data, separators=(",", ":"), sort_keys=True, default=str, allow_nan=False)
    if len(encoded.encode()) > MAX_DATA_BYTES:
        return None
    ended_at = started_at if ended_at is None else ended_at
    with _connection() as conn:
        cursor = conn.execute(
            "INSERT INTO telemetry_records (kind, form, schema, started_at, ended_at, data, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, form, int(schema), float(started_at), float(ended_at), encoded, time.time()),
        )
        conn.commit()
        return int(cursor.lastrowid)


def lastSnapshot(kind: str) -> dict[str, Any] | None:
    """The data of the newest snapshot of `kind`, to compare a new one with."""
    with _connection() as conn:
        row = conn.execute(
            "SELECT data FROM telemetry_records WHERE kind = ? AND form = ? ORDER BY id DESC LIMIT 1",
            (kind, FORM_SNAPSHOT),
        ).fetchone()
    return json.loads(row["data"]) if row else None


def listAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    """Records above `after_id` in id order, as the sync leg sends them."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, kind, form, schema, started_at, ended_at, data FROM telemetry_records "
            "WHERE id > ? ORDER BY id LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    return [
        {
            "local_id": int(row["id"]),
            "kind": row["kind"],
            "form": row["form"],
            "schema": int(row["schema"]),
            "started_at": float(row["started_at"]),
            "ended_at": float(row["ended_at"]),
            "data": json.loads(row["data"]),
        }
        for row in rows
    ]


def maxId() -> int:
    with _connection() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS m FROM telemetry_records").fetchone()
    return int(row["m"])


def stats() -> dict[str, int]:
    with _connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(data)), 0) AS total, "
            "COALESCE(SUM(CASE WHEN synced_at IS NULL THEN 1 ELSE 0 END), 0) AS waiting "
            "FROM telemetry_records"
        ).fetchone()
    return {"count": int(row["n"]), "bytes": int(row["total"]), "waiting": int(row["waiting"])}


def markSyncedUpTo(max_id: int, synced_at: float) -> None:
    if max_id <= 0:
        return
    with _connection() as conn:
        conn.execute(
            "UPDATE telemetry_records SET synced_at = ? WHERE id <= ? AND synced_at IS NULL",
            (float(synced_at), int(max_id)),
        )
        conn.commit()


def prune(now: float) -> int:
    """Delete what every Hive has had for a week, and anything past KEEP_DAYS."""
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM telemetry_records WHERE (synced_at IS NOT NULL AND created_at < ?) OR created_at < ?",
            (now - SYNCED_KEEP_DAYS * 86400.0, now - KEEP_DAYS * 86400.0),
        )
        conn.commit()
        return int(cursor.rowcount or 0)
