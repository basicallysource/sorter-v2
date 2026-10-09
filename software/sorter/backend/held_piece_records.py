"""Every piece C2 or C3 could not move, one row each, for the Cycle time page.

The feeder's held-piece watch (subsystems/feeder/pulse_perception/held.py)
writes a row when a piece it turned the next channel for, or reported, is done
with: freed (it moved again), gone (it left the channel), or the sorting
stopped first. The row says how long it was held, how many turns of the next
channel it took, and whether the operator was called.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

import db

KEEP_DAYS = 60.0


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS held_pieces ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "channel INTEGER NOT NULL, "
        "track_id INTEGER, "
        "zone TEXT, "
        "started_at REAL NOT NULL, "
        "ended_at REAL NOT NULL, "
        "turns INTEGER NOT NULL, "
        "reported INTEGER NOT NULL, "
        "outcome TEXT NOT NULL"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_held_pieces_started ON held_pieces(started_at)")
    conn.execute("DELETE FROM held_pieces WHERE started_at < ?", (time.time() - KEEP_DAYS * 86400.0,))


def record(**row: Any) -> None:
    """Write one held piece, on the database writer thread (the feeder calls
    this from the control loop)."""

    def write() -> None:
        with db.connect(_createTables) as conn:
            names = list(row)
            conn.execute(
                f"INSERT INTO held_pieces ({', '.join(names)}) VALUES ({', '.join('?' for _ in names)})",
                [row[n] for n in names],
            )
            conn.commit()

    db.defer("held_piece_records.record", write)


def listHeld(since: float, until: Optional[float] = None) -> list[dict[str, Any]]:
    until = time.time() if until is None else until
    with db.connect(_createTables) as conn:
        rows = conn.execute(
            "SELECT * FROM held_pieces WHERE started_at >= ? AND started_at < ? ORDER BY started_at DESC",
            (since, until),
        ).fetchall()
    return [dict(r) for r in rows]
