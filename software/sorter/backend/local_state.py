from __future__ import annotations

from contextlib import contextmanager
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from toml_config import loadTomlFile

SOFTWARE_DIR = Path(__file__).resolve().parent

_STATE_INIT_LOCK = threading.Lock()
_SCHEMA_VERSION = 5

_STATE_KEY_MACHINE_ID = "machine_id"
_STATE_KEY_STEPPER_POSITIONS = "stepper_positions"
_STATE_KEY_SERVO_POSITIONS = "servo_positions"
_STATE_KEY_BIN_CATEGORIES = "bin_categories"
_STATE_KEY_CHANNEL_POLYGONS = "channel_polygons"
_STATE_KEY_CLASSIFICATION_POLYGONS = "classification_polygons"
_STATE_KEY_CLASSIFICATION_TRAINING = "classification_training"
_STATE_KEY_HIVE = "hive"
_STATE_KEY_SORTING_PROFILE_SYNC = "sorting_profile_sync"
_STATE_KEY_API_KEYS = "api_keys"
_STATE_KEY_SERVO_STATES = "servo_states"
_STATE_KEY_SET_PROGRESS = "set_progress"
_STATE_KEY_RECENT_KNOWN_OBJECTS = "recent_known_objects"
_STATE_KEY_UI_THEME_COLOR_ID = "ui_theme_color_id"
_STATE_KEY_BIN_LAYOUT = "bin_layout"
_STATE_KEY_PERSISTENT_TRACKER_IGNORED_REGIONS_PREFIX = "persistent_tracker_ignored_regions:"

_META_KEY_ACTIVE_SORTING_SESSION_ID = "active_sorting_session_id"

_RECENT_KNOWN_OBJECTS_LIMIT = 10


def local_state_db_path() -> Path:
    env_path = os.getenv("LOCAL_STATE_DB_PATH")
    if isinstance(env_path, str) and env_path.strip():
        return Path(env_path).expanduser()

    return SOFTWARE_DIR / "local_state.sqlite"


def _legacy_machine_params_path() -> Path:
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if isinstance(params_path, str) and params_path.strip():
        return Path(params_path).expanduser().resolve()
    return SOFTWARE_DIR / "machine_params.toml"


def _legacy_state_dir() -> Path:
    return _legacy_machine_params_path().parent


def _legacy_data_path() -> Path:
    return _legacy_state_dir() / "data.json"


def _legacy_polygons_path() -> Path:
    return _legacy_state_dir() / "polygons.json"


def _legacy_servo_states_path() -> Path:
    return _legacy_state_dir() / "servo_states.json"


def _legacy_set_progress_path() -> Path:
    return _legacy_state_dir() / "blob" / "set_progress.json"


def _connect() -> sqlite3.Connection:
    db_path = local_state_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        os.chmod(db_path, 0o600)
    except OSError:
        pass
    return conn


@contextmanager
def _connection() -> sqlite3.Connection:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def _read_json_file(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _read_machine_params() -> dict[str, Any]:
    path = _legacy_machine_params_path()
    if not path.exists():
        return {}
    data = loadTomlFile(path)
    return data if isinstance(data, dict) else {}


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


def _get_json(conn: sqlite3.Connection, key: str) -> Any | None:
    row = conn.execute(
        "SELECT json_value FROM state_entries WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(str(row["json_value"]))


def _set_json(conn: sqlite3.Connection, key: str, value: Any) -> None:
    payload = json.dumps(value, sort_keys=True)
    conn.execute(
        "INSERT INTO state_entries(key, json_value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET json_value = excluded.json_value, updated_at = excluded.updated_at",
        (key, payload, time.time()),
    )


def _delete_key(conn: sqlite3.Connection, key: str) -> None:
    conn.execute("DELETE FROM state_entries WHERE key = ?", (key,))


def _normalize_string_dict(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if isinstance(key, str) and value is not None
    }


def _normalize_hive_target(raw: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    url = raw.get("url")
    api_token = raw.get("api_token")
    if not isinstance(url, str) or not url.strip():
        return None
    if not isinstance(api_token, str) or not api_token.strip():
        return None

    target_id = raw.get("id")
    name = raw.get("name")
    machine_id = raw.get("machine_id")

    target = {
        "id": target_id.strip() if isinstance(target_id, str) and target_id.strip() else f"target-{index + 1}",
        "name": name.strip() if isinstance(name, str) and name.strip() else url.strip().rstrip("/"),
        "url": url.strip().rstrip("/"),
        "api_token": api_token.strip(),
        "enabled": bool(raw.get("enabled", True)),
    }
    if isinstance(machine_id, str) and machine_id.strip():
        target["machine_id"] = machine_id.strip()
    return target


def _normalize_hive_config(raw: Any) -> dict[str, Any]:
    raw_targets = raw.get("targets") if isinstance(raw, dict) else None
    normalized_targets: list[dict[str, Any]] = []
    if isinstance(raw_targets, list):
        for index, item in enumerate(raw_targets):
            target = _normalize_hive_target(item, index)
            if target is not None:
                normalized_targets.append(target)
    elif isinstance(raw, dict):
        legacy_target = _normalize_hive_target(raw, 0)
        if legacy_target is not None:
            normalized_targets.append(legacy_target)
    return {"targets": normalized_targets}


def _migrate_state_key(conn: sqlite3.Connection, key: str, value: Any) -> None:
    if value is None or _get_json(conn, key) is not None:
        return
    _set_json(conn, key, value)


def _migrate_from_machine_params(conn: sqlite3.Connection) -> None:
    config = _read_machine_params()
    _migrate_state_key(conn, _STATE_KEY_CLASSIFICATION_TRAINING, config.get("classification_training"))
    _migrate_state_key(conn, _STATE_KEY_API_KEYS, _normalize_string_dict(config.get("api_keys")))
    _migrate_state_key(conn, _STATE_KEY_HIVE, _normalize_hive_config(config.get("hive") or config.get("sorthive")))
    _migrate_state_key(conn, _STATE_KEY_SORTING_PROFILE_SYNC, config.get("sorting_profile_sync"))


def _migrate_from_polygons_json(conn: sqlite3.Connection) -> None:
    polygons = _read_json_file(_legacy_polygons_path())
    if not isinstance(polygons, dict):
        return
    _migrate_state_key(conn, _STATE_KEY_CHANNEL_POLYGONS, polygons.get("channel_polygons"))
    _migrate_state_key(conn, _STATE_KEY_CLASSIFICATION_POLYGONS, polygons.get("classification_polygons"))


def _migrate_from_data_json(conn: sqlite3.Connection) -> None:
    data = _read_json_file(_legacy_data_path())
    if not isinstance(data, dict):
        return

    _migrate_state_key(conn, _STATE_KEY_MACHINE_ID, data.get("machine_id"))
    _migrate_state_key(conn, _STATE_KEY_STEPPER_POSITIONS, data.get("stepper_positions"))
    _migrate_state_key(conn, _STATE_KEY_SERVO_POSITIONS, data.get("servo_positions"))
    _migrate_state_key(conn, _STATE_KEY_BIN_CATEGORIES, data.get("bin_categories"))
    _migrate_state_key(conn, _STATE_KEY_CHANNEL_POLYGONS, data.get("channel_polygons"))
    _migrate_state_key(conn, _STATE_KEY_CLASSIFICATION_POLYGONS, data.get("classification_polygons"))
    _migrate_state_key(conn, _STATE_KEY_CLASSIFICATION_TRAINING, data.get("classification_training"))
    _migrate_state_key(conn, _STATE_KEY_API_KEYS, _normalize_string_dict(data.get("api_keys")))


def _migrate_misc_state_files(conn: sqlite3.Connection) -> None:
    servo_states = _read_json_file(_legacy_servo_states_path())
    if isinstance(servo_states, dict):
        _migrate_state_key(conn, _STATE_KEY_SERVO_STATES, servo_states)

    set_progress = _read_json_file(_legacy_set_progress_path())
    if isinstance(set_progress, dict):
        _migrate_state_key(conn, _STATE_KEY_SET_PROGRESS, set_progress)


def _cleanup_machine_params_runtime_sections(conn: sqlite3.Connection) -> None:
    path = _legacy_machine_params_path()
    if not path.exists():
        return

    try:
        original = path.read_text(encoding="utf-8")
    except OSError:
        return

    runtime_roots = {
        _STATE_KEY_CLASSIFICATION_TRAINING,
        _STATE_KEY_API_KEYS,
        _STATE_KEY_HIVE,
        "sorthive",
        _STATE_KEY_SORTING_PROFILE_SYNC,
    }

    cleaned_lines: list[str] = []
    skipping_block = False

    for line in original.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            header = stripped.strip("[]").strip()
            table_path = header.split(".", 1)[0].strip()
            skipping_block = table_path in runtime_roots
            if skipping_block:
                continue

        if not skipping_block:
            cleaned_lines.append(line)

    cleaned = "".join(cleaned_lines)
    if cleaned == original:
        return

    try:
        path.write_text(cleaned, encoding="utf-8")
    except OSError:
        return


def _migrate_renamed_state_keys(conn: sqlite3.Connection) -> None:
    """Rename legacy state keys from the SortHive→Hive rename (2026-04-09)."""
    old_key = "sorthive"
    new_key = _STATE_KEY_HIVE
    if old_key == new_key:
        return
    old_value = _get_json(conn, old_key)
    if old_value is not None and _get_json(conn, new_key) is None:
        _set_json(conn, new_key, old_value)
        conn.execute("DELETE FROM state_entries WHERE key = ?", (old_key,))


def initialize_local_state() -> None:
    with _STATE_INIT_LOCK:
        with _connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata ("
                "key TEXT PRIMARY KEY, "
                "value TEXT NOT NULL"
                ")"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS state_entries ("
                "key TEXT PRIMARY KEY, "
                "json_value TEXT NOT NULL, "
                "updated_at REAL NOT NULL"
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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS piece_dossiers ("
                "piece_uuid TEXT PRIMARY KEY, "
                "session_id TEXT NOT NULL, "
                "tracked_global_id INTEGER, "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL, "
                "last_event_at REAL NOT NULL, "
                "stage TEXT NOT NULL, "
                "classification_status TEXT NOT NULL, "
                "first_carousel_seen_ts REAL, "
                "classification_channel_zone_center_deg REAL, "
                "distributed_at REAL, "
                "payload_json TEXT NOT NULL, "
                "FOREIGN KEY(session_id) REFERENCES sorting_sessions(id) ON DELETE CASCADE"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS piece_dossiers_session_last_event_idx "
                "ON piece_dossiers(session_id, last_event_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS piece_dossiers_session_stage_idx "
                "ON piece_dossiers(session_id, stage, distributed_at DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS piece_dossiers_tracked_gid_idx "
                "ON piece_dossiers(tracked_global_id)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS piece_segments ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "piece_uuid TEXT NOT NULL, "
                "session_id TEXT NOT NULL, "
                "role TEXT NOT NULL, "
                "tracked_global_id INTEGER, "
                "sequence INTEGER NOT NULL, "
                "first_seen_ts REAL NOT NULL, "
                "last_seen_ts REAL NOT NULL, "
                "hit_count INTEGER NOT NULL DEFAULT 0, "
                "channel_center_x REAL, "
                "channel_center_y REAL, "
                "channel_radius_inner REAL, "
                "channel_radius_outer REAL, "
                "snapshot_width INTEGER, "
                "snapshot_height INTEGER, "
                "snapshot_path TEXT, "
                "path_json TEXT NOT NULL, "
                "sector_snapshots_json TEXT NOT NULL, "
                "recognize_result_json TEXT, "
                "created_at REAL NOT NULL, "
                "FOREIGN KEY(session_id) REFERENCES sorting_sessions(id) ON DELETE CASCADE, "
                "FOREIGN KEY(piece_uuid) REFERENCES piece_dossiers(piece_uuid) ON DELETE CASCADE"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS piece_segments_piece_seq_idx "
                "ON piece_segments(piece_uuid, sequence)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS piece_segments_session_role_idx "
                "ON piece_segments(session_id, role, first_seen_ts DESC)"
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
            schema_version = _get_meta(conn, "schema_version")
            if schema_version != str(_SCHEMA_VERSION):
                _set_meta(conn, "schema_version", str(_SCHEMA_VERSION))

            _migrate_from_machine_params(conn)
            _migrate_from_polygons_json(conn)
            _migrate_from_data_json(conn)
            _migrate_misc_state_files(conn)
            _cleanup_machine_params_runtime_sections(conn)
            _migrate_renamed_state_keys(conn)
            conn.commit()


def _read_state(key: str) -> Any | None:
    initialize_local_state()
    with _connection() as conn:
        return _get_json(conn, key)


def _write_state(key: str, value: Any | None) -> None:
    initialize_local_state()
    with _connection() as conn:
        if value is None:
            _delete_key(conn, key)
        else:
            _set_json(conn, key, value)
        conn.commit()


def get_machine_id() -> str | None:
    value = _read_state(_STATE_KEY_MACHINE_ID)
    return value if isinstance(value, str) and value.strip() else None


def set_machine_id(machine_id: str) -> None:
    normalized = machine_id.strip() if isinstance(machine_id, str) else ""
    if not normalized:
        raise ValueError("machine_id must be a non-empty string")
    _write_state(_STATE_KEY_MACHINE_ID, normalized)


def get_stepper_positions() -> dict[str, int]:
    value = _read_state(_STATE_KEY_STEPPER_POSITIONS)
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for name, position in value.items():
        if isinstance(name, str) and isinstance(position, int) and not isinstance(position, bool):
            result[name] = position
    return result


def set_stepper_positions(positions: dict[str, int]) -> None:
    _write_state(_STATE_KEY_STEPPER_POSITIONS, get_sanitized_int_mapping(positions))


def get_servo_positions() -> dict[str, int]:
    value = _read_state(_STATE_KEY_SERVO_POSITIONS)
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for name, angle in value.items():
        if isinstance(name, str) and isinstance(angle, int) and not isinstance(angle, bool):
            result[name] = angle
    return result


def set_servo_positions(positions: dict[str, int]) -> None:
    _write_state(_STATE_KEY_SERVO_POSITIONS, get_sanitized_int_mapping(positions))


def get_sanitized_int_mapping(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool):
            result[key] = value
    return result


def get_bin_categories() -> list[list[list[list[str]]]] | None:
    value = _read_state(_STATE_KEY_BIN_CATEGORIES)
    return value if isinstance(value, list) else None


def set_bin_categories(categories: list[list[list[list[str]]]]) -> None:
    _write_state(_STATE_KEY_BIN_CATEGORIES, categories)


def get_channel_polygons() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_CHANNEL_POLYGONS)
    return value if isinstance(value, dict) else None


def set_channel_polygons(polygons: dict[str, Any]) -> None:
    _write_state(_STATE_KEY_CHANNEL_POLYGONS, dict(polygons))


def get_classification_polygons() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_CLASSIFICATION_POLYGONS)
    return value if isinstance(value, dict) else None


def set_classification_polygons(polygons: dict[str, Any]) -> None:
    _write_state(_STATE_KEY_CLASSIFICATION_POLYGONS, dict(polygons))


def get_classification_training_state() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_CLASSIFICATION_TRAINING)
    return value if isinstance(value, dict) else None


def set_classification_training_state(state: dict[str, Any] | None) -> None:
    normalized = None
    if isinstance(state, dict):
        normalized = {
            key: value
            for key, value in state.items()
            if isinstance(key, str) and value is not None
        }
    _write_state(_STATE_KEY_CLASSIFICATION_TRAINING, normalized)


def get_hive_config() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_HIVE)
    if not isinstance(value, dict):
        return {"targets": []}

    from secrets_crypto import decrypt_str, is_encrypted

    config = _normalize_hive_config(value)
    had_plaintext_token = False
    for target in config.get("targets", []):
        token = target.get("api_token")
        if isinstance(token, str) and token:
            if not is_encrypted(token):
                had_plaintext_token = True
            target["api_token"] = decrypt_str(token)

    # Migrate legacy plaintext tokens to encrypted form on first read.
    if had_plaintext_token and config.get("targets"):
        set_hive_config(config)

    return config


def set_hive_config(config: dict[str, Any]) -> None:
    from secrets_crypto import encrypt_str

    normalized = _normalize_hive_config(config)
    for target in normalized.get("targets", []):
        token = target.get("api_token")
        if isinstance(token, str) and token:
            target["api_token"] = encrypt_str(token)
    _write_state(_STATE_KEY_HIVE, normalized)


def get_sorting_profile_sync_state() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_SORTING_PROFILE_SYNC)
    return value if isinstance(value, dict) else None


def set_sorting_profile_sync_state(state: dict[str, Any] | None) -> None:
    normalized = None
    if isinstance(state, dict):
        normalized = {
            key: value
            for key, value in state.items()
            if isinstance(key, str) and value is not None
        }
    _write_state(_STATE_KEY_SORTING_PROFILE_SYNC, normalized)


def get_api_keys() -> dict[str, str]:
    value = _read_state(_STATE_KEY_API_KEYS)
    stored = _normalize_string_dict(value)

    from secrets_crypto import decrypt_str, is_encrypted

    decoded = {key: decrypt_str(val) for key, val in stored.items()}
    had_plaintext = any(val and not is_encrypted(val) for val in stored.values())
    if had_plaintext and decoded:
        # Transparent migration: re-save so future reads decrypt from ciphertext.
        set_api_keys(decoded)
    return decoded


def set_api_keys(keys: dict[str, str] | None) -> None:
    from secrets_crypto import encrypt_str

    normalized = _normalize_string_dict(keys)
    encrypted = {key: encrypt_str(val) for key, val in normalized.items() if val}
    _write_state(_STATE_KEY_API_KEYS, encrypted or None)


def get_servo_states() -> dict[str, Any]:
    value = _read_state(_STATE_KEY_SERVO_STATES)
    return value if isinstance(value, dict) else {}


def set_servo_states(states: dict[str, Any]) -> None:
    _write_state(_STATE_KEY_SERVO_STATES, dict(states))


def get_set_progress_state() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_SET_PROGRESS)
    return value if isinstance(value, dict) else None


def set_set_progress_state(state: dict[str, Any] | None) -> None:
    normalized = dict(state) if isinstance(state, dict) else None
    _write_state(_STATE_KEY_SET_PROGRESS, normalized)


def get_recent_known_objects() -> list[dict[str, Any]]:
    value = _read_state(_STATE_KEY_RECENT_KNOWN_OBJECTS)
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("uuid"), str):
            result.append(dict(item))
    return result


def get_ui_theme_color_id() -> str | None:
    value = _read_state(_STATE_KEY_UI_THEME_COLOR_ID)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def set_ui_theme_color_id(color_id: str | None) -> None:
    if color_id is None:
        _write_state(_STATE_KEY_UI_THEME_COLOR_ID, None)
        return
    if not isinstance(color_id, str):
        raise ValueError("color_id must be a string")
    normalized = color_id.strip()
    if not normalized:
        _write_state(_STATE_KEY_UI_THEME_COLOR_ID, None)
        return
    _write_state(_STATE_KEY_UI_THEME_COLOR_ID, normalized)


_CHECKLIST_ALLOWED_STATES = ('auto', 'deferred', 'complete')


def get_checklist_state_for_set(set_num: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Return a lookup of checklist state keyed by (part_num, color_id) for a set.

    State keyed by the rebrickable set_num so it survives profile swaps, bin
    clears, and restarts. Entries with state == 'auto' and a NULL
    manual_override_count are omitted — they are indistinguishable from
    no-entry.
    """
    if not isinstance(set_num, str) or not set_num.strip():
        return {}
    initialize_local_state()
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
    initialize_local_state()
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


def _persistent_tracker_ignored_regions_key(role: str) -> str:
    normalized = role.strip() if isinstance(role, str) else ""
    if not normalized:
        raise ValueError("role must be a non-empty string")
    return f"{_STATE_KEY_PERSISTENT_TRACKER_IGNORED_REGIONS_PREFIX}{normalized}"


def get_persistent_tracker_ignored_regions(role: str) -> list[dict[str, Any]]:
    key = _persistent_tracker_ignored_regions_key(role)
    initialize_local_state()
    with _connection() as conn:
        raw = _get_json(conn, key)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        center = item.get("center_px")
        if (
            not isinstance(center, (list, tuple))
            or len(center) != 2
            or not all(isinstance(v, (int, float)) for v in center)
        ):
            continue
        out.append(
            {
                "center_px": [float(center[0]), float(center[1])],
                "radius_px": float(item.get("radius_px", 0.0)),
                "center_angle_rad": (
                    float(item["center_angle_rad"])
                    if isinstance(item.get("center_angle_rad"), (int, float))
                    else None
                ),
                "center_radius_px": (
                    float(item["center_radius_px"])
                    if isinstance(item.get("center_radius_px"), (int, float))
                    else None
                ),
                "angle_tolerance_rad": (
                    float(item["angle_tolerance_rad"])
                    if isinstance(item.get("angle_tolerance_rad"), (int, float))
                    else None
                ),
                "radius_tolerance_px": (
                    float(item["radius_tolerance_px"])
                    if isinstance(item.get("radius_tolerance_px"), (int, float))
                    else None
                ),
                "suppression_count": max(
                    1,
                    int(item["suppression_count"])
                    if isinstance(item.get("suppression_count"), (int, float))
                    else 1,
                ),
            }
        )
    return out


def set_persistent_tracker_ignored_regions(
    role: str,
    regions: list[dict[str, Any]],
) -> None:
    key = _persistent_tracker_ignored_regions_key(role)
    normalized: list[dict[str, Any]] = []
    if isinstance(regions, list):
        for item in regions:
            if not isinstance(item, dict):
                continue
            center = item.get("center_px")
            if (
                not isinstance(center, (list, tuple))
                or len(center) != 2
                or not all(isinstance(v, (int, float)) for v in center)
            ):
                continue
            normalized.append(
                {
                    "center_px": [float(center[0]), float(center[1])],
                    "radius_px": float(item.get("radius_px", 0.0)),
                    "center_angle_rad": (
                        float(item["center_angle_rad"])
                        if isinstance(item.get("center_angle_rad"), (int, float))
                        else None
                    ),
                    "center_radius_px": (
                        float(item["center_radius_px"])
                        if isinstance(item.get("center_radius_px"), (int, float))
                        else None
                    ),
                    "angle_tolerance_rad": (
                        float(item["angle_tolerance_rad"])
                        if isinstance(item.get("angle_tolerance_rad"), (int, float))
                        else None
                    ),
                    "radius_tolerance_px": (
                        float(item["radius_tolerance_px"])
                        if isinstance(item.get("radius_tolerance_px"), (int, float))
                        else None
                    ),
                    "suppression_count": max(
                        1,
                        int(item["suppression_count"])
                        if isinstance(item.get("suppression_count"), (int, float))
                        else 1,
                    ),
                }
            )
    initialize_local_state()
    with _connection() as conn:
        _set_json(conn, key, normalized)
        conn.commit()


def _current_sync_state_from_conn(conn: sqlite3.Connection) -> dict[str, Any]:
    value = _get_json(conn, _STATE_KEY_SORTING_PROFILE_SYNC)
    return value if isinstance(value, dict) else {}


def _session_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        key: row[key]
        for key in row.keys()
    }


def _latest_sorting_session_conn(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM sorting_sessions ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return _session_row_to_dict(row)


def _piece_dossier_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        payload = json.loads(str(row["payload_json"]))
    except Exception:
        payload = None
    if not isinstance(payload, dict):
        payload = {}
    payload["uuid"] = str(payload.get("uuid") or row["piece_uuid"])
    payload["session_id"] = row["session_id"]
    payload["last_event_at"] = float(row["last_event_at"])
    return payload


def _close_active_sorting_session_conn(conn: sqlite3.Connection, *, reason: str | None = None) -> None:
    active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
    if not active_session_id:
        return
    conn.execute(
        "UPDATE sorting_sessions SET status = 'closed', ended_at = ?, reason = COALESCE(?, reason) WHERE id = ? AND status = 'active'",
        (time.time(), reason, active_session_id),
    )
    conn.execute("DELETE FROM metadata WHERE key = ?", (_META_KEY_ACTIVE_SORTING_SESSION_ID,))


def _create_sorting_session_conn(
    conn: sqlite3.Connection,
    *,
    sync_state: dict[str, Any],
    reason: str | None = None,
) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = time.time()
    raw_machine_id = _get_json(conn, _STATE_KEY_MACHINE_ID)
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


def _ensure_active_sorting_session_conn(
    conn: sqlite3.Connection,
    *,
    force_new: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    sync_state = _current_sync_state_from_conn(conn)
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

    return _create_sorting_session_conn(conn, sync_state=sync_state, reason=reason)


def _payload_value(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    if isinstance(value, list) and len(value) == 0:
        return None
    return value


def _min_positive_timestamp(*values: Any) -> float | None:
    candidates = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and float(value) > 0.0
    ]
    if not candidates:
        return None
    return min(candidates)


def _max_positive_timestamp(*values: Any) -> float | None:
    candidates = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and float(value) > 0.0
    ]
    if not candidates:
        return None
    return max(candidates)


def _merge_piece_payload(
    existing: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in incoming.items():
        if not isinstance(key, str):
            continue
        normalized = value
        if isinstance(value, str) and not value.strip():
            normalized = None
        if isinstance(value, list) and len(value) == 0:
            normalized = None
        if normalized is None and key in merged:
            continue
        merged[key] = value

    created_at = _min_positive_timestamp(
        _payload_value(existing or {}, "created_at"),
        _payload_value(incoming, "created_at"),
    )
    if created_at is not None:
        merged["created_at"] = created_at

    updated_at = _max_positive_timestamp(
        _payload_value(existing or {}, "updated_at"),
        _payload_value(incoming, "updated_at"),
        _payload_value(existing or {}, "distributed_at"),
        _payload_value(incoming, "distributed_at"),
    )
    if updated_at is not None:
        merged["updated_at"] = updated_at

    first_seen_ts = _min_positive_timestamp(
        _payload_value(existing or {}, "first_carousel_seen_ts"),
        _payload_value(incoming, "first_carousel_seen_ts"),
    )
    if first_seen_ts is not None:
        merged["first_carousel_seen_ts"] = first_seen_ts

    distributed_at = _max_positive_timestamp(
        _payload_value(existing or {}, "distributed_at"),
        _payload_value(incoming, "distributed_at"),
    )
    if distributed_at is not None:
        merged["distributed_at"] = distributed_at

    return merged


def start_new_sorting_session(*, reason: str = "profile_activated") -> dict[str, Any]:
    initialize_local_state()
    with _connection() as conn:
        session = _ensure_active_sorting_session_conn(conn, force_new=True, reason=reason)
        conn.commit()
        return session


def get_active_sorting_session() -> dict[str, Any] | None:
    initialize_local_state()
    with _connection() as conn:
        active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
        if not active_session_id:
            return None
        row = conn.execute(
            "SELECT * FROM sorting_sessions WHERE id = ? AND status = 'active'",
            (active_session_id,),
        ).fetchone()
        return _session_row_to_dict(row)


def remember_piece_dossier(obj: dict[str, Any]) -> None:
    if not isinstance(obj, dict):
        return
    piece_uuid = obj.get("uuid")
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return

    initialize_local_state()
    with _connection() as conn:
        existing_row = conn.execute(
            "SELECT * FROM piece_dossiers WHERE piece_uuid = ?",
            (piece_uuid,),
        ).fetchone()
        existing_payload = _piece_dossier_row_to_dict(existing_row)
        merged = _merge_piece_payload(existing_payload, obj)
        if existing_row is not None:
            session_id = str(existing_row["session_id"])
        else:
            session = _ensure_active_sorting_session_conn(conn, force_new=False)
            session_id = str(session["id"])

        created_at = _min_positive_timestamp(
            _payload_value(merged, "created_at"),
            _payload_value(merged, "feeding_started_at"),
            _payload_value(merged, "first_carousel_seen_ts"),
            _payload_value(merged, "updated_at"),
        ) or time.time()
        updated_at = _max_positive_timestamp(
            _payload_value(merged, "updated_at"),
            _payload_value(merged, "distributed_at"),
            _payload_value(merged, "distribution_positioned_at"),
            _payload_value(merged, "classified_at"),
            _payload_value(merged, "first_carousel_seen_ts"),
            created_at,
        ) or created_at
        merged["created_at"] = created_at
        merged["updated_at"] = updated_at

        stage = str(
            _payload_value(merged, "stage")
            or (existing_row["stage"] if existing_row is not None else "created")
        )
        classification_status = str(
            _payload_value(merged, "classification_status")
            or (
                existing_row["classification_status"]
                if existing_row is not None
                else "pending"
            )
        )
        tracked_global_id = _payload_value(merged, "tracked_global_id")
        tracked_global_id = (
            int(tracked_global_id)
            if isinstance(tracked_global_id, int)
            or (
                isinstance(tracked_global_id, float)
                and float(tracked_global_id).is_integer()
            )
            else None
        )
        first_carousel_seen_ts = _min_positive_timestamp(
            _payload_value(merged, "first_carousel_seen_ts")
        )
        zone_center_deg = _payload_value(merged, "classification_channel_zone_center_deg")
        zone_center_deg = (
            float(zone_center_deg)
            if isinstance(zone_center_deg, (int, float))
            else None
        )
        distributed_at = _max_positive_timestamp(_payload_value(merged, "distributed_at"))

        conn.execute(
            "INSERT INTO piece_dossiers(piece_uuid, session_id, tracked_global_id, created_at, updated_at, last_event_at, stage, classification_status, first_carousel_seen_ts, classification_channel_zone_center_deg, distributed_at, payload_json) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(piece_uuid) DO UPDATE SET "
            "session_id = excluded.session_id, "
            "tracked_global_id = excluded.tracked_global_id, "
            "created_at = excluded.created_at, "
            "updated_at = excluded.updated_at, "
            "last_event_at = excluded.last_event_at, "
            "stage = excluded.stage, "
            "classification_status = excluded.classification_status, "
            "first_carousel_seen_ts = excluded.first_carousel_seen_ts, "
            "classification_channel_zone_center_deg = excluded.classification_channel_zone_center_deg, "
            "distributed_at = excluded.distributed_at, "
            "payload_json = excluded.payload_json",
            (
                piece_uuid,
                session_id,
                tracked_global_id,
                created_at,
                updated_at,
                updated_at,
                stage,
                classification_status,
                first_carousel_seen_ts,
                zone_center_deg,
                distributed_at,
                json.dumps(merged, sort_keys=True),
            ),
        )
        conn.commit()


def get_piece_dossier(piece_uuid: str) -> dict[str, Any] | None:
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return None
    initialize_local_state()
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM piece_dossiers WHERE piece_uuid = ?",
            (piece_uuid,),
        ).fetchone()
        return _piece_dossier_row_to_dict(row)


def get_piece_dossier_by_tracked_global_id(tracked_global_id: int) -> dict[str, Any] | None:
    initialize_local_state()
    with _connection() as conn:
        row = conn.execute(
            "SELECT * FROM piece_dossiers WHERE tracked_global_id = ? ORDER BY last_event_at DESC LIMIT 1",
            (int(tracked_global_id),),
        ).fetchone()
        return _piece_dossier_row_to_dict(row)


def list_piece_dossiers(
    *,
    limit: int = 200,
    session_id: str | None = None,
) -> list[dict[str, Any]]:
    initialize_local_state()
    with _connection() as conn:
        resolved_session_id = session_id
        if not resolved_session_id:
            active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
            if active_session_id:
                resolved_session_id = active_session_id
            else:
                latest = _latest_sorting_session_conn(conn)
                resolved_session_id = str(latest["id"]) if latest is not None else None
        if not resolved_session_id:
            return []
        rows = conn.execute(
            "SELECT * FROM piece_dossiers WHERE session_id = ? ORDER BY last_event_at DESC LIMIT ?",
            (resolved_session_id, max(1, int(limit))),
        ).fetchall()
        return [
            entry
            for entry in (_piece_dossier_row_to_dict(row) for row in rows)
            if entry is not None
        ]


def clear_piece_dossiers(*, clear_recent_known_objects: bool = True) -> None:
    initialize_local_state()
    with _connection() as conn:
        conn.execute("DELETE FROM piece_dossiers")
        if clear_recent_known_objects:
            _set_json(conn, _STATE_KEY_RECENT_KNOWN_OBJECTS, [])
        conn.commit()


def _coerce_optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return int(value)
    return None


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        float_value = float(value)
        if float_value != float_value:  # NaN
            return None
        return float_value
    return None


def _piece_segment_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    try:
        path = json.loads(str(row["path_json"]))
    except Exception:
        path = None
    if not isinstance(path, list):
        path = []
    try:
        sector_snapshots = json.loads(str(row["sector_snapshots_json"]))
    except Exception:
        sector_snapshots = None
    if not isinstance(sector_snapshots, list):
        sector_snapshots = []
    recognize_result: Any | None = None
    raw_recognize = row["recognize_result_json"]
    if raw_recognize is not None:
        try:
            recognize_result = json.loads(str(raw_recognize))
        except Exception:
            recognize_result = None
    return {
        "id": int(row["id"]),
        "piece_uuid": str(row["piece_uuid"]),
        "session_id": str(row["session_id"]),
        "role": str(row["role"]),
        "tracked_global_id": (
            int(row["tracked_global_id"])
            if row["tracked_global_id"] is not None
            else None
        ),
        "sequence": int(row["sequence"]),
        "first_seen_ts": float(row["first_seen_ts"]),
        "last_seen_ts": float(row["last_seen_ts"]),
        "hit_count": int(row["hit_count"]),
        "channel_center_x": (
            float(row["channel_center_x"])
            if row["channel_center_x"] is not None
            else None
        ),
        "channel_center_y": (
            float(row["channel_center_y"])
            if row["channel_center_y"] is not None
            else None
        ),
        "channel_radius_inner": (
            float(row["channel_radius_inner"])
            if row["channel_radius_inner"] is not None
            else None
        ),
        "channel_radius_outer": (
            float(row["channel_radius_outer"])
            if row["channel_radius_outer"] is not None
            else None
        ),
        "snapshot_width": (
            int(row["snapshot_width"])
            if row["snapshot_width"] is not None
            else None
        ),
        "snapshot_height": (
            int(row["snapshot_height"])
            if row["snapshot_height"] is not None
            else None
        ),
        "snapshot_path": (
            str(row["snapshot_path"])
            if row["snapshot_path"] is not None
            else None
        ),
        "path": path,
        "sector_snapshots": sector_snapshots,
        "recognize_result": recognize_result,
        "created_at": float(row["created_at"]),
    }


def remember_piece_segment(
    piece_uuid: str,
    role: str,
    sequence: int,
    payload: dict[str, Any],
) -> None:
    """Persist (or upsert) a per-segment tracking record for a piece.

    ``payload`` carries the segment fields — see the ``piece_segments``
    schema for the accepted keys. List-valued keys (``path``,
    ``sector_snapshots``) and ``recognize_result`` are serialized into their
    respective ``*_json`` columns. On upsert over an existing
    ``(piece_uuid, sequence)`` row, ``created_at`` is preserved.
    """
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return
    if not isinstance(role, str) or not role.strip():
        return
    if not isinstance(payload, dict):
        payload = {}
    try:
        sequence_int = int(sequence)
    except (TypeError, ValueError):
        return

    initialize_local_state()
    with _connection() as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM piece_segments "
            "WHERE piece_uuid = ? AND sequence = ?",
            (piece_uuid, sequence_int),
        ).fetchone()

        tracked_global_id = _coerce_optional_int(payload.get("tracked_global_id"))
        first_seen_ts = _coerce_optional_float(payload.get("first_seen_ts")) or 0.0
        last_seen_ts = _coerce_optional_float(payload.get("last_seen_ts")) or first_seen_ts
        hit_count = _coerce_optional_int(payload.get("hit_count")) or 0
        channel_center_x = _coerce_optional_float(payload.get("channel_center_x"))
        channel_center_y = _coerce_optional_float(payload.get("channel_center_y"))
        channel_radius_inner = _coerce_optional_float(payload.get("channel_radius_inner"))
        channel_radius_outer = _coerce_optional_float(payload.get("channel_radius_outer"))
        snapshot_width = _coerce_optional_int(payload.get("snapshot_width"))
        snapshot_height = _coerce_optional_int(payload.get("snapshot_height"))
        snapshot_path_raw = payload.get("snapshot_path")
        snapshot_path = (
            str(snapshot_path_raw)
            if isinstance(snapshot_path_raw, str) and snapshot_path_raw
            else None
        )

        path_value = payload.get("path")
        if not isinstance(path_value, list):
            path_value = []
        sector_snapshots_value = payload.get("sector_snapshots")
        if not isinstance(sector_snapshots_value, list):
            sector_snapshots_value = []
        recognize_result_value = payload.get("recognize_result")

        path_json = json.dumps(path_value, sort_keys=True)
        sector_snapshots_json = json.dumps(sector_snapshots_value, sort_keys=True)
        recognize_result_json = (
            json.dumps(recognize_result_value, sort_keys=True)
            if recognize_result_value is not None
            else None
        )

        if existing is not None:
            # Preserve original created_at on upsert.
            session_row = conn.execute(
                "SELECT session_id FROM piece_segments WHERE id = ?",
                (int(existing["id"]),),
            ).fetchone()
            session_id = str(session_row["session_id"]) if session_row is not None else ""
            if not session_id:
                dossier_row = conn.execute(
                    "SELECT session_id FROM piece_dossiers WHERE piece_uuid = ?",
                    (piece_uuid,),
                ).fetchone()
                if dossier_row is not None:
                    session_id = str(dossier_row["session_id"])
                else:
                    session = _ensure_active_sorting_session_conn(conn, force_new=False)
                    session_id = str(session["id"])
            created_at = float(existing["created_at"])
            conn.execute(
                "UPDATE piece_segments SET "
                "session_id = ?, "
                "role = ?, "
                "tracked_global_id = ?, "
                "first_seen_ts = ?, "
                "last_seen_ts = ?, "
                "hit_count = ?, "
                "channel_center_x = ?, "
                "channel_center_y = ?, "
                "channel_radius_inner = ?, "
                "channel_radius_outer = ?, "
                "snapshot_width = ?, "
                "snapshot_height = ?, "
                "snapshot_path = ?, "
                "path_json = ?, "
                "sector_snapshots_json = ?, "
                "recognize_result_json = ? "
                "WHERE id = ?",
                (
                    session_id,
                    role,
                    tracked_global_id,
                    first_seen_ts,
                    last_seen_ts,
                    hit_count,
                    channel_center_x,
                    channel_center_y,
                    channel_radius_inner,
                    channel_radius_outer,
                    snapshot_width,
                    snapshot_height,
                    snapshot_path,
                    path_json,
                    sector_snapshots_json,
                    recognize_result_json,
                    int(existing["id"]),
                ),
            )
            conn.commit()
            return

        # New row: bind to the dossier's session if available, else the
        # active session (creating one if needed).
        dossier_row = conn.execute(
            "SELECT session_id FROM piece_dossiers WHERE piece_uuid = ?",
            (piece_uuid,),
        ).fetchone()
        if dossier_row is not None:
            session_id = str(dossier_row["session_id"])
        else:
            session = _ensure_active_sorting_session_conn(conn, force_new=False)
            session_id = str(session["id"])

        created_at = _coerce_optional_float(payload.get("created_at")) or time.time()
        conn.execute(
            "INSERT INTO piece_segments("
            "piece_uuid, session_id, role, tracked_global_id, sequence, "
            "first_seen_ts, last_seen_ts, hit_count, "
            "channel_center_x, channel_center_y, "
            "channel_radius_inner, channel_radius_outer, "
            "snapshot_width, snapshot_height, snapshot_path, "
            "path_json, sector_snapshots_json, recognize_result_json, "
            "created_at) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                piece_uuid,
                session_id,
                role,
                tracked_global_id,
                sequence_int,
                first_seen_ts,
                last_seen_ts,
                hit_count,
                channel_center_x,
                channel_center_y,
                channel_radius_inner,
                channel_radius_outer,
                snapshot_width,
                snapshot_height,
                snapshot_path,
                path_json,
                sector_snapshots_json,
                recognize_result_json,
                created_at,
            ),
        )
        conn.commit()


def list_piece_segments(piece_uuid: str) -> list[dict[str, Any]]:
    """Return all segments for ``piece_uuid`` ordered by ``sequence`` asc."""
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return []
    initialize_local_state()
    with _connection() as conn:
        rows = conn.execute(
            "SELECT * FROM piece_segments "
            "WHERE piece_uuid = ? ORDER BY sequence ASC",
            (piece_uuid,),
        ).fetchall()
        return [
            entry
            for entry in (_piece_segment_row_to_dict(row) for row in rows)
            if entry is not None
        ]


def clear_piece_segments_for_session(session_id: str) -> int:
    """Delete all segments belonging to ``session_id``. Returns rowcount."""
    if not isinstance(session_id, str) or not session_id.strip():
        return 0
    initialize_local_state()
    with _connection() as conn:
        cursor = conn.execute(
            "DELETE FROM piece_segments WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()
        return int(cursor.rowcount or 0)


def get_piece_segment_counts(
    piece_uuids: list[str] | tuple[str, ...] | None = None,
    *,
    session_id: str | None = None,
) -> dict[str, int]:
    """Return ``{piece_uuid: segment_count}`` in one SELECT.

    Used by the tracked-pieces list endpoint to populate ``has_track_segments``
    without issuing N+1 segment queries. Either pass an explicit list of
    ``piece_uuids`` (preferred when the caller already fetched the dossiers) or
    a ``session_id`` to scope to every piece in that session. Missing pieces
    return 0 implicitly by omission.
    """
    if piece_uuids is not None:
        uuids = [u for u in piece_uuids if isinstance(u, str) and u.strip()]
        if not uuids:
            return {}
        initialize_local_state()
        out: dict[str, int] = {}
        with _connection() as conn:
            # SQLite has a default host-parameter limit of 999. Chunk to be
            # safe; in practice the list endpoint caps at 500 pieces.
            chunk_size = 500
            for start in range(0, len(uuids), chunk_size):
                chunk = uuids[start : start + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    "SELECT piece_uuid, COUNT(*) AS c FROM piece_segments "
                    f"WHERE piece_uuid IN ({placeholders}) GROUP BY piece_uuid",
                    tuple(chunk),
                ).fetchall()
                for row in rows:
                    out[str(row["piece_uuid"])] = int(row["c"])
        return out

    if isinstance(session_id, str) and session_id.strip():
        initialize_local_state()
        with _connection() as conn:
            rows = conn.execute(
                "SELECT piece_uuid, COUNT(*) AS c FROM piece_segments "
                "WHERE session_id = ? GROUP BY piece_uuid",
                (session_id,),
            ).fetchall()
            return {str(row["piece_uuid"]): int(row["c"]) for row in rows}

    return {}


def build_piece_detail_payload(piece_uuid: str) -> dict[str, Any] | None:
    """Return merged dossier + segments payload for the detail endpoint.

    Reads the dossier from :func:`get_piece_dossier` and its segments from
    :func:`list_piece_segments` and merges them into a single response dict
    shaped as ``{**dossier, "track_detail": {"segments": [...], "live": False}}``.
    ``live`` is always ``False`` here (DB source); the API layer flips it to
    ``True`` when live-tracker data is merged on top. Returns ``None`` when no
    dossier row exists — segments without a dossier row are ignored (cannot
    occur thanks to FK cascade but handled defensively).
    """
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return None
    dossier = get_piece_dossier(piece_uuid)
    if dossier is None:
        return None
    segments = list_piece_segments(piece_uuid)
    payload: dict[str, Any] = dict(dossier)
    payload["track_detail"] = {"segments": segments, "live": False}
    return payload


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

    initialize_local_state()
    with _connection() as conn:
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
            "INSERT OR IGNORE INTO piece_events(session_id, piece_uuid, layer_index, section_index, bin_index, bin_epoch, distributed_at, part_id, color_id, color_name, category_id, classification_status, thumbnail, top_image, bottom_image, brickognize_preview_url) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                piece_uuid,
                layer_index,
                section_index,
                bin_index,
                bin_epoch,
                float(distributed_at),
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


def clear_current_session_bins(
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
) -> dict[str, Any]:
    initialize_local_state()
    with _connection() as conn:
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
            f"SELECT layer_index, section_index, bin_index, bin_epoch, piece_count FROM bin_state_current WHERE {' AND '.join(where)}",
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
                "SELECT layer_index, section_index, bin_index, bin_epoch, piece_count FROM bin_state_current WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
                (active_session_id, layer_index, section_index, bin_index),
            ).fetchall()

        cleared_bins = 0
        now = time.time()
        for row in rows:
            li = int(row["layer_index"])
            si = int(row["section_index"])
            bi = int(row["bin_index"])
            current_epoch = int(row["bin_epoch"])
            if int(row["piece_count"] or 0) > 0:
                cleared_bins += 1
            conn.execute(
                "UPDATE bin_state_current SET bin_epoch = ?, piece_count = 0, unique_item_count = 0, last_distributed_at = NULL, updated_at = ? WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
                (current_epoch + 1, now, active_session_id, li, si, bi),
            )
            conn.execute(
                "DELETE FROM bin_item_aggregates WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
                (active_session_id, li, si, bi),
            )

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
        return {"ok": True, "cleared_bins": cleared_bins}


def get_current_bin_piece_counts() -> dict[tuple[int, int, int], int]:
    initialize_local_state()
    with _connection() as conn:
        active_session_id = _get_meta(conn, _META_KEY_ACTIVE_SORTING_SESSION_ID)
        if not active_session_id:
            return {}
        rows = conn.execute(
            "SELECT layer_index, section_index, bin_index, piece_count FROM bin_state_current WHERE session_id = ?",
            (active_session_id,),
        ).fetchall()
        return {
            (int(row["layer_index"]), int(row["section_index"]), int(row["bin_index"])): int(row["piece_count"] or 0)
            for row in rows
        }


def get_current_bin_contents_snapshot() -> dict[str, Any]:
    initialize_local_state()
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


def import_bin_contents_snapshot(snapshot: dict[str, Any], *, reason: str = "snapshot_import") -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {"imported_bins": 0}

    bins = snapshot.get("bins")
    if not isinstance(bins, list):
        return {"imported_bins": 0}

    initialize_local_state()
    with _connection() as conn:
        session = _ensure_active_sorting_session_conn(conn, force_new=False, reason=reason)
        session_id = str(session["id"])
        imported_bins = 0
        now = time.time()

        for raw_bin in bins:
            if not isinstance(raw_bin, dict):
                continue
            try:
                layer_index = int(raw_bin.get("layer_index"))
                section_index = int(raw_bin.get("section_index"))
                bin_index = int(raw_bin.get("bin_index"))
            except (TypeError, ValueError):
                continue

            piece_count = int(raw_bin.get("piece_count") or 0)
            unique_item_count = int(raw_bin.get("unique_item_count") or 0)
            last_distributed_at = raw_bin.get("last_distributed_at")
            bin_epoch = _ensure_bin_state_row_conn(
                conn,
                session_id=session_id,
                layer_index=layer_index,
                section_index=section_index,
                bin_index=bin_index,
            )

            conn.execute(
                "UPDATE bin_state_current SET piece_count = ?, unique_item_count = ?, last_distributed_at = ?, updated_at = ? WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
                (
                    piece_count,
                    unique_item_count,
                    float(last_distributed_at) if isinstance(last_distributed_at, (int, float)) else None,
                    now,
                    session_id,
                    layer_index,
                    section_index,
                    bin_index,
                ),
            )
            conn.execute(
                "DELETE FROM bin_item_aggregates WHERE session_id = ? AND layer_index = ? AND section_index = ? AND bin_index = ?",
                (session_id, layer_index, section_index, bin_index),
            )

            items = raw_bin.get("items")
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    conn.execute(
                        "INSERT OR REPLACE INTO bin_item_aggregates(session_id, layer_index, section_index, bin_index, item_key, part_id, color_id, color_name, category_id, classification_status, count, last_distributed_at, thumbnail, top_image, bottom_image, brickognize_preview_url) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            session_id,
                            layer_index,
                            section_index,
                            bin_index,
                            str(item.get("key") or uuid.uuid4()),
                            item.get("part_id"),
                            item.get("color_id"),
                            item.get("color_name"),
                            item.get("category_id"),
                            item.get("classification_status"),
                            int(item.get("count") or 0),
                            float(item.get("last_distributed_at")) if isinstance(item.get("last_distributed_at"), (int, float)) else None,
                            item.get("thumbnail"),
                            item.get("top_image"),
                            item.get("bottom_image"),
                            item.get("brickognize_preview_url"),
                        ),
                    )

            recent_pieces = raw_bin.get("recent_pieces")
            if isinstance(recent_pieces, list):
                for index, piece in enumerate(recent_pieces):
                    if not isinstance(piece, dict):
                        continue
                    distributed_at = piece.get("distributed_at")
                    if not isinstance(distributed_at, (int, float)):
                        distributed_at = now - index
                    conn.execute(
                        "INSERT OR IGNORE INTO piece_events(session_id, piece_uuid, layer_index, section_index, bin_index, bin_epoch, distributed_at, part_id, color_id, color_name, category_id, classification_status, thumbnail, top_image, bottom_image, brickognize_preview_url) "
                        "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            session_id,
                            str(piece.get("uuid") or f"imported-{layer_index}-{section_index}-{bin_index}-{index}-{uuid.uuid4()}"),
                            layer_index,
                            section_index,
                            bin_index,
                            bin_epoch,
                            float(distributed_at),
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

            imported_bins += 1

        if imported_bins > 0:
            conn.execute(
                "INSERT INTO bin_events(session_id, event_type, created_at, details_json) VALUES(?, ?, ?, ?)",
                (session_id, "snapshot_imported", now, json.dumps({"imported_bins": imported_bins}, sort_keys=True)),
            )
        conn.commit()
        return {"imported_bins": imported_bins, "session_id": session_id}


def remember_recent_known_object(obj: dict[str, Any], *, limit: int = _RECENT_KNOWN_OBJECTS_LIMIT) -> None:
    if not isinstance(obj, dict):
        return
    uuid = obj.get("uuid")
    if not isinstance(uuid, str) or not uuid.strip():
        return

    normalized = {key: value for key, value in obj.items() if isinstance(key, str)}
    existing = [entry for entry in get_recent_known_objects() if entry.get("uuid") != uuid]
    next_entries = [normalized, *existing][: max(1, int(limit))]
    _write_state(_STATE_KEY_RECENT_KNOWN_OBJECTS, next_entries)


def get_bin_layout() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_BIN_LAYOUT)
    return value if isinstance(value, dict) else None


def set_bin_layout(layout: dict[str, Any] | None) -> None:
    _write_state(_STATE_KEY_BIN_LAYOUT, dict(layout) if layout is not None else None)
