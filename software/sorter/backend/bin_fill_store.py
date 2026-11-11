from __future__ import annotations

import threading
from typing import Any

import db
import local_state

# Volume-aware bin limits: a "fill unit" is a relative piece volume where 1.0
# is the reference piece (a 2x4 brick). Each part_id maps to the units one of
# its pieces adds to a bin; parts without an entry count as `default_units`.
# Bins track their fill in memory (bin_contents) and compare it against the
# layout's per-layer max_fill_units, so big parts fill their bin sooner than
# the piece count alone suggests. Units are relative on purpose — only their
# ratios matter, and the operator tunes them per part in the UI.

_STATE_KEY = "bin_fill_units"
_DEFAULT_UNITS = 1.0

_lock = threading.RLock()
_cache: tuple[str, dict[str, Any]] | None = None


def _createTables(conn) -> None:
    local_state.create_tables(conn)


def _normalize_config(raw: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"default_units": _DEFAULT_UNITS, "parts": {}}
    if not isinstance(raw, dict):
        return config
    default = raw.get("default_units")
    if isinstance(default, (int, float)) and not isinstance(default, bool) and default > 0:
        config["default_units"] = float(default)
    parts = raw.get("parts")
    if isinstance(parts, dict):
        for part_id, units in parts.items():
            key = str(part_id or "").strip()
            if not key:
                continue
            if isinstance(units, (int, float)) and not isinstance(units, bool) and units > 0:
                config["parts"][key] = float(units)
    return config


def get_fill_config() -> dict[str, Any]:
    """The fill-unit config: {"default_units": float, "parts": {part_id: units}}."""
    global _cache
    with _lock:
        path = db.local_state_db_path()
        if _cache is not None and _cache[0] == path:
            return _cache[1]
        with db.connect(_createTables) as conn:
            config = _normalize_config(local_state.read_entry(conn, _STATE_KEY))
        _cache = (path, config)
        return config


def set_fill_config(*, default_units: float | None = None, parts: dict[str, float] | None = None) -> dict[str, Any]:
    """Update the config. Both fields are optional; passing parts replaces the
    whole per-part map. Values must be positive numbers."""
    with _lock:
        current = get_fill_config()
        merged: dict[str, Any] = {
            "default_units": current["default_units"],
            "parts": dict(current["parts"]),
        }
        if default_units is not None:
            if not isinstance(default_units, (int, float)) or isinstance(default_units, bool) or default_units <= 0:
                raise ValueError("default_units must be a positive number")
            merged["default_units"] = float(default_units)
        if parts is not None:
            cleaned: dict[str, float] = {}
            for part_id, units in parts.items():
                key = str(part_id or "").strip()
                if not key:
                    continue
                if not isinstance(units, (int, float)) or isinstance(units, bool) or units <= 0:
                    raise ValueError(f"fill units for '{key}' must be a positive number")
                cleaned[key] = float(units)
            merged["parts"] = cleaned
        with db.connect(_createTables) as conn:
            local_state.write_entry(conn, _STATE_KEY, merged)
            conn.commit()
        global _cache
        _cache = (db.local_state_db_path(), merged)
        return dict(merged)


def part_volume(part_id: Any) -> float:
    """Units one piece of the given part adds to a bin. Unknown, empty or
    unclassified pieces fall back to default_units."""
    config = get_fill_config()
    key = str(part_id or "").strip()
    if not key:
        return float(config["default_units"])
    return float(config["parts"].get(key, config["default_units"]))


def cache_invalidate() -> None:
    global _cache
    with _lock:
        _cache = None
