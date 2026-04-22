"""FastAPI router exposing the shadow-mode runner state.

Bridge-import: reads ``backend.server.shared_state`` for the per-role
``PerceptionRunner`` + ``RollingIouTracker`` dicts populated by
``main.py``. That dependency is **temporary** for Phase 2b while the
legacy server is still in charge; Phase 3+ will expose these through the
new ``RuntimeContext``/``Orchestrator`` facade.

Endpoints (mounted by ``server/api.py`` under the ``/api/rt/shadow``
prefix):

* ``GET /status``              — global status (roles, runner health,
                                 current IoU per role)
* ``GET /tracks/{role}``       — latest :class:`TrackBatch` for a role
                                 as JSON

When no shadow runners are active (``RT_SHADOW_FEEDS`` unset) every
endpoint returns an empty/disabled shape rather than 4xx — the UI can
poll safely from any machine.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException


router = APIRouter()


def _shadow_runners() -> dict[str, Any]:
    try:
        from server import shared_state  # bridge-import
    except Exception:
        return {}
    runners = getattr(shared_state, "shadow_runners", None)
    return runners if isinstance(runners, dict) else {}


def _shadow_iou() -> dict[str, Any]:
    try:
        from server import shared_state  # bridge-import
    except Exception:
        return {}
    iou = getattr(shared_state, "shadow_iou", None)
    return iou if isinstance(iou, dict) else {}


def _iou_snapshot_for_role(role: str) -> dict[str, Any]:
    tracker = _shadow_iou().get(role)
    if tracker is None:
        return {"mean_iou": 0.0, "sample_count": 0, "window_sec": 0.0}
    snapshot_fn = getattr(tracker, "snapshot", None)
    if not callable(snapshot_fn):
        return {"mean_iou": 0.0, "sample_count": 0, "window_sec": 0.0}
    try:
        snapshot = snapshot_fn()
    except Exception:
        return {"mean_iou": 0.0, "sample_count": 0, "window_sec": 0.0}
    if not isinstance(snapshot, dict):
        return {"mean_iou": 0.0, "sample_count": 0, "window_sec": 0.0}
    return {
        "mean_iou": float(snapshot.get("mean_iou", 0.0) or 0.0),
        "sample_count": int(snapshot.get("sample_count", 0) or 0),
        "window_sec": float(snapshot.get("window_sec", 0.0) or 0.0),
    }


def _runner_health(runner: Any) -> dict[str, Any]:
    running = bool(getattr(runner, "_running", False))
    name = str(getattr(runner, "_name", ""))
    # We deliberately avoid reading private state beyond what the runner
    # already exposes for observability.
    latest = None
    latest_fn = getattr(runner, "latest_tracks", None)
    if callable(latest_fn):
        try:
            batch = latest_fn()
        except Exception:
            batch = None
        if batch is not None:
            latest = {
                "feed_id": str(getattr(batch, "feed_id", "")),
                "frame_seq": int(getattr(batch, "frame_seq", 0)),
                "timestamp": float(getattr(batch, "timestamp", 0.0)),
                "track_count": len(getattr(batch, "tracks", []) or ()),
            }
    return {"running": running, "name": name, "latest": latest}


def _track_to_dict(track: Any) -> dict[str, Any]:
    bbox = getattr(track, "bbox_xyxy", None) or (0, 0, 0, 0)
    try:
        x1, y1, x2, y2 = bbox
    except (TypeError, ValueError):
        x1 = y1 = x2 = y2 = 0
    return {
        "track_id": int(getattr(track, "track_id", 0) or 0),
        "global_id": (
            int(getattr(track, "global_id"))
            if getattr(track, "global_id", None) is not None
            else None
        ),
        "piece_uuid": getattr(track, "piece_uuid", None),
        "bbox_xyxy": [int(x1), int(y1), int(x2), int(y2)],
        "score": float(getattr(track, "score", 0.0) or 0.0),
        "confirmed_real": bool(getattr(track, "confirmed_real", False)),
        "angle_rad": (
            float(getattr(track, "angle_rad"))
            if getattr(track, "angle_rad", None) is not None
            else None
        ),
        "radius_px": (
            float(getattr(track, "radius_px"))
            if getattr(track, "radius_px", None) is not None
            else None
        ),
        "hit_count": int(getattr(track, "hit_count", 0) or 0),
        "first_seen_ts": float(getattr(track, "first_seen_ts", 0.0) or 0.0),
        "last_seen_ts": float(getattr(track, "last_seen_ts", 0.0) or 0.0),
    }


@router.get("/status")
def get_shadow_status() -> dict[str, Any]:
    """Return the shadow-mode state for every active role."""
    runners = _shadow_runners()
    iou = _shadow_iou()
    roles = sorted(set(runners.keys()) | set(iou.keys()))
    enabled = len(roles) > 0
    per_role: list[dict[str, Any]] = []
    for role in roles:
        runner = runners.get(role)
        per_role.append(
            {
                "role": role,
                "health": _runner_health(runner) if runner is not None else {
                    "running": False,
                    "name": "",
                    "latest": None,
                },
                "iou": _iou_snapshot_for_role(role),
            }
        )
    return {
        "enabled": enabled,
        "roles": per_role,
    }


@router.get("/tracks/{role}")
def get_shadow_tracks(role: str) -> dict[str, Any]:
    """Return the latest :class:`TrackBatch` for ``role``, or an empty one."""
    runners = _shadow_runners()
    runner = runners.get(role)
    if runner is None:
        # Empty-but-shape-valid rather than 404 so the UI never has to
        # decide "is the role configured?" before rendering.
        return {
            "role": role,
            "available": False,
            "feed_id": None,
            "frame_seq": None,
            "timestamp": None,
            "tracks": [],
            "lost_track_ids": [],
            "iou": _iou_snapshot_for_role(role),
        }
    latest_fn = getattr(runner, "latest_tracks", None)
    batch = latest_fn() if callable(latest_fn) else None
    if batch is None:
        return {
            "role": role,
            "available": True,
            "feed_id": None,
            "frame_seq": None,
            "timestamp": None,
            "tracks": [],
            "lost_track_ids": [],
            "iou": _iou_snapshot_for_role(role),
        }
    tracks = getattr(batch, "tracks", ()) or ()
    try:
        track_dicts = [_track_to_dict(t) for t in tracks]
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"track serialization failed: {exc}")
    return {
        "role": role,
        "available": True,
        "feed_id": str(getattr(batch, "feed_id", "")),
        "frame_seq": int(getattr(batch, "frame_seq", 0) or 0),
        "timestamp": float(getattr(batch, "timestamp", 0.0) or 0.0),
        "tracks": track_dicts,
        "lost_track_ids": [int(x) for x in getattr(batch, "lost_track_ids", ()) or ()],
        "iou": _iou_snapshot_for_role(role),
    }


__all__ = ["router"]
