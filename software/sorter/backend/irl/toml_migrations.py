"""In-place migrations for `machine.toml`.

When we rename or remove a key in `machine.toml`, add a migration here so that
existing user machines keep booting without manual editing. Each migration
mutates the parsed `raw_toml` dict before the rest of the config loader reads
it, and prints a one-line stderr warning so the operator sees what happened.

Migrations are short-lived. Each entry has an `added` date in its comment;
once enough time has passed and the legacy key is unlikely to appear in the
wild, delete the migration. After deletion, anyone still on the old schema
gets a clean validation error from the normal parser instead of silent wrong
behavior.

To add a new migration: append a function below and add it to MIGRATIONS.
"""

from __future__ import annotations

import sys
from typing import Callable


def _migrate_use_dynamic_zones_to_mode(raw_toml: dict[str, object]) -> None:
    # added 2026-05-26; safe to remove ~2026-06-26
    section = raw_toml.get("classification_channel")
    if not isinstance(section, dict):
        return
    if "use_dynamic_zones" not in section:
        return
    legacy = section.pop("use_dynamic_zones")
    if "mode" not in section:
        section["mode"] = "dynamic" if bool(legacy) else "classic_carousel"
        print(
            f"[machine.toml migration] classification_channel.use_dynamic_zones={legacy!r} "
            f"is deprecated; migrated to classification_channel.mode={section['mode']!r}. "
            f"Please update your machine.toml.",
            file=sys.stderr,
        )
    else:
        print(
            f"[machine.toml migration] classification_channel.use_dynamic_zones={legacy!r} "
            f"is deprecated and was ignored because classification_channel.mode is already set. "
            f"Please remove use_dynamic_zones from your machine.toml.",
            file=sys.stderr,
        )


MIGRATIONS: list[Callable[[dict[str, object]], None]] = [
    _migrate_use_dynamic_zones_to_mode,
]


def applyTomlMigrations(raw_toml: dict[str, object]) -> None:
    for migration in MIGRATIONS:
        migration(raw_toml)
