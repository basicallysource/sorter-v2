"""How each piece is identified.

"part_and_color" is the usual: the mold provider names the part and the color
provider its color. "color_only" asks only the color model, for a lot of one
kind of piece sorted by color: the part is the one named here (a 1x1 plate,
3024), or with none named, no part at all and the piece is routed by its
color alone. Kept in machine.toml's [sorting_mode].
"""

from __future__ import annotations

from typing import Any

import machine_toml

SECTION = "sorting_mode"
PART_AND_COLOR = "part_and_color"
COLOR_ONLY = "color_only"
MODES = (PART_AND_COLOR, COLOR_ONLY)


def get(config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = machine_toml.read() if config is None else config
    table = config.get(SECTION)
    table = table if isinstance(table, dict) else {}
    mode = table.get("mode") if table.get("mode") in MODES else PART_AND_COLOR
    part = table.get("assumed_part_id")
    part = str(part).strip() if part not in (None, "") else None
    name = table.get("assumed_part_name")
    return {
        "mode": mode,
        "assumed_part_id": part,
        "assumed_part_name": str(name).strip() if part and name else None,
    }


def update(updates: dict[str, Any]) -> dict[str, Any]:
    if "mode" in updates and updates["mode"] not in MODES:
        raise ValueError(f"mode is one of {', '.join(MODES)}")
    with machine_toml.edit() as config:
        table = config.get(SECTION)
        table = dict(table) if isinstance(table, dict) else {}
        for key in ("mode", "assumed_part_id", "assumed_part_name"):
            if key in updates:
                value = updates[key]
                if value in (None, ""):
                    table.pop(key, None)
                else:
                    table[key] = str(value).strip()
        config[SECTION] = table
    return get()


def colorOnly() -> dict[str, Any] | None:
    """The color-only settings when that mode is on, else None."""
    mode = get()
    return mode if mode["mode"] == COLOR_ONLY else None
