"""Feed profiles: how the machine feeds and handles one kind of piece.

A profile is a named copy of the feeder's tuning (C1 to C3) and the
classification channel's, one per kind of piece the machine is given: small
pieces such as 1x1 plates clump and slide differently from a mixed lot, and
want other pulses, gaps and holds. Picking one writes its values over the two
tuning sections; saving one copies what the machine runs now.

machine.toml keeps them: [feed_profiles.<id>] holds a label and one table per
section, and [feed_profile] active names the one last picked.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable

import machine_toml
from toml_config import (
    getClassificationChannelRev01Config,
    getPulsePerceptionConfig,
    setClassificationChannelRev01Config,
    setPulsePerceptionConfig,
)

PROFILES = "feed_profiles"
ACTIVE = "feed_profile"

# Each section a profile holds: its getter and setter.
SECTIONS: dict[str, tuple[Callable[[], dict[str, Any]], Callable[[dict[str, Any]], dict[str, Any]]]] = {
    "feeder": (getPulsePerceptionConfig, setPulsePerceptionConfig),
    "classification_channel": (getClassificationChannelRev01Config, setClassificationChannelRev01Config),
}


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
    return slug or f"profile-{int(time.time())}"


def _current() -> dict[str, dict[str, Any]]:
    return {name: get() for name, (get, _) in SECTIONS.items()}


def _changes(values: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Every value the profile sets that differs from what the machine runs."""
    out = []
    for section, table in values.items():
        now = current.get(section, {})
        for key, value in table.items():
            if key in now and now[key] != value:
                out.append({"section": section, "key": key, "profile": value, "current": now[key]})
    return out


def listProfiles() -> dict[str, Any]:
    config = machine_toml.read()
    stored = config.get(PROFILES)
    stored = stored if isinstance(stored, dict) else {}
    active_table = config.get(ACTIVE)
    active = active_table.get("active") if isinstance(active_table, dict) else None
    current = _current()
    profiles = []
    for pid, entry in stored.items():
        if not isinstance(entry, dict):
            continue
        values = {s: dict(entry.get(s) or {}) for s in SECTIONS}
        changes = _changes(values, current)
        profiles.append(
            {
                "id": pid,
                "label": entry.get("label") or pid,
                "description": entry.get("description") or "",
                "saved_at": entry.get("saved_at"),
                "active": pid == active,
                "matches": not changes,
                "changes": changes,
            }
        )
    profiles.sort(key=lambda p: p["label"].lower())
    return {"active": active if active in stored else None, "profiles": profiles}


def saveProfile(label: str, description: str = "", profile_id: str | None = None) -> dict[str, Any]:
    """Copy what the machine runs now into a profile (a new one, or over
    ``profile_id``), and make it the active one."""
    label = label.strip()
    if not label:
        raise ValueError("A profile needs a name.")
    pid = profile_id or _slug(label)
    current = _current()
    with machine_toml.edit() as config:
        stored = config.get(PROFILES)
        stored = dict(stored) if isinstance(stored, dict) else {}
        stored[pid] = {"label": label, "description": description.strip(), "saved_at": time.time(), **current}
        config[PROFILES] = stored
        config[ACTIVE] = {"active": pid}
    return listProfiles()


def applyProfile(profile_id: str) -> dict[str, Any]:
    """Write a profile's values over the tuning sections. The feeder takes them
    within a second; the classification channel at its next start."""
    config = machine_toml.read()
    stored = config.get(PROFILES)
    entry = stored.get(profile_id) if isinstance(stored, dict) else None
    if not isinstance(entry, dict):
        raise KeyError(profile_id)
    for section, (_, setter) in SECTIONS.items():
        values = entry.get(section)
        if isinstance(values, dict) and values:
            setter(dict(values))
    with machine_toml.edit() as config:
        config[ACTIVE] = {"active": profile_id}
    return listProfiles()


def deleteProfile(profile_id: str) -> dict[str, Any]:
    with machine_toml.edit() as config:
        stored = config.get(PROFILES)
        stored = dict(stored) if isinstance(stored, dict) else {}
        stored.pop(profile_id, None)
        config[PROFILES] = stored
        active_table = config.get(ACTIVE)
        if isinstance(active_table, dict) and active_table.get("active") == profile_id:
            config[ACTIVE] = {}
    return listProfiles()
