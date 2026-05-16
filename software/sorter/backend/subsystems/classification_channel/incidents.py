from __future__ import annotations

import time
from typing import Any

from defs.known_object import ClassificationStatus

CLASSIFICATION_UNRESOLVED_INCIDENT_KIND = "classification_unresolved"
CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND = "classification_multi_drop_collision"
CLASSIFICATION_INTAKE_TIMEOUT_INCIDENT_KIND = "classification_intake_request_timeout"
CLASSIFICATION_TRACK_LOST_INCIDENT_KIND = "classification_track_lost"


def classification_fallback_incident_kind(
    status: ClassificationStatus,
) -> str:
    if status == ClassificationStatus.multi_drop_fail:
        return CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND
    return CLASSIFICATION_UNRESOLVED_INCIDENT_KIND


def publish_classification_fallback_incident(
    gc: Any,
    *,
    piece: Any,
    status: ClassificationStatus,
    reason: str,
) -> bool:
    kind = classification_fallback_incident_kind(status)
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
    piece_uuid = str(getattr(piece, "uuid", "") or "")
    if isinstance(active, dict):
        return active.get("kind") == kind and active.get("piece_uuid") == piece_uuid

    status_value = getattr(status, "value", str(status))
    tracked_global_id = getattr(piece, "tracked_global_id", None)
    center_deg = getattr(piece, "classification_channel_zone_center_deg", None)
    exit_offset_deg = getattr(piece, "classification_channel_exit_offset_deg", None)
    payload: dict[str, Any] = {
        "kind": kind,
        "severity": (
            "critical"
            if kind == CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND
            else "warning"
        ),
        "status": "waiting_for_operator",
        "awaiting_operator": True,
        "scope": "classification",
        "channel": "c4",
        "role": "classification_channel",
        "channel_label": "C4",
        "piece_uuid": piece_uuid,
        "piece_short": piece_uuid[:8],
        "classification_status": status_value,
        "reason": str(reason),
        "triggered_at": time.time(),
        "rule": (
            "multiple_pieces_at_classification_drop"
            if kind == CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND
            else "classification_fell_back_before_drop"
        ),
        "resolution": "operator_review_classification_fallback_then_clear",
    }
    if isinstance(tracked_global_id, int):
        payload["tracked_global_id"] = int(tracked_global_id)
        payload["track_id"] = int(tracked_global_id)
    if isinstance(center_deg, (int, float)):
        payload["center_deg"] = float(center_deg)
    if isinstance(exit_offset_deg, (int, float)):
        payload["exit_offset_deg"] = float(exit_offset_deg)
    if kind == CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND:
        payload["operator_message"] = (
            "Multiple pieces reached the C4 drop area together. Inspect before continuing."
        )
    else:
        payload["operator_message"] = (
            "Classification fell back before the drop. Review if this repeats."
        )

    runtime_stats.setActiveIncident(payload)
    return True


def publish_classification_intake_timeout_incident(
    gc: Any,
    *,
    elapsed_s: float,
) -> bool:
    kind = CLASSIFICATION_INTAKE_TIMEOUT_INCIDENT_KIND
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
        return active.get("kind") == kind

    runtime_stats.setActiveIncident(
        {
            "kind": kind,
            "severity": "warning",
            "status": "waiting_for_operator",
            "awaiting_operator": True,
            "scope": "classification",
            "channel": "c4",
            "role": "classification_channel",
            "channel_label": "C4",
            "triggered_at": time.time(),
            "timeout_ms": int(max(0.0, float(elapsed_s)) * 1000.0),
            "rule": "c4_requested_piece_but_no_intake_track_arrived",
            "resolution": "operator_check_c3_to_c4_handoff_then_clear",
            "operator_message": (
                "C4 requested a piece from C3, but no intake track arrived before the timeout."
            ),
        }
    )
    return True


def publish_classification_track_lost_incident(
    gc: Any,
    *,
    piece: Any,
    reason: str,
) -> bool:
    kind = CLASSIFICATION_TRACK_LOST_INCIDENT_KIND
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
    piece_uuid = str(getattr(piece, "uuid", "") or "")
    if isinstance(active, dict):
        return active.get("kind") == kind and active.get("piece_uuid") == piece_uuid

    status = getattr(getattr(piece, "classification_status", None), "value", None)
    tracked_global_id = getattr(piece, "tracked_global_id", None)
    payload: dict[str, Any] = {
        "kind": kind,
        "severity": "warning",
        "status": "waiting_for_operator",
        "awaiting_operator": True,
        "scope": "classification",
        "channel": "c4",
        "role": "classification_channel",
        "channel_label": "C4",
        "piece_uuid": piece_uuid,
        "piece_short": piece_uuid[:8],
        "classification_status": str(status or ""),
        "reason": str(reason),
        "triggered_at": time.time(),
        "rule": "meaningful_c4_track_expired_from_stale_zone",
        "resolution": "operator_check_c4_tracking_or_clear_if_expected",
        "operator_message": (
            "A C4 track with captured evidence expired before the normal drop flow completed."
        ),
    }
    if isinstance(tracked_global_id, int):
        payload["tracked_global_id"] = int(tracked_global_id)
        payload["track_id"] = int(tracked_global_id)
    runtime_stats.setActiveIncident(payload)
    return True


def _incident_handling_off(kind: str) -> bool:
    try:
        from toml_config import incidentHandlingOff

        return bool(incidentHandlingOff(kind))
    except Exception:
        return False
