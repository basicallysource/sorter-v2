from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any

import db
import local_state
from sorting_profile import profileSummary

# The bin layout the machine runs, and the layouts saved to switch between.
# The live layout is three key/value state entries: the layers (geometry,
# enabled flags, each layer's servo channel), the categories assigned to each
# bin, and the bins flagged not-in-inventory. A saved layout (bin_layouts) is a
# snapshot of all three, tied to a sorting profile. Servo calibration is kept
# per PWM channel ({channel_id: {"open": int, "closed": int}}), not per layer,
# so switching or editing layouts never touches it.
#
# Every layout the machine ran is kept in bin_layout_history: a row each time
# the live layout or the profile it sorts by changes, with what the profile
# called each category then. So what a bin was assigned at any moment (in any
# sorting run) can be told after the layout moved on. Rows never change; they
# sync to Hive by id (data type bin_layouts).

_STATE_KEY_BIN_LAYOUT = "bin_layout"
_STATE_KEY_BIN_CATEGORIES = "bin_categories"
_STATE_KEY_NOT_IN_INVENTORY_BINS = "not_in_inventory_bins"
_STATE_KEY_SERVO_CHANNEL_CALIBRATION = "servo_channel_calibration"
# The entries a layout is made of: writing one of them is a new layout.
_LAYOUT_KEYS = (_STATE_KEY_BIN_LAYOUT, _STATE_KEY_BIN_CATEGORIES, _STATE_KEY_NOT_IN_INVENTORY_BINS)
# What a history row says of the profile, from its sync state.
_PROFILE_FIELDS = ("profile_id", "profile_name", "version_number", "version_label", "artifact_hash")

_BIN_LAYOUT_COLUMNS = (
    "id, name, profile_id, profile_source, layout_json, created_at, updated_at, is_active"
)


def _createTables(conn: sqlite3.Connection) -> None:
    local_state.create_tables(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bin_layouts ("
        "id TEXT PRIMARY KEY, "
        "name TEXT NOT NULL, "
        "profile_id TEXT, "
        "profile_source TEXT, "
        "layout_json TEXT NOT NULL, "
        "created_at REAL NOT NULL, "
        "updated_at REAL NOT NULL, "
        "is_active INTEGER NOT NULL DEFAULT 0"
        ")"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bin_layout_history ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "changed_at REAL NOT NULL, "
        # sha256 of layout_json: a write that changes nothing adds no row.
        "content_hash TEXT NOT NULL, "
        "layout_json TEXT NOT NULL"
        ")"
    )
    _migrate_servo_channels_and_bin_layouts(conn)
    # The layout running when this table first appears is its first row.
    _record_history(conn)


def _connection(op: str | None = None):
    return db.connect(_createTables, op=op)


def _read(key: str) -> Any | None:
    with _connection(f"bin_layout_store._read({key})") as conn:
        return local_state.read_entry(conn, key)


def _write(key: str, value: Any | None) -> None:
    with _connection(f"bin_layout_store._write({key})") as conn:
        local_state.write_entry(conn, key, value)
        if key in _LAYOUT_KEYS:
            _record_history(conn)
        conn.commit()


def _category_ids(categories: Any) -> set[str]:
    return {
        str(category_id)
        for layer in (categories if isinstance(categories, list) else [])
        if isinstance(layer, list)
        for section in layer
        if isinstance(section, list)
        for bin_categories in section
        if isinstance(bin_categories, list)
        for category_id in bin_categories
    }


def _category_names(categories: Any) -> dict[str, str]:
    """What the active sorting profile calls each category the layout assigns,
    as the Bins page names them; nothing for a category it does not name, or
    when no profile is loaded. The profile's summary is cached per file, and
    the runtime's own parse fills it, so this reads no file on the hot path."""
    ids = _category_ids(categories)
    if not ids:
        return {}
    from server import shared_state

    path = getattr(shared_state.gc_ref, "sorting_profile_path", None)
    if not path:
        return {}
    try:
        meta = profileSummary(path).get("categories") or {}
    except (OSError, ValueError):
        return {}
    names: dict[str, str] = {}
    for category_id in sorted(ids):
        entry = meta.get(category_id) if isinstance(meta, dict) else None
        name = entry.get("name") if isinstance(entry, dict) else None
        if isinstance(name, str) and name.strip():
            names[category_id] = name.strip()
    return names


def _record_history(conn: sqlite3.Connection) -> None:
    """Add the live layout to bin_layout_history, in the caller's transaction,
    unless the last row already is this layout."""
    bin_layout = local_state.read_entry(conn, _STATE_KEY_BIN_LAYOUT)
    layers = bin_layout.get("layers") if isinstance(bin_layout, dict) else None
    if not isinstance(layers, list):
        return
    categories = local_state.read_entry(conn, _STATE_KEY_BIN_CATEGORIES)
    sync = local_state.read_entry(conn, local_state.STATE_KEY_SORTING_PROFILE_SYNC)
    sync = sync if isinstance(sync, dict) else {}
    entry = _layout_snapshot(layers, categories, local_state.read_entry(conn, _STATE_KEY_NOT_IN_INVENTORY_BINS))
    entry["profile"] = {field: sync.get(field) for field in _PROFILE_FIELDS}
    entry["category_names"] = _category_names(categories)
    content = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(content.encode()).hexdigest()
    last = conn.execute("SELECT content_hash FROM bin_layout_history ORDER BY id DESC LIMIT 1").fetchone()
    if last is not None and last["content_hash"] == digest:
        return
    conn.execute(
        "INSERT INTO bin_layout_history (changed_at, content_hash, layout_json) VALUES (?, ?, ?)",
        (time.time(), digest, content),
    )


def listHistoryAfter(after_id: int, limit: int) -> list[dict[str, Any]]:
    """The layouts the machine ran after the row `after_id`, oldest first:
    {id, changed_at, layout}, where layout is a saved layout's snapshot (layers,
    bin_categories, not_in_inventory_bins) with the profile it sorted by and
    category_names."""
    with _connection("bin_layout_store.listHistoryAfter") as conn:
        rows = conn.execute(
            "SELECT id, changed_at, layout_json FROM bin_layout_history WHERE id > ? ORDER BY id LIMIT ?",
            (int(after_id), int(limit)),
        ).fetchall()
    return [{"id": row["id"], "changed_at": row["changed_at"], "layout": json.loads(row["layout_json"])} for row in rows]


def maxHistoryId() -> int:
    with _connection("bin_layout_store.maxHistoryId") as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) AS n FROM bin_layout_history").fetchone()
    return int(row["n"])


def _layout_snapshot(layers: Any, bin_categories: Any, not_in_inventory_bins: Any) -> dict[str, Any]:
    return {
        "layers": [
            {
                "sections": layer.get("sections"),
                "enabled": layer.get("enabled", True),
                "servo_channel_id": layer.get("servo_channel_id"),
                "max_pieces_per_bin": layer.get("max_pieces_per_bin"),
                "max_dimension_mm": layer.get("max_dimension_mm"),
                "section_enabled": layer.get("section_enabled"),
            }
            for layer in layers
            if isinstance(layer, dict)
        ],
        "bin_categories": bin_categories,
        "not_in_inventory_bins": not_in_inventory_bins,
    }


def _migrate_servo_channels_and_bin_layouts(conn: sqlite3.Connection) -> None:
    """Decouple servo calibration from the bin layout (2026-06-27). Moves the
    per-layer servo angles into a per-channel calibration store, stamps each
    layer with a servo_channel_id (defaults to the layer index — the historical
    1:1 mapping), and snapshots the current layout into the bin_layouts presets
    table as the active record. Idempotent. Runs once per start and after every
    bin layout write: layers the layout editor adds carry no servo_channel_id,
    and this is what stamps one on them."""
    bin_layout = local_state.read_entry(conn, _STATE_KEY_BIN_LAYOUT)
    calibration = local_state.read_entry(conn, _STATE_KEY_SERVO_CHANNEL_CALIBRATION)
    if not isinstance(calibration, dict):
        calibration = {}

    layers = bin_layout.get("layers") if isinstance(bin_layout, dict) else None
    if isinstance(layers, list):
        cal_changed = False
        layout_changed = False
        for index, layer in enumerate(layers):
            if not isinstance(layer, dict):
                continue
            channel = layer.get("servo_channel_id")
            if not isinstance(channel, int):
                channel = index
                layer["servo_channel_id"] = channel
                layout_changed = True
            key = str(channel)
            if key not in calibration:
                open_angle = layer.get("servo_open_angle")
                closed_angle = layer.get("servo_closed_angle")
                if isinstance(open_angle, int) or isinstance(closed_angle, int):
                    calibration[key] = {
                        "open": open_angle if isinstance(open_angle, int) else None,
                        "closed": closed_angle if isinstance(closed_angle, int) else None,
                    }
                    cal_changed = True
        if cal_changed:
            local_state.write_entry(conn, _STATE_KEY_SERVO_CHANNEL_CALIBRATION, calibration)
        if layout_changed:
            local_state.write_entry(conn, _STATE_KEY_BIN_LAYOUT, bin_layout)

    row = conn.execute("SELECT COUNT(*) AS n FROM bin_layouts").fetchone()
    if row is not None and int(row["n"]) == 0 and isinstance(layers, list):
        categories = local_state.read_entry(conn, _STATE_KEY_BIN_CATEGORIES)
        not_in_inventory = local_state.read_entry(conn, _STATE_KEY_NOT_IN_INVENTORY_BINS)
        sync = local_state.read_entry(conn, local_state.STATE_KEY_SORTING_PROFILE_SYNC)
        sync = sync if isinstance(sync, dict) else {}
        snapshot = _layout_snapshot(layers, categories, not_in_inventory)
        profile_name = sync.get("profile_name")
        name = f"{profile_name} layout" if profile_name else "Current layout"
        now = time.time()
        conn.execute(
            f"INSERT INTO bin_layouts({_BIN_LAYOUT_COLUMNS}) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()), name,
                sync.get("profile_id") or sync.get("local_filename"),
                sync.get("source"),
                json.dumps(snapshot), now, now, 1,
            ),
        )


def get_bin_layout() -> dict[str, Any] | None:
    value = _read(_STATE_KEY_BIN_LAYOUT)
    return value if isinstance(value, dict) else None


def set_bin_layout(layout: dict[str, Any] | None) -> None:
    with _connection("bin_layout_store.set_bin_layout") as conn:
        local_state.write_entry(conn, _STATE_KEY_BIN_LAYOUT, dict(layout) if layout is not None else None)
        _migrate_servo_channels_and_bin_layouts(conn)
        _record_history(conn)
        conn.commit()


def get_bin_categories() -> list[list[list[list[str]]]] | None:
    value = _read(_STATE_KEY_BIN_CATEGORIES)
    return value if isinstance(value, list) else None


def set_bin_categories(categories: list[list[list[list[str]]]]) -> None:
    _write(_STATE_KEY_BIN_CATEGORIES, categories)


def get_not_in_inventory_bins() -> list[list[list[bool]]] | None:
    value = _read(_STATE_KEY_NOT_IN_INVENTORY_BINS)
    return value if isinstance(value, list) else None


def set_not_in_inventory_bins(flags: list[list[list[bool]]]) -> None:
    _write(_STATE_KEY_NOT_IN_INVENTORY_BINS, flags)


def current_layout_snapshot() -> dict[str, Any]:
    """The live layout as a saved layout stores it: no servo angles (those are
    per channel). The same builder as the snapshot the migration seeds, so that
    record does not read as changed."""
    bin_layout = get_bin_layout() or {}
    return _layout_snapshot(
        bin_layout.get("layers", []), get_bin_categories(), get_not_in_inventory_bins()
    )


def get_servo_channel_calibration() -> dict[str, dict[str, Any]]:
    value = _read(_STATE_KEY_SERVO_CHANNEL_CALIBRATION)
    return value if isinstance(value, dict) else {}


def set_servo_channel_angle(channel_id: Any, which: str, angle: int | None) -> None:
    # which is "open" or "closed"; angle None clears that side
    calibration = get_servo_channel_calibration()
    key = str(channel_id)
    entry = dict(calibration.get(key) or {})
    entry[which] = angle
    calibration[key] = entry
    _write(_STATE_KEY_SERVO_CHANNEL_CALIBRATION, calibration)


def _bin_layout_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        layout = json.loads(row["layout_json"])
    except (TypeError, ValueError):
        layout = None
    return {
        "id": row["id"],
        "name": row["name"],
        "profile_id": row["profile_id"],
        "profile_source": row["profile_source"],
        "layout": layout,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "is_active": bool(row["is_active"]),
    }


def count_bin_layouts() -> int:
    with _connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM bin_layouts").fetchone()["n"])


def list_bin_layouts(profile_id: str | None = None) -> list[dict[str, Any]]:
    with _connection() as conn:
        if profile_id is not None:
            rows = conn.execute(
                f"SELECT {_BIN_LAYOUT_COLUMNS} FROM bin_layouts WHERE profile_id = ? "
                "ORDER BY updated_at DESC",
                (profile_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {_BIN_LAYOUT_COLUMNS} FROM bin_layouts ORDER BY updated_at DESC"
            ).fetchall()
    return [_bin_layout_row_to_dict(row) for row in rows]


def get_bin_layout_record(layout_id: str) -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(
            f"SELECT {_BIN_LAYOUT_COLUMNS} FROM bin_layouts WHERE id = ?",
            (layout_id,),
        ).fetchone()
    return _bin_layout_row_to_dict(row) if row is not None else None


def get_active_bin_layout_record() -> dict[str, Any] | None:
    with _connection() as conn:
        row = conn.execute(
            f"SELECT {_BIN_LAYOUT_COLUMNS} FROM bin_layouts WHERE is_active = 1 "
            "ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
    return _bin_layout_row_to_dict(row) if row is not None else None


def create_bin_layout(
    *,
    name: str,
    layout: dict[str, Any],
    profile_id: str | None = None,
    profile_source: str | None = None,
    make_active: bool = False,
    layout_id: str | None = None,
) -> dict[str, Any]:
    lid = layout_id or str(uuid.uuid4())
    now = time.time()
    with _connection() as conn:
        if make_active:
            conn.execute("UPDATE bin_layouts SET is_active = 0")
        conn.execute(
            f"INSERT INTO bin_layouts({_BIN_LAYOUT_COLUMNS}) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (lid, name, profile_id, profile_source, json.dumps(layout), now, now,
             1 if make_active else 0),
        )
        conn.commit()
    record = get_bin_layout_record(lid)
    assert record is not None
    return record


def update_bin_layout(
    layout_id: str, *, name: str | None = None, layout: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name = ?")
        params.append(name)
    if layout is not None:
        sets.append("layout_json = ?")
        params.append(json.dumps(layout))
    if not sets:
        return get_bin_layout_record(layout_id)
    sets.append("updated_at = ?")
    params.append(time.time())
    params.append(layout_id)
    with _connection() as conn:
        conn.execute(f"UPDATE bin_layouts SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
    return get_bin_layout_record(layout_id)


def set_active_bin_layout(layout_id: str) -> None:
    with _connection() as conn:
        conn.execute("UPDATE bin_layouts SET is_active = 0")
        conn.execute("UPDATE bin_layouts SET is_active = 1 WHERE id = ?", (layout_id,))
        conn.commit()


def delete_bin_layout(layout_id: str) -> None:
    with _connection() as conn:
        conn.execute("DELETE FROM bin_layouts WHERE id = ?", (layout_id,))
        conn.commit()
