from __future__ import annotations

import json
import sqlite3
import tomllib
from pathlib import Path
from typing import Any

from .schema import SorterConfig


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursive dict merge: override wins on leaves, dicts merge, lists replace."""
    out = dict(base)
    for key, value in override.items():
        existing = out.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            out[key] = _deep_merge(existing, value)
        else:
            out[key] = value
    return out


def _load_sqlite_overrides(sqlite_path: Path) -> dict[str, Any]:
    """Read sorter-config overrides from SQLite.

    Expected schema: a `sorter_config` table with `(key TEXT PRIMARY KEY, value TEXT)`
    rows, where `value` is a JSON blob to deep-merge into the TOML config. Missing
    table is treated as "no overrides".
    """
    if not sqlite_path.exists():
        return {}

    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT key, value FROM sorter_config"
            ).fetchall()
        except sqlite3.OperationalError:
            return {}

    merged: dict[str, Any] = {}
    for row in rows:
        try:
            parsed = json.loads(row["value"])
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        merged = _deep_merge(merged, {row["key"]: parsed})
    return merged


def load_sorter_config(
    toml_path: Path,
    sqlite_path: Path | None = None,
) -> SorterConfig:
    """Load, merge, and validate the sorter runtime configuration.

    Reads the TOML at `toml_path`, optionally deep-merges JSON overrides from a
    `sorter_config` table in `sqlite_path`, then validates via Pydantic. Any
    `ValidationError` propagates with Pydantic's default path report.
    """
    with toml_path.open("rb") as fp:
        base = tomllib.load(fp)

    if sqlite_path is not None:
        overrides = _load_sqlite_overrides(sqlite_path)
        if overrides:
            base = _deep_merge(base, overrides)

    return SorterConfig.model_validate(base)


def load_sorter_config_from_str(
    toml_text: str,
    sqlite_path: Path | None = None,
) -> SorterConfig:
    """Same as load_sorter_config but takes TOML text directly (testing convenience)."""
    base = tomllib.loads(toml_text)
    if sqlite_path is not None:
        overrides = _load_sqlite_overrides(sqlite_path)
        if overrides:
            base = _deep_merge(base, overrides)
    return SorterConfig.model_validate(base)


__all__ = ["load_sorter_config", "load_sorter_config_from_str"]
