from __future__ import annotations

import sqlite3
import time
from typing import Any

import db
import local_state

# The dashboard's "pieces passed" counter. Resetting it must not touch the
# piece history, so a reset only records a baseline: the piece-records total
# at the moment of the reset. The counter is that total minus the baseline,
# and the baseline survives restarts like every other state entry.

_STATE_KEY = "pieces_counter_baseline"


def _createTables(conn: sqlite3.Connection) -> None:
    local_state.create_tables(conn)


def _connection(op: str | None = None):
    return db.connect(_createTables, op=op)


def getBaseline() -> dict[str, Any]:
    with _connection("pieces_counter_store.getBaseline()") as conn:
        value = local_state.read_entry(conn, _STATE_KEY)
    if not isinstance(value, dict) or not isinstance(value.get("total_at_reset"), int):
        return {"total_at_reset": 0, "reset_at": None}
    return value


def setBaseline(total_at_reset: int) -> dict[str, Any]:
    value = {"total_at_reset": int(total_at_reset), "reset_at": time.time()}
    with _connection("pieces_counter_store.setBaseline()") as conn:
        local_state.write_entry(conn, _STATE_KEY, value)
        conn.commit()
    return value
