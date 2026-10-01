from __future__ import annotations

import sqlite3
import time
from typing import Any

import db

# What the operator marked on a set's parts checklist: a manual found-count
# override and a state (auto, deferred, complete) per part and color. Keyed by
# the Rebrickable set_num so it survives profile swaps, bin clears and restarts.

_CHECKLIST_ALLOWED_STATES = ('auto', 'deferred', 'complete')


def _createTables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS checklist_part_state ("
        "set_num TEXT NOT NULL, "
        "part_num TEXT NOT NULL, "
        "color_id TEXT NOT NULL, "
        "manual_override_count INTEGER, "
        "user_state TEXT NOT NULL DEFAULT 'auto', "
        "updated_at REAL NOT NULL, "
        "PRIMARY KEY(set_num, part_num, color_id)"
        ")"
    )


def _connection():
    return db.connect(_createTables)


def get_checklist_state_for_set(set_num: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Return a lookup of checklist state keyed by (part_num, color_id) for a set.

    Entries with state == 'auto' and a NULL manual_override_count are omitted —
    they are indistinguishable from no-entry.
    """
    if not isinstance(set_num, str) or not set_num.strip():
        return {}
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with _connection() as conn:
        cursor = conn.execute(
            "SELECT part_num, color_id, manual_override_count, user_state, updated_at "
            "FROM checklist_part_state WHERE set_num = ?",
            (set_num.strip(),),
        )
        for row in cursor.fetchall():
            out[(str(row["part_num"]), str(row["color_id"]))] = {
                "manual_override_count": row["manual_override_count"],
                "user_state": row["user_state"] or "auto",
                "updated_at": row["updated_at"],
            }
    return out


def set_checklist_part_state(
    set_num: str,
    part_num: str,
    color_id: str,
    *,
    manual_override_count: int | None,
    user_state: str,
) -> dict[str, Any]:
    """Upsert a single checklist part state row.

    Pass manual_override_count=None to clear the override. user_state must be
    one of 'auto', 'deferred', 'complete'. When both override is None and
    user_state is 'auto', the row is deleted so future reads fall through to
    the live sorter count.
    """
    if not isinstance(set_num, str) or not set_num.strip():
        raise ValueError("set_num must be a non-empty string")
    if not isinstance(part_num, str) or not part_num.strip():
        raise ValueError("part_num must be a non-empty string")
    if not isinstance(color_id, str) or color_id == "":
        raise ValueError("color_id must be a non-empty string")
    if user_state not in _CHECKLIST_ALLOWED_STATES:
        raise ValueError(
            f"user_state must be one of {_CHECKLIST_ALLOWED_STATES}"
        )
    if manual_override_count is not None:
        if not isinstance(manual_override_count, int) or manual_override_count < 0:
            raise ValueError("manual_override_count must be a non-negative int or None")

    now = time.time()
    with _connection() as conn:
        if manual_override_count is None and user_state == "auto":
            conn.execute(
                "DELETE FROM checklist_part_state "
                "WHERE set_num = ? AND part_num = ? AND color_id = ?",
                (set_num.strip(), part_num.strip(), color_id),
            )
        else:
            conn.execute(
                "INSERT INTO checklist_part_state "
                "(set_num, part_num, color_id, manual_override_count, user_state, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(set_num, part_num, color_id) DO UPDATE SET "
                "manual_override_count = excluded.manual_override_count, "
                "user_state = excluded.user_state, "
                "updated_at = excluded.updated_at",
                (
                    set_num.strip(),
                    part_num.strip(),
                    color_id,
                    manual_override_count,
                    user_state,
                    now,
                ),
            )
        conn.commit()
    return {
        "manual_override_count": manual_override_count,
        "user_state": user_state,
        "updated_at": now,
    }
