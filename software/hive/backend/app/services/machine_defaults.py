"""The defaults every sorter starts from, held by Hive.

A sorter keeps its own copy of every default in its code, so it works with no
Hive at all. It also asks its primary Hive for this block (GET
/api/machine/defaults, announced by `defaults_version` on every heartbeat
reply), and where the block has a value it takes that instead of its own; a
setting the person saved still wins. So a default changes across the fleet
without a sorter release: here, in Hive's code (a Hive release), or as an
override an admin sets, live.

BASE_DEFAULTS mirrors the sorter's own defaults, namespace by namespace:

- sharing: whether each optional stream is shared (the sorter's sharing.py).
- steppers: each motor's TMC2209 driver settings; "*" for every motor, then a
  motor's own (the sorter's hardware_settings/steppers.py: FIELDS and
  MOTOR_DEFAULTS).
- sample_capture: the training-sample capture (the sorter's sample_collector.py).

An override replaces one leaf (`steppers.chute.sgthrs`) and must name a leaf
BASE_DEFAULTS has, with a value of the same type.

The block's version is a hash of what it holds, so a machine can tell in one
heartbeat whether to fetch it again.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.machine_default_override import MachineDefaultOverride

BASE_DEFAULTS: dict[str, Any] = {
    "sharing": {
        "piece_records": True,
        "piece_images": True,
        "camera_frames": True,
        "channel_crops": True,
        "feeder_logs": True,
        "network": True,
    },
    "steppers": {
        "*": {
            "irun": 16,
            "ihold": 4,
            "ihold_delay": 8,
            "microsteps": 8,
            "stealthchop": True,
            "coolstep": False,
            "stallguard": False,
            "stallguard_auto": False,
            "sgthrs": 50,
            "tcoolthrs": 150,
        },
        "c_channel_1": {"irun": 4, "ihold": 1},
        "c_channel_2": {"irun": 4, "ihold": 1},
        "c_channel_3": {"irun": 4, "ihold": 1},
        "carousel": {"irun": 8, "ihold": 1, "stallguard": True, "sgthrs": 148, "tcoolthrs": 150},
        "chute": {"stallguard": True, "sgthrs": 55, "tcoolthrs": 150},
    },
    "sample_capture": {
        "enabled": False,
        "interval_s": 120.0,
        "annotate": True,
        "decay_enabled": True,
    },
}

# Every process reads the overrides at most this often.
CACHE_TTL_S = 30.0

_cache_lock = threading.Lock()
_cache: tuple[float, dict[str, Any]] | None = None


class MachineDefaultsError(ValueError):
    """An override that names no default, or has the wrong type."""


def _leaf(path: str) -> Any:
    node: Any = BASE_DEFAULTS
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            raise MachineDefaultsError(f"There is no default '{path}'.")
        node = node[part]
    if isinstance(node, dict):
        raise MachineDefaultsError(f"'{path}' is a group of defaults, not one.")
    return node


def _checked(path: str, value: Any) -> Any:
    base = _leaf(path)
    if isinstance(base, bool):
        ok = isinstance(value, bool)
    elif isinstance(base, int):
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif isinstance(base, float):
        ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        value = float(value) if ok else value
    else:
        ok = isinstance(value, type(base))
    if not ok:
        raise MachineDefaultsError(f"'{path}' takes a {type(base).__name__}, not {value!r}.")
    return value


def _apply(block: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = block
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _version(defaults: dict[str, Any]) -> str:
    encoded = json.dumps(defaults, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()[:16]


def _compute(db: Session) -> dict[str, Any]:
    defaults = copy.deepcopy(BASE_DEFAULTS)
    overrides = db.query(MachineDefaultOverride).order_by(MachineDefaultOverride.path).all()
    for row in overrides:
        try:
            _apply(defaults, row.path, _checked(row.path, row.value))
        except MachineDefaultsError:
            continue  # a default Hive's code no longer has
    return {"version": _version(defaults), "defaults": defaults}


def current(db: Session) -> dict[str, Any]:
    """{"version", "defaults"}: what every machine is served now."""
    global _cache
    with _cache_lock:
        if _cache is not None and time.monotonic() - _cache[0] < CACHE_TTL_S:
            return _cache[1]
    block = _compute(db)
    with _cache_lock:
        _cache = (time.monotonic(), block)
    return block


def invalidate() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def admin_view(db: Session) -> dict[str, Any]:
    block = _compute(db)
    overrides = db.query(MachineDefaultOverride).order_by(MachineDefaultOverride.path).all()
    return {
        **block,
        "base": BASE_DEFAULTS,
        "overrides": [
            {
                "path": row.path,
                "value": row.value,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in overrides
        ],
    }


def set_override(db: Session, path: str, value: Any, user_id: UUID | None) -> dict[str, Any]:
    """Override one default for every machine, or (value None) go back to
    Hive's own. Commits."""
    row = db.get(MachineDefaultOverride, path)
    if value is None:
        _leaf(path)
        if row is not None:
            db.delete(row)
    else:
        value = _checked(path, value)
        if row is None:
            row = MachineDefaultOverride(path=path)
            db.add(row)
        row.value = value
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by_id = user_id
    db.commit()
    invalidate()
    return admin_view(db)
