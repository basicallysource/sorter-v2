from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

import db

# The machine's key/value state: one JSON value per key in state_entries
# (machine id, stepper and servo positions, polygons, Hive targets, API keys,
# LEDs, ...). A store that reads or writes an entry inside its own transaction
# (bin_contents, bin_layout_store) runs create_tables in its schema function and
# goes through read_entry and write_entry.

STATE_KEY_MACHINE_ID = "machine_id"
STATE_KEY_SORTING_PROFILE_SYNC = "sorting_profile_sync"
_STATE_KEY_CHANNEL_POLYGONS = "channel_polygons"
_STATE_KEY_CLASSIFICATION_POLYGONS = "classification_polygons"
_STATE_KEY_CLASSIFICATION_TRAINING = "classification_training"
_STATE_KEY_HIVE = "hive"
_STATE_KEY_API_KEYS = "api_keys"
_STATE_KEY_SERVO_STATES = "servo_states"
_STATE_KEY_SET_PROGRESS = "set_progress"
_STATE_KEY_UI_THEME_COLOR_ID = "ui_theme_color_id"
_STATE_KEY_TAILSCALE_HOSTNAME = "tailscale_hostname"
_STATE_KEY_SAMPLE_COLLECTION = "sample_collection"
_STATE_KEY_TELEMETRY_INSTALL = "telemetry_install"
_STATE_KEY_LEDS = "leds"
_STATE_KEY_BASICALLY_SERVICES = "basically_services"
_STATE_KEY_FEEDER_AUTOTUNE_BACKGROUND = "feeder_autotune_background"


def create_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS state_entries ("
        "key TEXT PRIMARY KEY, "
        "json_value TEXT NOT NULL, "
        "updated_at REAL NOT NULL"
        ")"
    )


def _connection(op: str | None = None):
    return db.connect(create_tables, op=op)


def read_entry(conn: sqlite3.Connection, key: str) -> Any | None:
    row = conn.execute(
        "SELECT json_value FROM state_entries WHERE key = ?",
        (key,),
    ).fetchone()
    if row is None:
        return None
    return json.loads(str(row["json_value"]))


def write_entry(conn: sqlite3.Connection, key: str, value: Any | None) -> None:
    """Store `value` under `key`; None deletes the entry."""
    if value is None:
        conn.execute("DELETE FROM state_entries WHERE key = ?", (key,))
        return
    conn.execute(
        "INSERT INTO state_entries(key, json_value, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET json_value = excluded.json_value, updated_at = excluded.updated_at",
        (key, json.dumps(value, sort_keys=True), time.time()),
    )


def _read_state(key: str) -> Any | None:
    with _connection(f"local_state._read_state({key})") as conn:
        return read_entry(conn, key)


def _write_state(key: str, value: Any | None) -> None:
    with _connection(f"local_state._write_state({key})") as conn:
        write_entry(conn, key, value)
        conn.commit()


def _read_dict(key: str) -> dict[str, Any] | None:
    value = _read_state(key)
    return value if isinstance(value, dict) else None


def _without_none_values(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    return {key: value for key, value in state.items() if isinstance(key, str) and value is not None}


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
    telemetry = raw.get("telemetry")
    if isinstance(telemetry, dict):
        # Per-target upload permissions; hive_telemetry owns the field set and
        # defaults, so pass through any bool entries untouched.
        normalized_telemetry = {
            key: value
            for key, value in telemetry.items()
            if isinstance(key, str) and isinstance(value, bool)
        }
        if normalized_telemetry:
            target["telemetry"] = normalized_telemetry
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

    # Exactly one target is the "primary" — used for metadata lookups (piece
    # dimensions, etc). Default to the first target; reset to the first if the
    # stored id no longer points at a live target.
    target_ids = {target["id"] for target in normalized_targets}
    primary_target_id = raw.get("primary_target_id") if isinstance(raw, dict) else None
    if not isinstance(primary_target_id, str) or primary_target_id not in target_ids:
        primary_target_id = normalized_targets[0]["id"] if normalized_targets else None

    return {"targets": normalized_targets, "primary_target_id": primary_target_id}


def get_machine_id() -> str | None:
    value = _read_state(STATE_KEY_MACHINE_ID)
    return value if isinstance(value, str) and value.strip() else None


def set_machine_id(machine_id: str) -> None:
    normalized = machine_id.strip() if isinstance(machine_id, str) else ""
    if not normalized:
        raise ValueError("machine_id must be a non-empty string")
    _write_state(STATE_KEY_MACHINE_ID, normalized)


def get_or_create_machine_id() -> str:
    machine_id = get_machine_id()
    if machine_id is not None:
        return machine_id
    machine_id = str(uuid.uuid4())
    set_machine_id(machine_id)
    return machine_id


# The anonymous install identity for the status ping (status_ping.py). Kept
# deliberately SEPARATE from machine_id: machine_id is sent to Hive at account
# registration and is therefore account-linked, whereas this id is random,
# never joined to an account, and is the only handle carried by the anonymous
# ping. Keeping the two apart is what lets an operator wipe their anonymous
# footprint (the Hive "forget" form) without touching registered machine data.
# created_at is stamped once, the first time the id is generated, so the server
# learns when this install first came online even if we only hear from it later.
def get_or_create_telemetry_install() -> dict[str, Any]:
    existing = _read_state(_STATE_KEY_TELEMETRY_INSTALL)
    if isinstance(existing, dict):
        install_id = existing.get("install_id")
        created_at = existing.get("created_at")
        if isinstance(install_id, str) and install_id.strip():
            return {
                "install_id": install_id,
                "created_at": float(created_at) if isinstance(created_at, (int, float)) else None,
            }
    record = {"install_id": str(uuid.uuid4()), "created_at": time.time()}
    _write_state(_STATE_KEY_TELEMETRY_INSTALL, record)
    return record


# Hosted-services enrollment on the main hive (basically_services.py). Separate
# from both the Hive account targets (an account object) and the anonymous
# telemetry install id (which must stay unlinkable). device_key is the stable
# secret that lets a re-enroll find the same server-side device row; token is
# the bearer credential the enroll call returned.
def get_basically_services_state() -> dict[str, Any]:
    return _read_dict(_STATE_KEY_BASICALLY_SERVICES) or {}


def set_basically_services_state(record: dict[str, Any]) -> None:
    _write_state(_STATE_KEY_BASICALLY_SERVICES, record)


def get_channel_polygons() -> dict[str, Any] | None:
    return _read_dict(_STATE_KEY_CHANNEL_POLYGONS)


def set_channel_polygons(polygons: dict[str, Any]) -> None:
    _write_state(_STATE_KEY_CHANNEL_POLYGONS, dict(polygons))


def get_classification_polygons() -> dict[str, Any] | None:
    return _read_dict(_STATE_KEY_CLASSIFICATION_POLYGONS)


def set_classification_polygons(polygons: dict[str, Any]) -> None:
    _write_state(_STATE_KEY_CLASSIFICATION_POLYGONS, dict(polygons))


def get_classification_training_state() -> dict[str, Any] | None:
    return _read_dict(_STATE_KEY_CLASSIFICATION_TRAINING)


def set_classification_training_state(state: dict[str, Any] | None) -> None:
    _write_state(_STATE_KEY_CLASSIFICATION_TRAINING, _without_none_values(state))


def get_sample_collection_state() -> dict[str, Any] | None:
    return _read_dict(_STATE_KEY_SAMPLE_COLLECTION)


def set_sample_collection_state(state: dict[str, Any] | None) -> None:
    _write_state(_STATE_KEY_SAMPLE_COLLECTION, _without_none_values(state))


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
    return _read_dict(STATE_KEY_SORTING_PROFILE_SYNC)


def set_sorting_profile_sync_state(state: dict[str, Any] | None) -> None:
    _write_state(STATE_KEY_SORTING_PROFILE_SYNC, _without_none_values(state))


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
    return _read_dict(_STATE_KEY_SERVO_STATES) or {}


def get_set_progress_state() -> dict[str, Any] | None:
    return _read_dict(_STATE_KEY_SET_PROGRESS)


def set_set_progress_state(state: dict[str, Any] | None) -> None:
    normalized = dict(state) if isinstance(state, dict) else None
    _write_state(_STATE_KEY_SET_PROGRESS, normalized)


# The three channels that can have a light of their own. "assignments" maps one
# to the id of the board output driving it; "brightness" is keyed by output id,
# not by channel, so channels sharing a pin cannot disagree about its duty.
LED_CHANNEL_KEYS = ("c_channel_2", "c_channel_3", "classification_channel")
LED_DEFAULT_BRIGHTNESS_PERCENT = 100


def _normalize_leds(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    assignments_raw = raw.get("assignments") if isinstance(raw.get("assignments"), dict) else {}
    brightness_raw = raw.get("brightness") if isinstance(raw.get("brightness"), dict) else {}
    assignments = {
        key: assignments_raw.get(key) if isinstance(assignments_raw.get(key), str) else None
        for key in LED_CHANNEL_KEYS
    }
    brightness = {
        str(output_id): max(0, min(100, int(round(percent))))
        for output_id, percent in brightness_raw.items()
        if isinstance(percent, (int, float)) and not isinstance(percent, bool)
    }
    return {"assignments": assignments, "brightness": brightness}


def get_led_state() -> dict[str, Any]:
    return _normalize_leds(_read_state(_STATE_KEY_LEDS))


def set_led_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_leds(state)
    _write_state(_STATE_KEY_LEDS, normalized)
    return normalized


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


def get_tailscale_hostname() -> str | None:
    value = _read_state(_STATE_KEY_TAILSCALE_HOSTNAME)
    return value if isinstance(value, str) and value.strip() else None


def set_tailscale_hostname(hostname: str) -> None:
    _write_state(_STATE_KEY_TAILSCALE_HOSTNAME, hostname.strip())


# The feeder auto-tune's background exploration (on or off, its settings and
# baseline config), kept so a restart resumes it
# (subsystems/feeder/pulse_perception/autotune.py). Its runs and trials are in
# feeder_autotune_records.
def getFeederAutotuneBackground() -> dict[str, Any] | None:
    return _read_dict(_STATE_KEY_FEEDER_AUTOTUNE_BACKGROUND)


def setFeederAutotuneBackground(record: dict[str, Any] | None) -> None:
    _write_state(
        _STATE_KEY_FEEDER_AUTOTUNE_BACKGROUND,
        dict(record) if isinstance(record, dict) else None,
    )
