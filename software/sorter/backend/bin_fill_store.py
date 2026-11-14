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
#
# Per-part units come from two sources: the operator's manual `parts` map
# (always wins), and `learned` entries the machine fills in by itself. At
# distribution time each classified piece carries its catalog bbox from Hive
# piece metadata (the same dims the oversize check uses); that bbox volume is
# folded into a running mean per part, so the table grows to cover the parts
# actually running through the machine without anyone typing anything.

_STATE_KEY = "bin_fill_units"
_DEFAULT_UNITS = 1.0

# The bbox of the reference piece (a 2x4 brick) in mm: 32 x 16 x 11.2. Only
# ratios matter — a slightly off reference scales every learned unit uniformly.
_REFERENCE_VOLUME_MM3 = 32.0 * 16.0 * 11.2
# The learned map is flushed to the state database at most every N new
# measurements, so a sorting run does not write it once per piece.
_FLUSH_EVERY_N_MEASUREMENTS = 20

_lock = threading.RLock()
_cache: tuple[str, dict[str, Any]] | None = None
_dirty_measurements = 0


def _createTables(conn) -> None:
    local_state.create_tables(conn)


def _normalize_config(raw: Any) -> dict[str, Any]:
    config: dict[str, Any] = {"default_units": _DEFAULT_UNITS, "parts": {}, "learned": {}}
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
    learned = raw.get("learned")
    if isinstance(learned, dict):
        for part_id, entry in learned.items():
            key = str(part_id or "").strip()
            if not key or not isinstance(entry, dict):
                continue
            volume = entry.get("volume_mm3")
            samples = entry.get("samples")
            if (
                isinstance(volume, (int, float))
                and not isinstance(volume, bool)
                and volume > 0
                and isinstance(samples, int)
                and not isinstance(samples, bool)
                and samples > 0
            ):
                config["learned"][key] = {"volume_mm3": float(volume), "samples": int(samples)}
    return config


def learned_units(learned: dict[str, Any]) -> float:
    return float(learned["volume_mm3"]) / _REFERENCE_VOLUME_MM3


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
            # Learned entries are the machine's own measurements — a manual
            # save of default/parts must never drop them.
            "learned": dict(current["learned"]),
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
    """Units one piece of the given part adds to a bin. The operator's manual
    map wins over the learned entries; unknown, empty or unclassified pieces
    fall back to default_units."""
    config = get_fill_config()
    key = str(part_id or "").strip()
    if not key:
        return float(config["default_units"])
    manual = config["parts"].get(key)
    if manual is not None:
        return float(manual)
    learned = config["learned"].get(key)
    if learned is not None:
        return learned_units(learned)
    return float(config["default_units"])


def learn_from_piece(piece: dict[str, Any]) -> bool:
    """Fold a distributed piece's catalog bbox into the learned per-part
    volumes. Returns True when a measurement was recorded. Runs on the
    distribution write path — dict lookups only, and the state database is
    touched at most every _FLUSH_EVERY_N_MEASUREMENTS new measurements."""
    global _dirty_measurements
    if not isinstance(piece, dict):
        return False
    part_id = str(piece.get("part_id") or "").strip()
    if not part_id:
        return False
    metadata = piece.get("piece_metadata")
    dims = metadata.get("dimensions") if isinstance(metadata, dict) else None
    if not isinstance(dims, dict):
        return False
    axes = []
    for name in ("bbox_x_mm", "bbox_y_mm", "bbox_z_mm"):
        value = dims.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            return False
        axes.append(float(value))
    volume_mm3 = axes[0] * axes[1] * axes[2]

    with _lock:
        config = get_fill_config()
        learned = config["learned"]
        entry = learned.get(part_id)
        if entry is None:
            learned[part_id] = {"volume_mm3": volume_mm3, "samples": 1}
        else:
            samples = int(entry["samples"]) + 1
            # Count-weighted running mean over the bbox volume.
            mean = (float(entry["volume_mm3"]) * int(entry["samples"]) + volume_mm3) / samples
            entry["volume_mm3"] = mean
            entry["samples"] = samples
        _dirty_measurements += 1
        if _dirty_measurements >= _FLUSH_EVERY_N_MEASUREMENTS:
            _flush_learned_locked(config)
    return True


def _flush_learned_locked(config: dict[str, Any]) -> None:
    global _dirty_measurements
    with db.connect(_createTables) as conn:
        local_state.write_entry(
            conn,
            _STATE_KEY,
            {
                "default_units": config["default_units"],
                "parts": config["parts"],
                "learned": config["learned"],
            },
        )
        conn.commit()
    _dirty_measurements = 0


def flush_learned() -> None:
    """Persist pending learned measurements now (fill-config reads, tests)."""
    with _lock:
        if _dirty_measurements == 0:
            return
        config = get_fill_config()
        _flush_learned_locked(config)


def cache_invalidate() -> None:
    global _cache, _dirty_measurements
    with _lock:
        _cache = None
        _dirty_measurements = 0
