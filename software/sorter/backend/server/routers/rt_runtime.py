"""rt-runtime status + lifecycle endpoints.

Exposes `/api/rt/status` which surfaces the RtRuntimeHandle's perception
runner roster, per-runner metadata, and any roles that were skipped at
bootstrap (e.g. because a camera config was missing). Used by the UI +
operators to verify that `/api/{scope}/detect/current` will actually hit
a live runner before clicking "Test Current Frame".
"""

from __future__ import annotations

import math
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException

from server import shared_state


router = APIRouter()


def _publish_runtime_state(state: str) -> None:
    irl = shared_state.getActiveIRL()
    layout = getattr(getattr(irl, "irl_config", None), "camera_layout", None)
    shared_state.publishSorterState(state, layout)


def _track_preview(batch: Any) -> List[Dict[str, Any]]:
    tracks = getattr(batch, "tracks", None) if batch is not None else None
    if not isinstance(tracks, (list, tuple)):
        return []
    out: List[Dict[str, Any]] = []
    for track in tracks[:3]:
        angle_rad = getattr(track, "angle_rad", None)
        angle_deg = None
        if isinstance(angle_rad, (int, float)):
            angle_deg = round(math.degrees(float(angle_rad)), 3)
        first_seen_ts = getattr(track, "first_seen_ts", None)
        last_seen_ts = getattr(track, "last_seen_ts", None)
        age_s = None
        if isinstance(first_seen_ts, (int, float)) and isinstance(last_seen_ts, (int, float)):
            age_s = round(max(0.0, float(last_seen_ts) - float(first_seen_ts)), 3)
        out.append({
            "global_id": getattr(track, "global_id", None),
            "confirmed_real": bool(getattr(track, "confirmed_real", False)),
            "hit_count": getattr(track, "hit_count", None),
            "score": getattr(track, "score", None),
            "age_s": age_s,
            "angle_deg": angle_deg,
        })
    return out


def _runner_entry(runner: Any) -> Dict[str, Any]:
    """Describe a single PerceptionRunner for the status payload."""
    pipeline = getattr(runner, "_pipeline", None)
    feed = getattr(pipeline, "feed", None) if pipeline is not None else None
    zone = getattr(pipeline, "zone", None) if pipeline is not None else None
    detector = getattr(pipeline, "detector", None) if pipeline is not None else None
    feed_id = getattr(feed, "feed_id", None)

    # Zone kind — keep it to a short tag so the UI doesn't need to import
    # the contract types.
    zone_kind: str | None = None
    if zone is not None:
        zone_kind = type(zone).__name__.replace("Zone", "").lower() or None

    # Latency since last frame — best-effort. CameraFeed doesn't expose a
    # direct "age" but the feed lock is cheap; avoid grabbing it if the
    # feed has no latest() helper.
    last_frame_age_ms: float | None = None
    latest_fn = getattr(feed, "latest", None) if feed is not None else None
    if callable(latest_fn):
        try:
            frame = latest_fn()
        except Exception:
            frame = None
        if frame is not None:
            monotonic_ts = getattr(frame, "monotonic_ts", None)
            if isinstance(monotonic_ts, (int, float)):
                last_frame_age_ms = max(0.0, (time.monotonic() - float(monotonic_ts)) * 1000.0)

    detection_count: int | None = None
    raw_track_count: int | None = None
    confirmed_track_count: int | None = None
    confirmed_real_track_count: int | None = None
    latest_state_fn = getattr(runner, "latest_state", None)
    if callable(latest_state_fn):
        try:
            state = latest_state_fn()
        except Exception:
            state = None
        if state is not None:
            detections = getattr(state, "detections", None)
            entries = getattr(detections, "detections", None) if detections is not None else None
            if isinstance(entries, (list, tuple)):
                detection_count = len(entries)
            raw_tracks = getattr(state, "raw_tracks", None)
            raw_entries = getattr(raw_tracks, "tracks", None) if raw_tracks is not None else None
            if isinstance(raw_entries, (list, tuple)):
                raw_track_count = len(raw_entries)
            filtered_tracks = getattr(state, "filtered_tracks", None)
            filtered_entries = (
                getattr(filtered_tracks, "tracks", None)
                if filtered_tracks is not None
                else None
            )
            if isinstance(filtered_entries, (list, tuple)):
                confirmed_track_count = len(filtered_entries)
                confirmed_real_track_count = sum(
                    1 for track in filtered_entries
                    if bool(getattr(track, "confirmed_real", False))
                )
            raw_track_preview = _track_preview(raw_tracks)
            confirmed_track_preview = _track_preview(filtered_tracks)
        else:
            raw_track_preview = []
            confirmed_track_preview = []
    else:
        raw_track_preview = []
        confirmed_track_preview = []

    return {
        "feed_id": feed_id,
        "detector_slug": getattr(detector, "key", None),
        "zone_kind": zone_kind,
        "running": bool(getattr(runner, "_running", False)),
        "last_frame_age_ms": last_frame_age_ms,
        "detection_count": detection_count,
        "raw_track_count": raw_track_count,
        "confirmed_track_count": confirmed_track_count,
        "confirmed_real_track_count": confirmed_real_track_count,
        "raw_track_preview": raw_track_preview,
        "confirmed_track_preview": confirmed_track_preview,
    }


def _slot_entry(slot: Any) -> Dict[str, int]:
    return {
        "capacity": int(slot.capacity()),
        "taken": int(slot.taken()),
        "available": int(slot.available()),
    }


@router.get("/api/rt/status")
def get_rt_status() -> Dict[str, Any]:
    """Describe the currently-active rt runtime handle.

    Returned shape::

        {
          "rt_handle_ready": bool,
          "perception_started": bool,
          "runners": [ {feed_id, detector_slug, zone_kind, running,
                         last_frame_age_ms}, ... ],
          "skipped_roles": [ {role, reason}, ... ]
        }

    Never 500s — missing state simply produces an empty rosters.
    """
    handle = shared_state.rt_handle
    if handle is None:
        return {
            "rt_handle_ready": False,
            "perception_started": False,
            "runners": [],
            "skipped_roles": [],
            "runtime_health": {},
            "runtime_debug": {},
            "slot_debug": {},
            "maintenance": {},
        }
    runners_out: List[Dict[str, Any]] = []
    for runner in getattr(handle, "perception_runners", []) or []:
        try:
            runners_out.append(_runner_entry(runner))
        except Exception:
            # One broken runner must not tank the endpoint.
            runners_out.append({
                "feed_id": None,
                "detector_slug": None,
                "zone_kind": None,
                "running": False,
                "last_frame_age_ms": None,
            })
    skipped = getattr(handle, "skipped_roles", []) or []
    orchestrator = getattr(handle, "orchestrator", None)
    health_fn = getattr(orchestrator, "health", None) if orchestrator is not None else None
    runtime_health: Dict[str, Any] = {}
    if callable(health_fn):
        try:
            runtime_health = dict(health_fn() or {})
        except Exception:
            runtime_health = {}
    runtime_debug: Dict[str, Any] = {}
    slot_debug: Dict[str, Any] = {}
    runtime_nodes = getattr(orchestrator, "_runtimes", []) if orchestrator is not None else []
    for runtime in runtime_nodes or []:
        runtime_id = getattr(runtime, "runtime_id", None)
        if not isinstance(runtime_id, str) or not runtime_id:
            continue
        debug_fn = getattr(runtime, "debug_snapshot", None)
        if callable(debug_fn):
            try:
                runtime_debug[runtime_id] = dict(debug_fn() or {})
            except Exception:
                runtime_debug[runtime_id] = {}
    slots = getattr(orchestrator, "_slots", {}) if orchestrator is not None else {}
    if isinstance(slots, dict):
        for (upstream, downstream), slot in slots.items():
            if not isinstance(upstream, str) or not isinstance(downstream, str):
                continue
            try:
                slot_debug[f"{upstream}_to_{downstream}"] = _slot_entry(slot)
            except Exception:
                slot_debug[f"{upstream}_to_{downstream}"] = {}
    maintenance: Dict[str, Any] = {}
    purge_status_fn = getattr(handle, "c234_purge_status", None)
    if callable(purge_status_fn):
        try:
            maintenance["c234_purge"] = dict(purge_status_fn() or {})
        except Exception:
            maintenance["c234_purge"] = {}
    return {
        "rt_handle_ready": True,
        "perception_started": bool(getattr(handle, "perception_started", False)),
        "started": bool(getattr(handle, "started", False)),
        "paused": bool(getattr(handle, "paused", False)),
        "runners": runners_out,
        "skipped_roles": list(skipped),
        "runtime_health": runtime_health,
        "runtime_debug": runtime_debug,
        "slot_debug": slot_debug,
        "maintenance": maintenance,
    }


@router.post("/api/rt/purge/c234")
def start_c234_purge() -> Dict[str, Any]:
    if shared_state.hardware_state != "ready":
        raise HTTPException(
            status_code=409,
            detail="hardware must be ready before running c234 purge",
        )
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    if not bool(getattr(handle, "started", False)):
        raise HTTPException(status_code=409, detail="rt runtime is not started")
    start_fn = getattr(handle, "start_c234_purge", None)
    if not callable(start_fn):
        raise HTTPException(status_code=501, detail="c234 purge is not supported")
    try:
        started = bool(start_fn(state_publisher=_publish_runtime_state))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not started:
        raise HTTPException(status_code=409, detail="c234 purge is already active")
    status_fn = getattr(handle, "c234_purge_status", None)
    status = dict(status_fn() or {}) if callable(status_fn) else {"active": True}
    return {"ok": True, "status": status}


@router.post("/api/rt/purge/c234/cancel")
def cancel_c234_purge() -> Dict[str, Any]:
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    cancel_fn = getattr(handle, "cancel_c234_purge", None)
    if not callable(cancel_fn):
        raise HTTPException(status_code=501, detail="c234 purge cancel is not supported")
    cancelled = bool(cancel_fn())
    status_fn = getattr(handle, "c234_purge_status", None)
    status = dict(status_fn() or {}) if callable(status_fn) else {"active": False}
    return {"ok": True, "cancelled": cancelled, "status": status}


__all__ = ["router"]
