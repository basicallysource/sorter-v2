"""Shared config I/O helpers for reading/writing machine_params.toml and bin_layout.json.

Used by hardware, steppers, and cameras routers.
"""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path
from typing import Any, Dict, List

from fastapi import HTTPException

from irl.bin_layout import getBinLayout


def _default_client_config_path(filename: str) -> str:
    return str(Path(__file__).resolve().parent.parent / filename)


def machine_params_path() -> str:
    """Return the machine params path from env, or the repo-local default."""
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if params_path:
        return params_path
    return _default_client_config_path("machine_params.toml")


def bin_layout_path() -> str:
    """Return the bin layout path from env, or the repo-local default."""
    layout_path = os.getenv("BIN_LAYOUT_PATH")
    if layout_path:
        return layout_path
    return _default_client_config_path("bin_layout.json")


def read_machine_params_config(
    *,
    require_exists: bool = False,
) -> tuple[str, Dict[str, Any]]:
    """Read and parse the machine params TOML file."""
    params_path = machine_params_path()
    if not os.path.exists(params_path):
        if require_exists:
            raise HTTPException(status_code=404, detail="Machine params file not found")
        return params_path, {}

    try:
        with open(params_path, "rb") as f:
            return params_path, tomllib.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read config: {e}")


def read_bin_layout_config() -> tuple[str, Any]:
    """Read the bin layout JSON file."""
    layout_path = bin_layout_path()
    try:
        return layout_path, getBinLayout()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read bin layout: {e}")


def toml_value(v: object) -> str:
    """Format a Python value as a TOML value string."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    if isinstance(v, list):
        return "[" + ", ".join(toml_value(item) for item in v) + "]"
    return str(v)


def _write_table(lines: List[str], prefix: str, table: Dict[str, Any]) -> None:
    """Recursively write a TOML table and its sub-tables.

    Scalar values are emitted first under `[prefix]`, then sub-dicts are
    emitted as `[prefix.key]`, and arrays of dicts as `[[prefix.key]]`.
    """
    scalars: List[tuple] = []
    sub_tables: List[tuple] = []
    array_tables: List[tuple] = []

    for k, v in table.items():
        if isinstance(v, dict):
            sub_tables.append((k, v))
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            array_tables.append((k, v))
        else:
            scalars.append((k, v))

    # Emit scalar keys under [prefix]
    if scalars:
        lines.append(f"\n[{prefix}]")
        for k, v in scalars:
            lines.append(f"{k} = {toml_value(v)}")
    elif not sub_tables and not array_tables:
        lines.append(f"\n[{prefix}]")

    # Recurse into sub-tables
    for k, v in sub_tables:
        _write_table(lines, f"{prefix}.{k}", v)

    # Emit array-of-tables
    for k, items in array_tables:
        for item in items:
            lines.append(f"\n[[{prefix}.{k}]]")
            for ik, iv in item.items():
                lines.append(f"{ik} = {toml_value(iv)}")


def write_machine_params_config(path: str, data: Dict[str, Any]) -> None:
    """Serialize a dict to TOML and write to disk."""
    lines: list[str] = []

    # Top-level scalar keys first
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {toml_value(v)}")

    # Then all table sections (recursive)
    for k, v in data.items():
        if isinstance(v, dict):
            _write_table(lines, k, v)

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_bin_layout_config(path: str, layers: List[Dict[str, Any]]) -> None:
    """Serialize bin layout to JSON and write to disk."""
    payload = {
        "layers": [
            {
                "enabled": bool(layer.get("enabled", True)),
                "sections": [
                    [layer["bin_size"]] * layer["bins_per_section"]
                    for _ in range(layer["section_count"])
                ]
            }
            for layer in layers
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
