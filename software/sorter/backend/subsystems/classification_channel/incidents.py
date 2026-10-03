from __future__ import annotations

import time
from typing import Any

CLASSIFICATION_UNRESOLVED_INCIDENT_KIND = "classification_unresolved"
CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND = "classification_multi_drop_collision"
CLASSIFICATION_INTAKE_TIMEOUT_INCIDENT_KIND = "classification_intake_request_timeout"
CLASSIFICATION_TRACK_LOST_INCIDENT_KIND = "classification_track_lost"
# The C4 stall watchdog shares the operator-facing "exit_stuck" kind (there is
# no separate "C4 piece stuck" incident); source_kind identifies the watchdog
# so its incidents are never confused with the legacy exit-release publishers.
C4_EXIT_STUCK_INCIDENT_KIND = "exit_stuck"
C4_STALL_WATCHDOG_SOURCE_KIND = "c4_stall_watchdog"


def c4_stall_incident_active(gc: Any) -> bool:
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
        return False
    try:
        active = runtime_stats.activeIncident()
    except Exception:
        return False
    return (
        isinstance(active, dict)
        and active.get("kind") == C4_EXIT_STUCK_INCIDENT_KIND
        and active.get("source_kind") == C4_STALL_WATCHDOG_SOURCE_KIND
    )


def publish_c4_exit_stuck_incident(
    gc: Any,
    *,
    stalled_ms: float,
    stalled_state: str,
    auto_clear_failed: bool = False,
    auto_clear_moved_deg: float = 0.0,
) -> bool:
    """Stall-watchdog incident: the C4 flow made NO progress (no state/phase
    change, no track-id change, no substantial piece movement) for the watchdog
    window while perception still reads a piece on the channel. Auto-clears when
    perception sees the channel clear. Never stomps a different active incident
    (single slot)."""
    kind = C4_EXIT_STUCK_INCIDENT_KIND
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
            and active.get("source_kind") == C4_STALL_WATCHDOG_SOURCE_KIND
        )

    if auto_clear_failed:
        operator_message = (
            "The classification channel stalled with a piece on it and rotating "
            f"forward {auto_clear_moved_deg:.0f}° did not clear it. Remove the piece "
            "(or clear the jam) to continue."
        )
    else:
        operator_message = (
            "The classification channel stopped making progress with a piece still "
            "on it. Remove the piece (or clear the jam) to continue."
        )
    payload: dict[str, Any] = {
        "kind": kind,
        "source_kind": C4_STALL_WATCHDOG_SOURCE_KIND,
        "source": "stall_watchdog",
        "severity": "critical",
        "status": "waiting_for_operator",
        "awaiting_operator": True,
        "scope": "classification",
        "channel": "c4",
        "role": "classification_channel",
        "channel_label": "C4",
        "stalled_ms": float(stalled_ms),
        "stalled_state": str(stalled_state),
        "auto_clear_failed": bool(auto_clear_failed),
        "triggered_at": time.time(),
        "rule": "c4_no_progress_with_piece_on_channel",
        "resolution": "operator_clear_stuck_c4_piece_then_auto_resumes",
        "operator_message": operator_message,
    }
    if auto_clear_failed:
        payload["auto_clear_moved_deg"] = float(auto_clear_moved_deg)
    runtime_stats.setActiveIncident(payload)
    return True


def record_c4_exit_stuck_auto_resolved(
    gc: Any,
    *,
    stalled_ms: float,
    stalled_state: str,
    moved_deg: float,
) -> None:
    """Log a C4 stall that the automatic watchdog cleared on its own — it rotated
    the channel forward until perception saw it empty, so it never escalated to
    an operator-facing hold. Recorded as a resolved incident (never occupies the
    active slot) so the durable log and the dashboard still reflect that it
    happened and how it was cleared. Only reached in automatic mode after a
    successful clear, so there is no off-mode gate here."""
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is None or not hasattr(runtime_stats, "recordAutoResolvedIncident"):
        return
    now = time.time()
    runtime_stats.recordAutoResolvedIncident(
        {
            "kind": C4_EXIT_STUCK_INCIDENT_KIND,
            "source_kind": C4_STALL_WATCHDOG_SOURCE_KIND,
            "source": "stall_watchdog",
            "severity": "critical",
            "status": "auto_resolved",
            "awaiting_operator": False,
            "scope": "classification",
            "channel": "c4",
            "role": "classification_channel",
            "channel_label": "C4",
            "stalled_ms": float(stalled_ms),
            "stalled_state": str(stalled_state),
            "auto_clear_failed": False,
            "auto_clear_moved_deg": float(moved_deg),
            "triggered_at": now - max(0.0, float(stalled_ms)) / 1000.0,
            "resolved_at": now,
            "rule": "c4_no_progress_with_piece_on_channel",
            "resolution": "auto_cleared_by_advancing_channel",
            "operator_message": (
                "The classification channel stalled with a piece on it; the machine "
                f"rotated it forward {moved_deg:.0f}° to clear it and resumed on its own."
            ),
        },
        resolved_by="auto",
    )


def clear_c4_exit_stuck_incident(gc: Any) -> None:
    if not c4_stall_incident_active(gc):
        return
    runtime_stats = getattr(gc, "runtime_stats", None)
    if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
        try:
            runtime_stats.clearActiveIncident(kind=C4_EXIT_STUCK_INCIDENT_KIND)
        except Exception:
            pass


def _incident_handling_off(kind: str) -> bool:
    try:
        from toml_config import incidentHandlingOff

        return bool(incidentHandlingOff(kind))
    except Exception:
        return False
