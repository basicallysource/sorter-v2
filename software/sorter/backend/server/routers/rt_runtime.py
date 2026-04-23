"""rt-runtime status + lifecycle endpoints.

Exposes `/api/rt/status` which surfaces the RtRuntimeHandle's perception
runner roster, per-runner metadata, and any roles that were skipped at
bootstrap (e.g. because a camera config was missing). Used by the UI +
operators to verify that `/api/{scope}/detect/current` will actually hit
a live runner before clicking "Test Current Frame".
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from server import shared_state


router = APIRouter()


def _publish_runtime_state(state: str) -> None:
    irl = shared_state.getActiveIRL()
    layout = getattr(getattr(irl, "irl_config", None), "camera_layout", None)
    shared_state.publishSorterState(state, layout)


def _empty_status(*, ready: bool) -> Dict[str, Any]:
    return {
        "rt_handle_ready": ready,
        "perception_started": False,
        "started": False,
        "paused": False,
        "runners": [],
        "skipped_roles": [],
        "runtime_health": {},
        "runtime_debug": {},
        "slot_debug": {},
        "maintenance": {},
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
        return _empty_status(ready=False)
    payload = _empty_status(ready=True)
    status_snapshot = getattr(handle, "status_snapshot", None)
    if callable(status_snapshot):
        try:
            snapshot = status_snapshot()
        except Exception:
            snapshot = None
        if isinstance(snapshot, dict):
            payload.update(snapshot)
    else:
        payload["perception_started"] = bool(getattr(handle, "perception_started", False))
        payload["started"] = bool(getattr(handle, "started", False))
        payload["paused"] = bool(getattr(handle, "paused", False))
        payload["skipped_roles"] = list(getattr(handle, "skipped_roles", []) or [])
    payload["rt_handle_ready"] = True
    return payload


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
