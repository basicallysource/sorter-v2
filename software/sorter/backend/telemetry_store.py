"""The machine's telemetry records, kept until every Hive has them.

A record is one small JSON document about how the machine is set up or how it
runs, written by fleet_telemetry and computer_health. The sync worker's
telemetry leg (the machine_telemetry stream) sends them to every Hive, by their
id, except the kinds in LOCAL_KINDS, which are the machine's own and never leave
it. Records never change once written. Three forms:

- snapshot: state (the machine specs), written only when it differs from the
  last one of its kind, so a quiet machine writes none.
- window: a distribution over a stretch of time, an hour at most: of sorting
  (stepper load, camera readings; closed when sorting stops), or of the
  computer's health, sorting or not.
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


# Kinds kept on the machine and never sent: the computer's health is for the
# person at the machine (its Computer settings page reads it back).
LOCAL_KINDS = frozenset({"computer_health"})
_NOT_LOCAL = "kind NOT IN (" + ", ".join("?" for _ in LOCAL_KINDS) + ")"


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
    created_at = time.time()
    # A record that is never sent has nothing to wait for: it counts as sent,
    # so it is not shown as waiting and is pruned like one every Hive has.
    synced_at = created_at if kind in LOCAL_KINDS else None
    with _connection() as conn:
        cursor = conn.execute(
            "INSERT INTO telemetry_records (kind, form, schema, started_at, ended_at, data, created_at, synced_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (kind, form, int(schema), float(started_at), float(ended_at), encoded, created_at, synced_at),
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


def listKind(kind: str, since: float) -> list[dict[str, Any]]:
    """The records of `kind` that end at or after `since`, oldest first (the
    computer health page reads its history back this way after a restart)."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT started_at, ended_at, data FROM telemetry_records "
            "WHERE kind = ? AND ended_at >= ? ORDER BY id",
            (kind, float(since)),
        ).fetchall()
    return [
        {"started_at": float(row["started_at"]), "ended_at": float(row["ended_at"]), "data": json.loads(row["data"])}
        for row in rows
    ]


def listAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    """Records above `after_id` in id order, as the sync leg sends them: all
    but the machine's own (LOCAL_KINDS)."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT id, kind, form, schema, started_at, ended_at, data FROM telemetry_records "
            f"WHERE id > ? AND {_NOT_LOCAL} ORDER BY id LIMIT ?",
            (int(after_id), *LOCAL_KINDS, int(limit)),
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


def countAfter(after_id: int) -> int:
    """How many records above `after_id` the sync leg has yet to send."""
    with _connection() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM telemetry_records WHERE id > ? AND {_NOT_LOCAL}",
            (int(after_id), *LOCAL_KINDS),
        ).fetchone()
    return int(row["n"])


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
