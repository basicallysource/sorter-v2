"""Feed profiles: how the machine feeds and handles one kind of piece.

Small pieces such as 1x1 plates clump and slide differently from a mixed lot,
and want other pulses, gaps and holds. A profile names the settings it changes
for its kind of piece, over the feeder's tuning (C1 to C3) and the
classification channel's; everything it leaves out stays as machine.toml and
the built-in defaults have it.

PRESETS are defined here, as each is tuned on a machine. Others are made on
the Settings > Sorting page and kept in machine.toml ([feed_profiles.<id>]).
[feed_profile] active names the one the machine runs; with none, "default",
which changes nothing.
"""

from __future__ import annotations

import re
import time
from typing import Any, Mapping

import machine_toml

DEFAULT = "default"
SECTIONS = ("feeder", "classification_channel")

PRESETS: dict[str, dict[str, Any]] = {
    DEFAULT: {
        "label": "Default",
        "description": "A mixed lot of every size: the machine's own settings, unchanged.",
    },
    "1x1_plates": {
        "label": "1x1 plates",
        "description": (
            "Tiny pieces that ride C3 in pairs about one plate apart and fall together: fewer "
            "pieces on C2 and C3 so they spread out, and finer exit pulses so the lead drops "
            "without dragging the one behind it."
        ),
        "feeder": {
            "ch3_max_pieces": 3,
            "ch2_max_pieces": 8,
            "exit_pulse_output_deg": 1.0,
            "exit_in_opening_max_deg": 2.0,
            "exit_move_margin_deg": 6.0,
        },
    },
}

STORED = "feed_profiles"
ACTIVE = "feed_profile"


def _stored(config: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    table = config.get(STORED)
    return {k: v for k, v in table.items() if isinstance(v, dict)} if isinstance(table, dict) else {}


def activeId(config: Mapping[str, Any] | None = None) -> str:
    config = machine_toml.read() if config is None else config
    table = config.get(ACTIVE)
    pid = table.get("active") if isinstance(table, dict) else None
    if isinstance(pid, str) and (pid in PRESETS or pid in _stored(config)):
        return pid
    return DEFAULT


def _profile(pid: str, config: Mapping[str, Any]) -> dict[str, Any]:
    return PRESETS.get(pid) or _stored(config).get(pid) or PRESETS[DEFAULT]


def overrides(section: str, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The active profile's values for one section ("feeder" or
    "classification_channel")."""
    config = machine_toml.read() if config is None else config
    values = _profile(activeId(config), config).get(section)
    return dict(values) if isinstance(values, dict) else {}


def listProfiles() -> dict[str, Any]:
    config = machine_toml.read()
    active = activeId(config)

    def row(pid: str, entry: dict[str, Any], preset: bool) -> dict[str, Any]:
        return {
            "id": pid,
            "label": entry.get("label") or pid,
            "description": entry.get("description") or "",
            "preset": preset,
            "active": pid == active,
            "values": {s: dict(entry.get(s) or {}) for s in SECTIONS},
        }

    rows = [row(pid, entry, True) for pid, entry in PRESETS.items()]
    rows += [row(pid, entry, False) for pid, entry in sorted(_stored(config).items()) if pid not in PRESETS]
    return {"active": active, "profiles": rows}


def setActive(profile_id: str) -> dict[str, Any]:
    config = machine_toml.read()
    if profile_id not in PRESETS and profile_id not in _stored(config):
        raise KeyError(profile_id)
    with machine_toml.edit() as config:
        config[ACTIVE] = {"active": profile_id}
    return listProfiles()


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_") or f"profile_{int(time.time())}"


def saveProfile(label: str, description: str, values: Mapping[str, Mapping[str, Any]], profile_id: str | None = None) -> dict[str, Any]:
    """Keep a profile of one's own: its name and the settings it changes."""
    label = label.strip()
    if not label:
        raise ValueError("A profile needs a name.")
    pid = profile_id or _slug(label)
    if pid in PRESETS:
        raise ValueError("A preset is changed in the code, not here; save it under a new name.")
    entry: dict[str, Any] = {"label": label, "description": description.strip(), "saved_at": time.time()}
    for section in SECTIONS:
        table = values.get(section) if isinstance(values, Mapping) else None
        if isinstance(table, Mapping) and table:
            entry[section] = dict(table)
    with machine_toml.edit() as config:
        stored = config.get(STORED)
        stored = dict(stored) if isinstance(stored, dict) else {}
        stored[pid] = entry
        config[STORED] = stored
    return listProfiles()


def deleteProfile(profile_id: str) -> dict[str, Any]:
    if profile_id in PRESETS:
        raise ValueError("A preset is removed in the code.")
    with machine_toml.edit() as config:
        stored = config.get(STORED)
        stored = dict(stored) if isinstance(stored, dict) else {}
        stored.pop(profile_id, None)
        config[STORED] = stored
        table = config.get(ACTIVE)
        if isinstance(table, dict) and table.get("active") == profile_id:
            config[ACTIVE] = {"active": DEFAULT}
    return listProfiles()
