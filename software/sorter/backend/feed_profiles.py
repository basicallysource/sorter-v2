"""Feed profiles: how the machine feeds and handles one kind of piece.

Small pieces such as 1x1 plates clump and slide differently from a mixed lot,
and want other pulses, gaps and holds. A profile names the settings it changes
for its kind of piece, over the feeder's tuning (C1 to C3) and the
classification channel's; everything it leaves out stays as machine.toml and
the built-in defaults have it.

ACTIVE is the one the machine runs. It is "default" (no changes) unless it is
changed here.
"""

from __future__ import annotations

from typing import Any

ACTIVE = "1x1_plates"

PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "default": {},
    # 1x1 plates ride C3 in pairs about one plate apart and fall together:
    # fewer on C2 and C3 so they spread, and finer exit pulses so the lead
    # drops without dragging the one behind it.
    "1x1_plates": {
        "feeder": {
            "ch3_max_pieces": 3,
            "ch2_max_pieces": 8,
            "exit_pulse_output_deg": 1.0,
            "exit_in_opening_max_deg": 2.0,
        },
    },
}


def overrides(section: str) -> dict[str, Any]:
    """The active profile's values for one section ("feeder" or
    "classification_channel")."""
    return dict(PROFILES.get(ACTIVE, {}).get(section, {}))
