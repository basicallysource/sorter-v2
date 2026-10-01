from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import db
import local_state

# What is in each bin. A sorting session (sorting_sessions) holds the current
# contents: a count per bin (bin_state_current), a count per distinct item in
# each bin (bin_item_aggregates) and one row per distributed piece
# (piece_events), with a log of session and clear events (bin_events). A new
# session carries the bins' contents forward; clearing a bin starts its next
# epoch and flushes what it held into the open bin snapshot (bin_snapshots,
# bin_snapshot_layers, bin_snapshot_items), which closes when every bin is
# cleared. metadata holds the active session's id and the open snapshot's id.

_META_KEY_ACTIVE_SORTING_SESSION_ID = "active_sorting_session_id"
_META_KEY_OPEN_BIN_SNAPSHOT_ID = "open_bin_snapshot_id"

# The control loop picks a bin for every piece by its current count, so it
# reads the counts from memory. Every write to bin_state_current holds
# _bin_state_write_lock and refreshes the copy after its commit, so the copy
# always matches the last commit.
_bin_state_write_lock = threading.RLock()
_bin_piece_counts: tuple[Path, dict[tuple[int, int, int], int]] | None = None

# The columns of a piece listing: the piece's event and its session's profile.
_PIECE_COLUMNS = (
    "p.piece_uuid, p.layer_index, p.section_index, p.bin_index, p.bin_epoch, "
    "p.distributed_at, p.created_at, p.classified_at, "
    "p.part_id, p.color_id, p.color_name, p.category_id, p.classification_status, "
    "p.thumbnail, p.top_image, p.bottom_image, p.brickognize_preview_url, "
    "s.profile_id, s.profile_name "
)


def _createTables(conn: sqlite3.Connection) -> None:
    # A new session is stamped with the machine id and the sorting profile,
    # read from the key/value state in the same transaction.
    local_state.create_tables(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS metadata ("
        "key TEXT PRIMARY KEY, "
        "value TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sorting_sessions ("
        "id TEXT PRIMARY KEY, "
        "machine_id TEXT NOT NULL, "
        "profile_id TEXT, "
        "profile_name TEXT, "
        "version_id TEXT, "
        "version_number INTEGER, "
        "version_label TEXT, "
        "artifact_hash TEXT, "
        "started_at REAL NOT NULL, "
        "ended_at REAL, "
        "status TEXT NOT NULL, "
        "reason TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bin_state_current ("
        "session_id TEXT NOT NULL, "
        "layer_index INTEGER NOT NULL, "
        "section_index INTEGER NOT NULL, "
        "bin_index INTEGER NOT NULL, "
        "bin_epoch INTEGER NOT NULL DEFAULT 0, "
        "piece_count INTEGER NOT NULL DEFAULT 0, "
        "unique_item_count INTEGER NOT NULL DEFAULT 0, "
        "last_distributed_at REAL, "
        "updated_at REAL NOT NULL, "
        "PRIMARY KEY(session_id, layer_index, section_index, bin_index), "
        "FOREIGN KEY(session_id) REFERENCES sorting_sessions(id) ON DELETE CASCADE"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bin_item_aggregates ("
        "session_id TEXT NOT NULL, "
        "layer_index INTEGER NOT NULL, "
        "section_index INTEGER NOT NULL, "
        "bin_index INTEGER NOT NULL, "
        "item_key TEXT NOT NULL, "
        "part_id TEXT, "
        "color_id TEXT, "
        "color_name TEXT, "
        "category_id TEXT, "
        "classification_status TEXT, "
        "count INTEGER NOT NULL DEFAULT 0, "
        "last_distributed_at REAL, "
        "thumbnail TEXT, "
        "top_image TEXT, "
        "bottom_image TEXT, "
        "brickognize_preview_url TEXT, "
        "PRIMARY KEY(session_id, layer_index, section_index, bin_index, item_key), "
        "FOREIGN KEY(session_id) REFERENCES sorting_sessions(id) ON DELETE CASCADE"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS piece_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT NOT NULL, "
        "piece_uuid TEXT NOT NULL, "
        "layer_index INTEGER NOT NULL, "
        "section_index INTEGER NOT NULL, "
        "bin_index INTEGER NOT NULL, "
        "bin_epoch INTEGER NOT NULL, "
        "distributed_at REAL NOT NULL, "
        "created_at REAL, "
        "classified_at REAL, "
        "part_id TEXT, "
        "color_id TEXT, "
        "color_name TEXT, "
        "category_id TEXT, "
        "classification_status TEXT, "
        "thumbnail TEXT, "
        "top_image TEXT, "
        "bottom_image TEXT, "
        "brickognize_preview_url TEXT, "
        "UNIQUE(session_id, piece_uuid), "
        "FOREIGN KEY(session_id) REFERENCES sorting_sessions(id) ON DELETE CASCADE"
        ")"
    )
    db.add_columns(conn, "piece_events", {"created_at": "REAL", "classified_at": "REAL"})
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_piece_events_bin_epoch "
        "ON piece_events(session_id, layer_index, section_index, bin_index, bin_epoch)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bin_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "session_id TEXT NOT NULL, "
        "event_type TEXT NOT NULL, "
        "created_at REAL NOT NULL, "
        "layer_index INTEGER, "
        "section_index INTEGER, "
        "bin_index INTEGER, "
        "bin_epoch INTEGER, "
        "details_json TEXT, "
        "FOREIGN KEY(session_id) REFERENCES sorting_sessions(id) ON DELETE CASCADE"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bin_snapshots ("
        "id TEXT PRIMARY KEY, "
        "status TEXT NOT NULL, "
        "label TEXT, "
        "created_at REAL NOT NULL, "
        "closed_at REAL, "
        "closed_reason TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bin_snapshot_layers ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "snapshot_id TEXT NOT NULL, "
        "session_id TEXT NOT NULL, "
        "layer_index INTEGER NOT NULL, "
        "section_index INTEGER NOT NULL, "
        "bin_index INTEGER NOT NULL, "
        "bin_epoch INTEGER NOT NULL, "
        "piece_count INTEGER NOT NULL DEFAULT 0, "
        "unique_item_count INTEGER NOT NULL DEFAULT 0, "
        "category_ids_json TEXT, "
        "flush_scope TEXT, "
        "flushed_at REAL NOT NULL, "
        "FOREIGN KEY(snapshot_id) REFERENCES bin_snapshots(id) ON DELETE CASCADE"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bin_snapshot_items ("
        "snapshot_layer_id INTEGER NOT NULL, "
        "item_key TEXT NOT NULL, "
        "part_id TEXT, "
        "color_id TEXT, "
        "color_name TEXT, "
        "category_id TEXT, "
        "classification_status TEXT, "
        "count INTEGER NOT NULL DEFAULT 0, "
        "last_distributed_at REAL, "
        "thumbnail TEXT, "
        "top_image TEXT, "
        "bottom_image TEXT, "
        "brickognize_preview_url TEXT, "
        "PRIMARY KEY(snapshot_layer_id, item_key), "
        "FOREIGN KEY(snapshot_layer_id) REFERENCES bin_snapshot_layers(id) ON DELETE CASCADE"
        ")"
    )


def _connection():
    return db.connect(_createTables)


def _get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT value FROM metadata WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    value = row["value"]
    return str(value) if value is not None else None


def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO metadata(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _session_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        key: row[key]
        for key in row.keys()
    }


def _close_active_sorting_session_conn(conn: sqlite3.Connection, *, reason: str | None = None) -> None:
    active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
    if not active_session_id:
        return
    conn.execute(
        "UPDATE sorting_sessions SET status = 'closed', ended_at = ?, reason = COALESCE(?, reason) WHERE id = ? AND status = 'active'",
        (time.time(), reason, active_session_id),
    )
    conn.execute("DELETE FROM metadata WHERE key = ?", (_META_KEY_ACTIVE_SORTING_SESSION_ID,))


def _create_sorting_session_conn(conn: sqlite3.Connection, *, reason: str | None = None) -> dict[str, Any]:
    sync_state = local_state.read_entry(conn, local_state.STATE_KEY_SORTING_PROFILE_SYNC)
    if not isinstance(sync_state, dict):
        sync_state = {}
    session_id = str(uuid.uuid4())
    now = time.time()
    raw_machine_id = local_state.read_entry(conn, local_state.STATE_KEY_MACHINE_ID)
    machine_id = str(raw_machine_id).strip() if isinstance(raw_machine_id, str) else "unknown-machine"
    if not machine_id:
        machine_id = "unknown-machine"
    session = {
        "id": session_id,
        "machine_id": machine_id,
        "profile_id": sync_state.get("profile_id"),
        "profile_name": sync_state.get("profile_name"),
        "version_id": sync_state.get("version_id"),
        "version_number": sync_state.get("version_number"),
        "version_label": sync_state.get("version_label"),
        "artifact_hash": sync_state.get("artifact_hash"),
        "started_at": now,
        "ended_at": None,
        "status": "active",
        "reason": reason,
    }
    conn.execute(
        "INSERT INTO sorting_sessions(id, machine_id, profile_id, profile_name, version_id, version_number, version_label, artifact_hash, started_at, ended_at, status, reason) "
        "VALUES(:id, :machine_id, :profile_id, :profile_name, :version_id, :version_number, :version_label, :artifact_hash, :started_at, :ended_at, :status, :reason)",
        session,
    )
    _set_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID, session_id)
    conn.execute(
        "INSERT INTO bin_events(session_id, event_type, created_at, details_json) VALUES(?, ?, ?, ?)",
        (session_id, "session_started", now, json.dumps({"reason": reason, "profile_name": sync_state.get("profile_name")}, sort_keys=True)),
    )
    return session


def _carry_forward_bin_contents_conn(
    conn: sqlite3.Connection, old_session_id: str, new_session_id: str
) -> None:
    """Copy physical bin contents (per-bin counts + per-item aggregates, with their
    bin_epoch) from the prior session into the new one. Bins are physical — switching
    a profile/layout must NOT appear to empty them. The only things that clear contents
    are the explicit wipe endpoints (clear_current_session_bins), which run against the
    current session *before* a new one is created, so a wiped bin carries forward empty."""
    if not old_session_id or old_session_id == new_session_id:
        return
    now = time.time()
    conn.execute(
        "INSERT OR IGNORE INTO bin_state_current"
        "(session_id, layer_index, section_index, bin_index, bin_epoch, piece_count, "
        "unique_item_count, last_distributed_at, updated_at) "
        "SELECT ?, layer_index, section_index, bin_index, bin_epoch, piece_count, "
        "unique_item_count, last_distributed_at, ? FROM bin_state_current WHERE session_id = ?",
        (new_session_id, now, old_session_id),
    )
    conn.execute(
        "INSERT OR IGNORE INTO bin_item_aggregates"
        "(session_id, layer_index, section_index, bin_index, item_key, part_id, color_id, "
        "color_name, category_id, classification_status, count, last_distributed_at, "
        "thumbnail, top_image, bottom_image, brickognize_preview_url) "
        "SELECT ?, layer_index, section_index, bin_index, item_key, part_id, color_id, "
        "color_name, category_id, classification_status, count, last_distributed_at, "
        "thumbnail, top_image, bottom_image, brickognize_preview_url "
        "FROM bin_item_aggregates WHERE session_id = ?",
        (new_session_id, old_session_id),
    )


def _ensure_active_sorting_session_conn(
    conn: sqlite3.Connection,
    *,
    force_new: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
    active_session = None
    if active_session_id:
        active_session = _session_row_to_dict(
            conn.execute(
                "SELECT * FROM sorting_sessions WHERE id = ? AND status = 'active'",
                (active_session_id,),
            ).fetchone()
        )

    if active_session is not None and not force_new:
        return active_session

    if force_new:
        _close_active_sorting_session_conn(conn, reason=reason)

    new_session = _create_sorting_session_conn(conn, reason=reason)
    if force_new and active_session_id:
        _carry_forward_bin_contents_conn(conn, active_session_id, new_session["id"])
    return new_session


def start_new_sorting_session(*, reason: str = "profile_activated") -> dict[str, Any]:
    with _bin_state_write_lock, _connection() as conn:
        session = _ensure_active_sorting_session_conn(conn, force_new=True, reason=reason)
        conn.commit()
        _refresh_bin_piece_counts(conn)
        return session


def get_active_sorting_session() -> dict[str, Any] | None:
    with _connection() as conn:
        active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
        if not active_session_id:
            return None
        row = conn.execute(
            "SELECT * FROM sorting_sessions WHERE id = ? AND status = 'active'",
            (active_session_id,),
        ).fetchone()
        return _session_row_to_dict(row)


def _ensure_bin_state_row_conn(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    layer_index: int,
    section_index: int,
    bin_index: int,
) -> int:
    now = time.time()
    conn.execute(
        "INSERT INTO bin_state_current(session_id, layer_index, section_index, bin_index, bin_epoch, piece_count, unique_item_count, last_distributed_at, updated_at) "
        "VALUES(?, ?, ?, ?, 0, 0, 0, NULL, ?) "
        "ON CONFLICT(session_id, layer_index, section_index, bin_index) DO NOTHING",
        (session_id, layer_index, section_index, bin_index, now),
    )
    row = conn.execute(
        "SELECT bin_epoch FROM bin_state_current WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
        (session_id, layer_index, section_index, bin_index),
    ).fetchone()
    return int(row["bin_epoch"]) if row is not None else 0


def record_piece_distribution(piece: dict[str, Any]) -> None:
    if not isinstance(piece, dict):
        return
    piece_uuid = piece.get("uuid")
    destination_bin = piece.get("destination_bin")
    distributed_at = piece.get("distributed_at")
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return
    if not isinstance(destination_bin, (list, tuple)) or len(destination_bin) != 3:
        return
    if not isinstance(distributed_at, (int, float)):
        return

    try:
        layer_index = int(destination_bin[0])
        section_index = int(destination_bin[1])
        bin_index = int(destination_bin[2])
    except (TypeError, ValueError):
        return

    with _bin_state_write_lock, _connection() as conn:
        session = _ensure_active_sorting_session_conn(conn, force_new=False)
        session_id = str(session["id"])
        bin_epoch = _ensure_bin_state_row_conn(
            conn,
            session_id=session_id,
            layer_index=layer_index,
            section_index=section_index,
            bin_index=bin_index,
        )

        item_key = "|".join(
            [
                str(piece.get("part_id") or ""),
                str(piece.get("color_id") or ""),
                str(piece.get("category_id") or ""),
                str(piece.get("classification_status") or ""),
            ]
        )

        cursor = conn.execute(
            "INSERT OR IGNORE INTO piece_events(session_id, piece_uuid, layer_index, section_index, bin_index, bin_epoch, distributed_at, created_at, classified_at, part_id, color_id, color_name, category_id, classification_status, thumbnail, top_image, bottom_image, brickognize_preview_url) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                piece_uuid,
                layer_index,
                section_index,
                bin_index,
                bin_epoch,
                float(distributed_at),
                piece.get("created_at"),
                piece.get("classified_at"),
                piece.get("part_id"),
                piece.get("color_id"),
                piece.get("color_name"),
                piece.get("category_id"),
                piece.get("classification_status"),
                piece.get("thumbnail"),
                piece.get("top_image"),
                piece.get("bottom_image"),
                piece.get("brickognize_preview_url"),
            ),
        )
        if cursor.rowcount == 0:
            conn.commit()
            _refresh_bin_piece_counts(conn)
            return

        conn.execute(
            "INSERT INTO bin_item_aggregates(session_id, layer_index, section_index, bin_index, item_key, part_id, color_id, color_name, category_id, classification_status, count, last_distributed_at, thumbnail, top_image, bottom_image, brickognize_preview_url) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id, layer_index, section_index, bin_index, item_key) DO UPDATE SET "
            "count = bin_item_aggregates.count + 1, "
            "last_distributed_at = CASE WHEN excluded.last_distributed_at > bin_item_aggregates.last_distributed_at OR bin_item_aggregates.last_distributed_at IS NULL THEN excluded.last_distributed_at ELSE bin_item_aggregates.last_distributed_at END, "
            "thumbnail = COALESCE(excluded.thumbnail, bin_item_aggregates.thumbnail), "
            "top_image = COALESCE(excluded.top_image, bin_item_aggregates.top_image), "
            "bottom_image = COALESCE(excluded.bottom_image, bin_item_aggregates.bottom_image), "
            "brickognize_preview_url = COALESCE(excluded.brickognize_preview_url, bin_item_aggregates.brickognize_preview_url)",
            (
                session_id,
                layer_index,
                section_index,
                bin_index,
                item_key,
                piece.get("part_id"),
                piece.get("color_id"),
                piece.get("color_name"),
                piece.get("category_id"),
                piece.get("classification_status"),
                float(distributed_at),
                piece.get("thumbnail"),
                piece.get("top_image"),
                piece.get("bottom_image"),
                piece.get("brickognize_preview_url"),
            ),
        )

        unique_count_row = conn.execute(
            "SELECT COUNT(*) AS n FROM bin_item_aggregates WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
            (session_id, layer_index, section_index, bin_index),
        ).fetchone()
        unique_count = int(unique_count_row["n"]) if unique_count_row is not None else 0
        conn.execute(
            "UPDATE bin_state_current SET piece_count = piece_count + 1, unique_item_count = ?, last_distributed_at = ?, updated_at = ? WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
            (unique_count, float(distributed_at), time.time(), session_id, layer_index, section_index, bin_index),
        )
        conn.commit()
        _refresh_bin_piece_counts(conn)


def get_distributed_part_keys_since(since_ts: float) -> list[tuple[str | None, str | None]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT part_id, color_id FROM piece_events "
            "WHERE distributed_at >= ? AND part_id IS NOT NULL AND part_id != ''",
            (float(since_ts),),
        ).fetchall()
    return [(row[0], row[1]) for row in rows]


def _get_or_create_open_bin_snapshot_conn(conn: sqlite3.Connection, now: float) -> str:
    snapshot_id = _get_meta(conn, _META_KEY_OPEN_BIN_SNAPSHOT_ID)
    if snapshot_id:
        row = conn.execute(
            "SELECT id FROM bin_snapshots WHERE id = ? AND status = 'open'",
            (snapshot_id,),
        ).fetchone()
        if row is not None:
            return str(row["id"])
    snapshot_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO bin_snapshots(id, status, created_at) VALUES(?, 'open', ?)",
        (snapshot_id, now),
    )
    _set_meta(conn, _META_KEY_OPEN_BIN_SNAPSHOT_ID, snapshot_id)
    return snapshot_id


def _category_ids_json_for_bin(
    bin_categories: Any, layer_index: int, section_index: int, bin_index: int
) -> str | None:
    try:
        category_ids = bin_categories[layer_index][section_index][bin_index]
    except (TypeError, IndexError, KeyError):
        return None
    if not isinstance(category_ids, list):
        return None
    return json.dumps([str(c) for c in category_ids])


def _flush_bin_layer_to_snapshot_conn(
    conn: sqlite3.Connection,
    *,
    snapshot_id: str,
    session_id: str,
    layer_index: int,
    section_index: int,
    bin_index: int,
    bin_epoch: int,
    piece_count: int,
    unique_item_count: int,
    category_ids_json: str | None,
    flush_scope: str,
    now: float,
) -> None:
    cursor = conn.execute(
        "INSERT INTO bin_snapshot_layers(snapshot_id, session_id, layer_index, section_index, bin_index, bin_epoch, piece_count, unique_item_count, category_ids_json, flush_scope, flushed_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            snapshot_id,
            session_id,
            layer_index,
            section_index,
            bin_index,
            bin_epoch,
            piece_count,
            unique_item_count,
            category_ids_json,
            flush_scope,
            now,
        ),
    )
    snapshot_layer_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO bin_snapshot_items(snapshot_layer_id, item_key, part_id, color_id, color_name, category_id, classification_status, count, last_distributed_at, thumbnail, top_image, bottom_image, brickognize_preview_url) "
        "SELECT ?, item_key, part_id, color_id, color_name, category_id, classification_status, count, last_distributed_at, thumbnail, top_image, bottom_image, brickognize_preview_url "
        "FROM bin_item_aggregates WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
        (snapshot_layer_id, session_id, layer_index, section_index, bin_index),
    )


def clear_current_session_bins(
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
    bin_categories: Any | None = None,
) -> dict[str, Any]:
    with _bin_state_write_lock, _connection() as conn:
        active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
        if not active_session_id:
            return {"ok": True, "cleared_bins": 0}

        where = ["session_id = ?"]
        params: list[Any] = [active_session_id]
        event_payload: dict[str, Any] = {"scope": scope}
        if scope == "layer":
            where.append("layer_index = ?")
            params.append(layer_index)
            event_payload["layer_index"] = layer_index
        elif scope == "bin":
            where.extend(["layer_index = ?", "section_index = ?", "bin_index = ?"])
            params.extend([layer_index, section_index, bin_index])
            event_payload.update(
                {
                    "layer_index": layer_index,
                    "section_index": section_index,
                    "bin_index": bin_index,
                }
            )

        rows = conn.execute(
            f"SELECT layer_index, section_index, bin_index, bin_epoch, piece_count, unique_item_count FROM bin_state_current WHERE {' AND '.join(where)}",
            tuple(params),
        ).fetchall()

        if scope == "bin" and not rows and layer_index is not None and section_index is not None and bin_index is not None:
            _ensure_bin_state_row_conn(
                conn,
                session_id=active_session_id,
                layer_index=layer_index,
                section_index=section_index,
                bin_index=bin_index,
            )
            rows = conn.execute(
                "SELECT layer_index, section_index, bin_index, bin_epoch, piece_count, unique_item_count FROM bin_state_current WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
                (active_session_id, layer_index, section_index, bin_index),
            ).fetchall()

        cleared_bins = 0
        now = time.time()
        snapshot_id: str | None = None
        for row in rows:
            li = int(row["layer_index"])
            si = int(row["section_index"])
            bi = int(row["bin_index"])
            current_epoch = int(row["bin_epoch"])
            if int(row["piece_count"] or 0) > 0:
                cleared_bins += 1
                if snapshot_id is None:
                    snapshot_id = _get_or_create_open_bin_snapshot_conn(conn, now)
                _flush_bin_layer_to_snapshot_conn(
                    conn,
                    snapshot_id=snapshot_id,
                    session_id=active_session_id,
                    layer_index=li,
                    section_index=si,
                    bin_index=bi,
                    bin_epoch=current_epoch,
                    piece_count=int(row["piece_count"]),
                    unique_item_count=int(row["unique_item_count"] or 0),
                    category_ids_json=_category_ids_json_for_bin(bin_categories, li, si, bi),
                    flush_scope=scope,
                    now=now,
                )
            conn.execute(
                "UPDATE bin_state_current SET bin_epoch = ?, piece_count = 0, unique_item_count = 0, last_distributed_at = NULL, updated_at = ? WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
                (current_epoch + 1, now, active_session_id, li, si, bi),
            )
            conn.execute(
                "DELETE FROM bin_item_aggregates WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
                (active_session_id, li, si, bi),
            )

        closed_snapshot_id: str | None = None
        if scope == "all":
            open_snapshot_id = _get_meta(conn, _META_KEY_OPEN_BIN_SNAPSHOT_ID)
            if open_snapshot_id:
                has_layers = conn.execute(
                    "SELECT 1 FROM bin_snapshot_layers WHERE snapshot_id = ? LIMIT 1",
                    (open_snapshot_id,),
                ).fetchone()
                if has_layers is not None:
                    conn.execute(
                        "UPDATE bin_snapshots SET status = 'closed', closed_at = ?, closed_reason = ? WHERE id = ? AND status = 'open'",
                        (now, "all_cleared", open_snapshot_id),
                    )
                    closed_snapshot_id = open_snapshot_id
                else:
                    conn.execute("DELETE FROM bin_snapshots WHERE id = ?", (open_snapshot_id,))
                conn.execute("DELETE FROM metadata WHERE key = ?", (_META_KEY_OPEN_BIN_SNAPSHOT_ID,))

        conn.execute(
            "INSERT INTO bin_events(session_id, event_type, created_at, layer_index, section_index, bin_index, details_json) VALUES(?, ?, ?, ?, ?, ?, ?)",
            (
                active_session_id,
                f"{scope}_cleared",
                now,
                layer_index,
                section_index,
                bin_index,
                json.dumps(event_payload, sort_keys=True),
            ),
        )
        conn.commit()
        _refresh_bin_piece_counts(conn)
        return {"ok": True, "cleared_bins": cleared_bins, "snapshot_id": closed_snapshot_id}


def get_current_bin_piece_counts() -> dict[tuple[int, int, int], int]:
    cached = _bin_piece_counts
    if cached is None or cached[0] != db.local_state_db_path():
        with _bin_state_write_lock, _connection() as conn:
            _refresh_bin_piece_counts(conn)
        cached = _bin_piece_counts
    return dict(cached[1])


def _refresh_bin_piece_counts(conn: sqlite3.Connection) -> None:
    global _bin_piece_counts
    counts: dict[tuple[int, int, int], int] = {}
    active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
    if active_session_id:
        rows = conn.execute(
            "SELECT layer_index, section_index, bin_index, piece_count FROM bin_state_current WHERE session_id = ?",
            (active_session_id,),
        ).fetchall()
        counts = {
            (int(row["layer_index"]), int(row["section_index"]), int(row["bin_index"])): int(row["piece_count"] or 0)
            for row in rows
        }
    _bin_piece_counts = (db.local_state_db_path(), counts)


def get_current_bin_contents_snapshot() -> dict[str, Any]:
    with _connection() as conn:
        active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
        if not active_session_id:
            return {"session": None, "bins": []}

        session_row = conn.execute(
            "SELECT * FROM sorting_sessions WHERE id = ?",
            (active_session_id,),
        ).fetchone()
        session = _session_row_to_dict(session_row)

        rows = conn.execute(
            "SELECT * FROM bin_state_current WHERE session_id = ? AND piece_count > 0 ORDER BY layer_index, section_index, bin_index",
            (active_session_id,),
        ).fetchall()

        bins: list[dict[str, Any]] = []
        for row in rows:
            li = int(row["layer_index"])
            si = int(row["section_index"])
            bi = int(row["bin_index"])
            epoch = int(row["bin_epoch"])
            items = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM bin_item_aggregates WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ? ORDER BY count DESC, last_distributed_at DESC",
                    (active_session_id, li, si, bi),
                ).fetchall()
            ]
            recent_pieces = [
                {
                    "uuid": piece["piece_uuid"],
                    "part_id": piece["part_id"],
                    "color_id": piece["color_id"],
                    "color_name": piece["color_name"],
                    "category_id": piece["category_id"],
                    "classification_status": piece["classification_status"],
                    "distributed_at": piece["distributed_at"],
                    "thumbnail": piece["thumbnail"],
                    "top_image": piece["top_image"],
                    "bottom_image": piece["bottom_image"],
                    "brickognize_preview_url": piece["brickognize_preview_url"],
                }
                for piece in conn.execute(
                    "SELECT * FROM piece_events WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ? AND bin_epoch = ? ORDER BY distributed_at DESC LIMIT 8",
                    (active_session_id, li, si, bi, epoch),
                ).fetchall()
            ]
            bins.append(
                {
                    "bin_key": f"{li}:{si}:{bi}",
                    "layer_index": li,
                    "section_index": si,
                    "bin_index": bi,
                    "piece_count": int(row["piece_count"]),
                    "unique_item_count": int(row["unique_item_count"]),
                    "last_distributed_at": row["last_distributed_at"],
                    "items": items,
                    "recent_pieces": recent_pieces,
                }
            )

        return {"session": session, "bins": bins}


def get_current_bin_contents_version() -> str:
    with _connection() as conn:
        active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
        if not active_session_id:
            return "none"
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(MAX(updated_at), 0) AS max_updated, "
            "COALESCE(SUM(bin_epoch), 0) AS epochs, COALESCE(SUM(piece_count), 0) AS pieces "
            "FROM bin_state_current WHERE session_id = ?",
            (active_session_id,),
        ).fetchone()
        return (
            f"{active_session_id}:{int(row['n'])}:{float(row['max_updated'])}:"
            f"{int(row['epochs'])}:{int(row['pieces'])}"
        )


def list_bin_snapshots() -> list[dict[str, Any]]:
    with _connection() as conn:
        rows = conn.execute(
            "SELECT s.id, s.status, s.label, s.created_at, s.closed_at, s.closed_reason, "
            "COUNT(l.id) AS layer_count, "
            "COUNT(DISTINCT l.layer_index || ':' || l.section_index || ':' || l.bin_index) AS bin_count, "
            "COALESCE(SUM(l.piece_count), 0) AS piece_count "
            "FROM bin_snapshots s LEFT JOIN bin_snapshot_layers l ON l.snapshot_id = s.id "
            "GROUP BY s.id ORDER BY s.created_at DESC",
        ).fetchall()
        return [dict(row) for row in rows]


def get_bin_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    with _connection() as conn:
        snapshot_row = conn.execute(
            "SELECT * FROM bin_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if snapshot_row is None:
            return None

        layer_rows = conn.execute(
            "SELECT * FROM bin_snapshot_layers WHERE snapshot_id = ? ORDER BY layer_index, section_index, bin_index, flushed_at",
            (snapshot_id,),
        ).fetchall()

        layers: list[dict[str, Any]] = []
        for row in layer_rows:
            layer = dict(row)
            raw_category_ids = layer.pop("category_ids_json", None)
            try:
                layer["category_ids"] = json.loads(raw_category_ids) if raw_category_ids else []
            except (TypeError, ValueError):
                layer["category_ids"] = []
            layer["items"] = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM bin_snapshot_items WHERE snapshot_layer_id = ? ORDER BY count DESC, last_distributed_at DESC",
                    (int(layer["id"]),),
                ).fetchall()
            ]
            layers.append(layer)

        snapshot = dict(snapshot_row)
        snapshot["layers"] = layers
        snapshot["piece_count"] = sum(int(l["piece_count"] or 0) for l in layers)
        return snapshot


def get_bin_snapshot_pieces(snapshot_id: str) -> list[dict[str, Any]] | None:
    with _connection() as conn:
        snapshot_row = conn.execute(
            "SELECT id FROM bin_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        if snapshot_row is None:
            return None
        # Joining on session_id too: (bin, epoch) alone can collide with stale
        # piece_events from unrelated past sessions (seen on real DBs), which
        # inflates the piece list well past the bin's counter. The cost is that
        # pieces logged under a pre-carry-forward session are omitted from the
        # per-piece list; bin_snapshot_items stays the authoritative content record.
        rows = conn.execute(
            "SELECT l.id AS snapshot_layer_id, l.flushed_at, l.flush_scope, "
            f"{_PIECE_COLUMNS}"
            "FROM bin_snapshot_layers l "
            "JOIN piece_events p ON p.session_id = l.session_id AND p.layer_index = l.layer_index "
            "AND p.section_index = l.section_index AND p.bin_index = l.bin_index "
            "AND p.bin_epoch = l.bin_epoch AND p.distributed_at <= l.flushed_at "
            "LEFT JOIN sorting_sessions s ON s.id = p.session_id "
            "WHERE l.snapshot_id = ? "
            "GROUP BY p.piece_uuid "
            "ORDER BY l.layer_index, l.section_index, l.bin_index, p.distributed_at",
            (snapshot_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def get_current_bin_pieces() -> list[dict[str, Any]]:
    with _connection() as conn:
        active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
        if not active_session_id:
            return []
        rows = conn.execute(
            f"SELECT {_PIECE_COLUMNS}"
            "FROM bin_state_current b "
            "JOIN piece_events p ON p.session_id = b.session_id AND p.layer_index = b.layer_index "
            "AND p.section_index = b.section_index AND p.bin_index = b.bin_index AND p.bin_epoch = b.bin_epoch "
            "LEFT JOIN sorting_sessions s ON s.id = p.session_id "
            "WHERE b.session_id = ? AND b.piece_count > 0 "
            "GROUP BY p.piece_uuid "
            "ORDER BY b.layer_index, b.section_index, b.bin_index, p.distributed_at",
            (active_session_id,),
        ).fetchall()
        return [dict(row) for row in rows]
