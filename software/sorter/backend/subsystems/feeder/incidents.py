from __future__ import annotations

import time
from typing import Any

# Feeder inter-channel jam. Distinct from the C4 classification "exit_stuck"
# watchdog: this fires when a DOWNSTREAM feeder channel (C2 or C3) keeps pulsing
# a piece it sees in its own drop zone but the piece never advances — because it
# is physically hung at the previous channel's exit lip (about to fall from C1
# onto C2, say), so the downstream camera reads it as "arrived" while it is
# really still on the upstream rotor. The watchdog nudges the upstream rotor a
# few times to free it; only when those nudges fail to move the piece do we
# raise THIS operator-facing incident.
FEEDER_JAM_INCIDENT_KIND = "feeder_jam"
FEEDER_JAM_SOURCE_KIND = "feeder_stuck_watchdog"


def feeder_jam_incident_active(gc: Any, *, channel_label: str | None = None) -> bool:
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
        return False
    try:
        active = runtime_stats.activeIncident()
    except Exception:
        return False
    if not (
        isinstance(active, dict)
        and active.get("kind") == FEEDER_JAM_INCIDENT_KIND
        and active.get("source_kind") == FEEDER_JAM_SOURCE_KIND
    ):
        return False
    if channel_label is None:
        return True
    return str(active.get("channel_label") or "") == str(channel_label)


def publish_feeder_jam_incident(
    gc: Any,
    *,
    channel_id: int,
    channel_label: str,
    upstream_label: str,
    no_progress_ms: float,
    nudge_attempts: int,
) -> bool:
    """Raise the operator-facing feeder-jam incident: a downstream feeder channel
    stalled with a piece it could not advance and the upstream nudges failed to
    free it. Never stomps a different active incident (single slot); a repeat
    call for the SAME channel is a no-op that reports the incident is still
    ours."""
    kind = FEEDER_JAM_INCIDENT_KIND
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
        return (
            active.get("kind") == kind
            and active.get("source_kind") == FEEDER_JAM_SOURCE_KIND
            and str(active.get("channel_label") or "") == str(channel_label)
        )

    channel = f"c{int(channel_id)}"
    tried = (
        f"Nudging {upstream_label} {int(nudge_attempts)}× did not free it. "
        if int(nudge_attempts) > 0
        else ""
    )
    operator_message = (
        f"{channel_label} keeps trying to advance a piece but it is not moving — "
        f"it is likely jammed at the {upstream_label} → {channel_label} hand-off. "
        f"{tried}Clear the jam to continue."
    )
    payload: dict[str, Any] = {
        "kind": kind,
        "source_kind": FEEDER_JAM_SOURCE_KIND,
        "source": "feeder_stuck_watchdog",
        "severity": "critical",
        "status": "waiting_for_operator",
        "awaiting_operator": True,
        "scope": "feeder",
        "channel": channel,
        "role": f"c_channel_{int(channel_id)}",
        "channel_label": str(channel_label),
        "upstream_label": str(upstream_label),
        "no_progress_ms": float(no_progress_ms),
        "nudge_attempts": int(nudge_attempts),
        "triggered_at": time.time(),
        "rule": "downstream_channel_pulsing_but_piece_not_advancing",
        "resolution": "operator_clear_feeder_jam_then_auto_resumes",
        "operator_message": operator_message,
    }
    runtime_stats.setActiveIncident(payload)
    return True


def clear_feeder_jam_incident(gc: Any, *, channel_label: str | None = None) -> None:
    if not feeder_jam_incident_active(gc, channel_label=channel_label):
        return
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
        try:
            runtime_stats.clearActiveIncident(kind=FEEDER_JAM_INCIDENT_KIND)
        except Exception:
            pass


def _incident_handling_off(kind: str) -> bool:
    try:
        from toml_config import incidentHandlingOff

        return bool(incidentHandlingOff(kind))
    except Exception:
        return False
