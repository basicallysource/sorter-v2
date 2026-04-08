from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import tomllib
from pathlib import Path
from typing import Any

CLIENT_DIR = Path(__file__).resolve().parent

_STATE_INIT_LOCK = threading.Lock()
_SCHEMA_VERSION = 1

_STATE_KEY_MACHINE_ID = "machine_id"
_STATE_KEY_STEPPER_POSITIONS = "stepper_positions"
_STATE_KEY_SERVO_POSITIONS = "servo_positions"
_STATE_KEY_BIN_CATEGORIES = "bin_categories"
_STATE_KEY_CHANNEL_POLYGONS = "channel_polygons"
_STATE_KEY_CLASSIFICATION_POLYGONS = "classification_polygons"
_STATE_KEY_CLASSIFICATION_TRAINING = "classification_training"
_STATE_KEY_SORTHIVE = "sorthive"
_STATE_KEY_SORTING_PROFILE_SYNC = "sorting_profile_sync"
_STATE_KEY_API_KEYS = "api_keys"
_STATE_KEY_SERVO_STATES = "servo_states"
_STATE_KEY_SET_PROGRESS = "set_progress"
_STATE_KEY_BIN_LAYOUT = "bin_layout"


def local_state_db_path() -> Path:
    env_path = os.getenv("LOCAL_STATE_DB_PATH")
    if isinstance(env_path, str) and env_path.strip():
        return Path(env_path).expanduser()

    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if isinstance(params_path, str) and params_path.strip():
        return Path(params_path).expanduser().resolve().parent / "local_state.sqlite"

    return CLIENT_DIR / "local_state.sqlite"


def _legacy_machine_params_path() -> Path:
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if isinstance(params_path, str) and params_path.strip():
        return Path(params_path).expanduser().resolve()
    return CLIENT_DIR / "machine_params.toml"


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
    try:
        with open(path, "rb") as handle:
            data = tomllib.load(handle)
    except Exception:
        return {}
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


def _normalize_sorthive_target(raw: Any, index: int) -> dict[str, Any] | None:
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


def _normalize_sorthive_config(raw: Any) -> dict[str, Any]:
    raw_targets = raw.get("targets") if isinstance(raw, dict) else None
    normalized_targets: list[dict[str, Any]] = []
    if isinstance(raw_targets, list):
        for index, item in enumerate(raw_targets):
            target = _normalize_sorthive_target(item, index)
            if target is not None:
                normalized_targets.append(target)
    elif isinstance(raw, dict):
        legacy_target = _normalize_sorthive_target(raw, 0)
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
    _migrate_state_key(conn, _STATE_KEY_SORTHIVE, _normalize_sorthive_config(config.get("sorthive")))
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


def _migrate_bin_layout_from_toml(conn: sqlite3.Connection) -> None:
    if _get_json(conn, _STATE_KEY_BIN_LAYOUT) is not None:
        return

    config = _read_machine_params()
    layers_table = config.get("layers")
    if not isinstance(layers_table, dict):
        return

    raw_sections = layers_table.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        return

    open_angles = layers_table.get("servo_open_angles", {})
    if not isinstance(open_angles, dict):
        open_angles = {}
    closed_angles = layers_table.get("servo_closed_angles", {})
    if not isinstance(closed_angles, dict):
        closed_angles = {}

    layers = []
    for i, sections in enumerate(raw_sections):
        if not isinstance(sections, list):
            continue
        layer: dict[str, Any] = {"sections": sections, "enabled": True}
        open_val = open_angles.get(str(i))
        closed_val = closed_angles.get(str(i))
        if isinstance(open_val, int):
            layer["servo_open_angle"] = open_val
        if isinstance(closed_val, int):
            layer["servo_closed_angle"] = closed_val
        layers.append(layer)

    if layers:
        _set_json(conn, _STATE_KEY_BIN_LAYOUT, {"layers": layers})


def _cleanup_machine_params_runtime_sections(conn: sqlite3.Connection) -> None:
    config_path = _legacy_machine_params_path()
    config = _read_machine_params()
    if not config:
        return

    moved_sections = {
        "classification_training": _STATE_KEY_CLASSIFICATION_TRAINING,
        "api_keys": _STATE_KEY_API_KEYS,
        "sorthive": _STATE_KEY_SORTHIVE,
        "sorting_profile_sync": _STATE_KEY_SORTING_PROFILE_SYNC,
    }
    changed = False
    for section_name, state_key in moved_sections.items():
        if section_name not in config:
            continue
        if _get_json(conn, state_key) is None:
            continue
        config.pop(section_name, None)
        changed = True

    if not changed:
        return

    from server.config_helpers import write_machine_params_config

    write_machine_params_config(str(config_path), config)


def initialize_local_state() -> None:
    with _STATE_INIT_LOCK:
        with _connect() as conn:
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
            schema_version = _get_meta(conn, "schema_version")
            if schema_version != str(_SCHEMA_VERSION):
                _set_meta(conn, "schema_version", str(_SCHEMA_VERSION))

            _migrate_from_machine_params(conn)
            _migrate_from_polygons_json(conn)
            _migrate_from_data_json(conn)
            _migrate_misc_state_files(conn)
            _migrate_bin_layout_from_toml(conn)
            _cleanup_machine_params_runtime_sections(conn)
            conn.commit()


def _read_state(key: str) -> Any | None:
    initialize_local_state()
    with _connect() as conn:
        return _get_json(conn, key)


def _write_state(key: str, value: Any | None) -> None:
    initialize_local_state()
    with _connect() as conn:
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


def get_sorthive_config() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_SORTHIVE)
    if not isinstance(value, dict):
        return {"targets": []}
    return _normalize_sorthive_config(value)


def set_sorthive_config(config: dict[str, Any]) -> None:
    _write_state(_STATE_KEY_SORTHIVE, _normalize_sorthive_config(config))


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
    return _normalize_string_dict(value)


def set_api_keys(keys: dict[str, str] | None) -> None:
    normalized = _normalize_string_dict(keys)
    _write_state(_STATE_KEY_API_KEYS, normalized or None)


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


def get_bin_layout() -> dict[str, Any] | None:
    value = _read_state(_STATE_KEY_BIN_LAYOUT)
    return value if isinstance(value, dict) else None


def set_bin_layout(layout: dict[str, Any]) -> None:
    _write_state(_STATE_KEY_BIN_LAYOUT, dict(layout))
