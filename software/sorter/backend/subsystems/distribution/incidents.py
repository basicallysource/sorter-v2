from __future__ import annotations

import time
from typing import Any

import server.shared_state as shared_state
from defs.events import PauseCommandData, PauseCommandEvent

# A bin reached its layer's ``max_pieces_per_bin``. Manual by design: the
# operator has to physically empty the bin, and the only thing that resolves
# the incident is marking that bin as emptied (which zeroes its count).
DISTRIBUTION_BIN_FULL_INCIDENT_KIND = "distribution_bin_full"


def _incident_handling_off(kind: str) -> bool:
    try:
        from toml_config import incidentHandlingOff

        return bool(incidentHandlingOff(kind))
    except Exception:
        return False


def bin_label(layer_index: int, section_index: int, bin_index: int) -> str:
    return f"Layer {layer_index + 1} / Section {section_index + 1} / Bin {bin_index + 1}"


def bin_full_incident_covers_bin(
    incident: Any,
    *,
    scope: str,
    layer_index: int | None = None,
    section_index: int | None = None,
    bin_index: int | None = None,
) -> bool:
    """True when ``incident`` is a bin-full incident whose bin lies inside the
    emptied scope (``all``, one ``layer`` or one ``bin``)."""
    if not isinstance(incident, dict) or incident.get("kind") != DISTRIBUTION_BIN_FULL_INCIDENT_KIND:
        return False
    if scope == "all":
        return True
    if incident.get("layer_index") != layer_index:
        return False
    if scope == "layer":
        return True
    return (
        scope == "bin"
        and incident.get("section_index") == section_index
        and incident.get("bin_index") == bin_index
    )


def publish_bin_full_incident(
    gc: Any,
    *,
    layer_index: int,
    section_index: int,
    bin_index: int,
    category_id: str,
    category_label: str,
    piece_count: int,
    max_pieces_per_bin: int,
) -> bool:
    """Raise the operator-facing bin-full incident and pause the machine.

    Never stomps a different active incident (single slot); a repeat call for
    the SAME bin is a no-op that reports the incident is still ours. Returns
    False when the kind is switched off, so callers fall back to the legacy
    "skip the full bin" routing.
    """
    kind = DISTRIBUTION_BIN_FULL_INCIDENT_KIND
    if _incident_handling_off(kind):
        return False

    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "setActiveIncident"):
        return False

    active = None
    if hasattr(runtime_stats, "activeIncident"):
        try:
            active = runtime_stats.activeIncident()
        except Exception:
            active = None
    if isinstance(active, dict):
        return bin_full_incident_covers_bin(
            active,
            scope="bin",
            layer_index=layer_index,
            section_index=section_index,
            bin_index=bin_index,
        )

    label = bin_label(layer_index, section_index, bin_index)
    runtime_stats.setActiveIncident(
        {
            "kind": kind,
            "severity": "warning",
            "status": "waiting_for_operator",
            "awaiting_operator": True,
            "scope": "distribution",
            "channel": "distribution",
            "role": "distribution_bin",
            "channel_label": "Distribution",
            "triggered_at": time.time(),
            "layer_index": int(layer_index),
            "section_index": int(section_index),
            "bin_index": int(bin_index),
            "bin_label": label,
            "category_id": str(category_id),
            "category_label": str(category_label),
            "piece_count": int(piece_count),
            "max_pieces_per_bin": int(max_pieces_per_bin),
            "detail": f"{label} ({category_label}) holds {piece_count} of {max_pieces_per_bin} pieces.",
            "rule": "bin_piece_count_reached_layer_limit",
            "resolution": "operator_empties_bin_then_marks_it_emptied",
            "operator_message": (
                f"{label} ({category_label}) is full. Empty the bin, then mark it as emptied to continue."
            ),
        }
    )
    try:
        gc.logger.warning(f"Distribution: {label} ({category_label}) is full — pausing")
    except Exception:
        pass
    try:
        if shared_state.command_queue is not None:
            shared_state.command_queue.put(PauseCommandEvent(tag="pause", data=PauseCommandData()))
    except Exception:
        pass
    return True
