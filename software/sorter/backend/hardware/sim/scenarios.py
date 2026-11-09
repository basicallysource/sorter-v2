"""The worlds a pretend board can start in: built-in sets of servos, or a JSON file.

A file looks like this (every key may be left out):

    {
      "speed": 1.0,
      "chute": {"start_angle": 120, "magnet_angle": 0, "magnet_width": 18, "gear_ratio": 6},
      "board_servos": [
        {"id": 1, "model": "SC15", "position": 500, "lower": 150, "upper": 850}
      ],
      "adapter_servos": []
    }

`lower` and `upper` are a servo's hard stops (the ends of a door's travel), in
the servo's counts. Brand-new servos all have ID 1.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .servos import PretendServo


def _doors(ids: list[int]) -> list[dict[str, Any]]:
    return [{"id": servo_id, "model": "SC15", "position": 500, "lower": 150, "upper": 850} for servo_id in ids]


BUILT_IN: dict[str, list[dict[str, Any]]] = {
    "empty": [],
    "one-door": _doors([1]),
    "four-doors": _doors([1, 2, 3, 4]),
    # Out of the box every servo answers to ID 1. They sit at slightly different places.
    "new-servos": [
        {"id": 1, "model": "SC15", "position": position, "lower": 150, "upper": 850} for position in (480, 510, 540)
    ],
}


def servo_list(name_or_path: str) -> list[dict[str, Any]]:
    """A built-in set by name, or the board servos of a scenario file."""
    if name_or_path in BUILT_IN:
        return [dict(entry) for entry in BUILT_IN[name_or_path]]
    return load(name_or_path).get("board_servos", [])


def load(name_or_path: str) -> dict[str, Any]:
    """A whole scenario: a built-in name (its servos on the board's bus) or a file."""
    if name_or_path in BUILT_IN:
        return {"board_servos": servo_list(name_or_path)}
    path = Path(name_or_path)
    if not path.is_file():
        names = ", ".join(sorted(BUILT_IN))
        raise ValueError(f"No scenario {name_or_path!r}: give a file, or one of {names}.")
    return json.loads(path.read_text())


def make_servo(entry: dict[str, Any]) -> PretendServo:
    known = {"id", "model", "position", "lower", "upper", "speed", "model_bytes", "label", "plugged"}
    unknown = set(entry) - known
    if unknown:
        raise ValueError(f"Unknown servo settings {sorted(unknown)}; known: {sorted(known)}.")
    model_bytes = entry.get("model_bytes")
    return PretendServo(
        servo_id=int(entry.get("id", 1)),
        model=str(entry.get("model", "SC15")),
        position=float(entry.get("position", 500)),
        lower=float(entry.get("lower", 0)),
        upper=float(entry.get("upper", 1023 if entry.get("model", "SC15").startswith("SC") else 4095)),
        speed=float(entry.get("speed", 0)),
        model_bytes=tuple(model_bytes) if model_bytes is not None else None,
        label=str(entry.get("label", "")),
        plugged=bool(entry.get("plugged", True)),
    )
