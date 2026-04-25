"""rt-runtime status + lifecycle endpoints.

Exposes `/api/rt/status` which surfaces the RtRuntimeHandle's perception
runner roster, per-runner metadata, and any roles that were skipped at
bootstrap (e.g. because a camera config was missing). Used by the UI +
operators to verify that `/api/{scope}/detect/current` will actually hit
a live runner before clicking "Test Current Frame".
"""

from __future__ import annotations

import math
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rt.pieces.identity import build_tracklet_id
from server import shared_state


router = APIRouter()

_TRACK_FEED_ALIASES = {
    "classification_channel": "c4_feed",
    "carousel": "c4_feed",
}


class SampleTransportPayload(BaseModel):
    base_interval_s: float = 2.0
    ratio: float = 2.0
    channel_rpm: Dict[str, float] | None = None
    channels: list[str] | None = None
    direct_max_speed_usteps_per_s: int | None = None
    direct_acceleration_usteps_per_s2: int | None = None
    duration_s: float | None = 600.0
    poll_s: float = 0.02


class SampleTransportUpdatePayload(BaseModel):
    base_interval_s: float | None = None
    ratio: float | None = None
    channel_rpm: Dict[str, float] | None = None
    direct_max_speed_usteps_per_s: int | None = None
    direct_acceleration_usteps_per_s2: int | None = None
    poll_s: float | None = None


class C234PurgeStartPayload(BaseModel):
    channels: list[str] | None = None
    timeout_s: float = 120.0
    clear_hold_s: float = 0.75
    poll_s: float = 0.05


class ReplayCaptureStartPayload(BaseModel):
    feed_id: str = "c4_feed"
    max_frames: int = 300
    sample_every_n: int = 1
    label: str | None = None


class RuntimeTuningPayload(BaseModel):
    channels: dict[str, dict[str, Any]] | None = None
    slots: dict[str, int] | None = None


def _publish_runtime_state(state: str) -> None:
    irl = shared_state.getActiveIRL()
    layout = getattr(getattr(irl, "irl_config", None), "camera_layout", None)
    shared_state.publishSorterState(state, layout)


def _runner_for_feed(feed_id: str) -> Any | None:
    handle = shared_state.rt_handle
    if handle is None:
        return None
    resolved = _TRACK_FEED_ALIASES.get(feed_id, feed_id)
    runners = getattr(handle, "perception_runners", None)
    if not isinstance(runners, list):
        return None
    for runner in runners:
        pipeline = getattr(runner, "_pipeline", None)
        feed = getattr(pipeline, "feed", None)
        if getattr(feed, "feed_id", None) == resolved:
            return runner
    return None


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


def _track_to_dict(
    track: Any,
    *,
    feed_id: str | None = None,
    tracker_key: str | None = None,
    tracker_epoch: str | None = None,
) -> dict[str, Any]:
    bbox = getattr(track, "bbox_xyxy", None)
    angle_rad = getattr(track, "angle_rad", None)
    embedding = getattr(track, "appearance_embedding", None)
    raw_track_id = getattr(track, "global_id", None)
    tracklet_id = None
    if (
        isinstance(feed_id, str)
        and feed_id
        and isinstance(tracker_epoch, str)
        and tracker_epoch
        and isinstance(raw_track_id, int)
    ):
        tracklet_id = build_tracklet_id(
            feed_id=feed_id,
            tracker_key=tracker_key,
            tracker_epoch=tracker_epoch,
            raw_track_id=raw_track_id,
        )
    return {
        "track_id": getattr(track, "track_id", None),
        "global_id": raw_track_id,
        "raw_track_id": raw_track_id if isinstance(raw_track_id, int) else None,
        "tracklet_id": tracklet_id,
        "current_tracklet_id": tracklet_id,
        "feed_id": feed_id,
        "tracker_key": tracker_key,
        "tracker_epoch": tracker_epoch,
        "piece_uuid": getattr(track, "piece_uuid", None),
        "bbox_xyxy": list(bbox) if isinstance(bbox, (list, tuple)) else None,
        "score": getattr(track, "score", None),
        "confirmed_real": bool(getattr(track, "confirmed_real", False)),
        "ghost": bool(getattr(track, "ghost", False)),
        "angle_rad": angle_rad if isinstance(angle_rad, (int, float)) else None,
        "angle_deg": (
            math.degrees(float(angle_rad)) if isinstance(angle_rad, (int, float)) else None
        ),
        "radius_px": getattr(track, "radius_px", None),
        "hit_count": getattr(track, "hit_count", None),
        "first_seen_ts": getattr(track, "first_seen_ts", None),
        "last_seen_ts": getattr(track, "last_seen_ts", None),
        "appearance_embedding_dim": (
            len(embedding) if isinstance(embedding, (list, tuple)) else None
        ),
    }


@router.get("/api/rt/tracks/{feed_id}")
def get_rt_tracks(feed_id: str) -> Dict[str, Any]:
    """Return the full current track snapshot for one perception feed.

    `/api/rt/status` intentionally stays compact for dashboard polling. The
    observer/debug path needs every track, so expose the same annotation
    snapshot the overlay renderer already uses.
    """
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    annotation_snapshot = getattr(handle, "annotation_snapshot", None)
    if not callable(annotation_snapshot):
        raise HTTPException(status_code=501, detail="rt track snapshots are not supported")
    requested_feed_id = feed_id
    feed_id = _TRACK_FEED_ALIASES.get(feed_id, feed_id)
    try:
        snapshot = annotation_snapshot(feed_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"rt track snapshot failed: {exc}") from exc

    tracks = tuple(getattr(snapshot, "tracks", ()) or ())
    shadow_tracks = tuple(getattr(snapshot, "shadow_tracks", ()) or ())
    zone = getattr(snapshot, "zone", None)
    resolved_feed_id = getattr(snapshot, "feed_id", feed_id)
    tracker_key = getattr(snapshot, "tracker_key", None)
    tracker_epoch = getattr(snapshot, "tracker_epoch", None)
    return {
        "feed_id": resolved_feed_id,
        "requested_feed_id": requested_feed_id,
        "tracker_key": tracker_key,
        "tracker_epoch": tracker_epoch,
        "zone_kind": type(zone).__name__ if zone is not None else None,
        "track_count": len(tracks),
        "shadow_track_count": len(shadow_tracks),
        "tracks": [
            _track_to_dict(
                track,
                feed_id=resolved_feed_id,
                tracker_key=tracker_key,
                tracker_epoch=tracker_epoch,
            )
            for track in tracks
        ],
        "shadow_tracks": [
            _track_to_dict(
                track,
                feed_id=resolved_feed_id,
                tracker_key=getattr(snapshot, "shadow_tracker_key", None),
                tracker_epoch=None,
            )
            for track in shadow_tracks
        ],
    }


@router.post("/api/rt/replay-capture/start")
def start_replay_capture(payload: ReplayCaptureStartPayload) -> Dict[str, Any]:
    runner = _runner_for_feed(payload.feed_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="perception runner not found for feed")
    start_fn = getattr(runner, "start_detector_input_capture", None)
    if not callable(start_fn):
        raise HTTPException(status_code=501, detail="replay capture is not supported")
    try:
        status = start_fn(
            max_frames=max(1, min(int(payload.max_frames), 10000)),
            sample_every_n=max(1, min(int(payload.sample_every_n), 1000)),
            label=payload.label,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "capture": status}


@router.post("/api/rt/replay-capture/{feed_id}/stop")
def stop_replay_capture(feed_id: str) -> Dict[str, Any]:
    runner = _runner_for_feed(feed_id)
    if runner is None:
        raise HTTPException(status_code=404, detail="perception runner not found for feed")
    stop_fn = getattr(runner, "stop_detector_input_capture", None)
    if not callable(stop_fn):
        raise HTTPException(status_code=501, detail="replay capture is not supported")
    status = stop_fn()
    return {"ok": True, "capture": status}


@router.get("/api/rt/replay-capture")
def get_replay_capture_status() -> Dict[str, Any]:
    handle = shared_state.rt_handle
    if handle is None:
        return {"ok": True, "captures": []}
    captures: list[dict[str, Any]] = []
    runners = getattr(handle, "perception_runners", None)
    if isinstance(runners, list):
        for runner in runners:
            status_fn = getattr(runner, "detector_input_capture_status", None)
            if not callable(status_fn):
                continue
            status = status_fn()
            if isinstance(status, dict):
                captures.append(status)
    return {"ok": True, "captures": captures}


@router.get("/api/rt/tuning")
def get_runtime_tuning() -> Dict[str, Any]:
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    status_fn = getattr(handle, "runtime_tuning_status", None)
    if not callable(status_fn):
        raise HTTPException(status_code=501, detail="runtime tuning is not supported")
    try:
        tuning = dict(status_fn() or {})
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"runtime tuning failed: {exc}") from exc
    return {"ok": True, "tuning": tuning}


@router.post("/api/rt/tuning")
def update_runtime_tuning(payload: RuntimeTuningPayload) -> Dict[str, Any]:
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    update_fn = getattr(handle, "update_runtime_tuning", None)
    if not callable(update_fn):
        raise HTTPException(status_code=501, detail="runtime tuning is not supported")
    patch: dict[str, Any] = {}
    if payload.channels is not None:
        patch["channels"] = payload.channels
    if payload.slots is not None:
        patch["slots"] = payload.slots
    try:
        tuning = dict(update_fn(patch) or {})
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, "tuning": tuning}


@router.post("/api/rt/purge/c234")
def start_c234_purge(
    payload: C234PurgeStartPayload = C234PurgeStartPayload(),
) -> Dict[str, Any]:
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
        started = bool(
            start_fn(
                state_publisher=_publish_runtime_state,
                channels=payload.channels,
                timeout_s=payload.timeout_s,
                clear_hold_s=payload.clear_hold_s,
                poll_s=payload.poll_s,
            )
        )
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


@router.post("/api/rt/sample-transport")
def start_sample_transport(
    payload: SampleTransportPayload = SampleTransportPayload(),
) -> Dict[str, Any]:
    if shared_state.hardware_state != "ready":
        raise HTTPException(
            status_code=409,
            detail="hardware must be ready before running sample transport",
        )
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    if not bool(getattr(handle, "started", False)):
        raise HTTPException(status_code=409, detail="rt runtime is not started")
    start_fn = getattr(handle, "start_sample_transport", None)
    if not callable(start_fn):
        raise HTTPException(status_code=501, detail="sample transport is not supported")
    try:
        started = bool(
            start_fn(
                state_publisher=_publish_runtime_state,
                base_interval_s=payload.base_interval_s,
                ratio=payload.ratio,
                channel_rpm=payload.channel_rpm,
                channels=payload.channels,
                direct_max_speed_usteps_per_s=payload.direct_max_speed_usteps_per_s,
                direct_acceleration_usteps_per_s2=payload.direct_acceleration_usteps_per_s2,
                duration_s=payload.duration_s,
                poll_s=payload.poll_s,
            )
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not started:
        raise HTTPException(status_code=409, detail="sample transport is already active")
    status_fn = getattr(handle, "sample_transport_status", None)
    status = dict(status_fn() or {}) if callable(status_fn) else {"active": True}
    return {"ok": True, "status": status}


@router.post("/api/rt/sample-transport/cancel")
def cancel_sample_transport() -> Dict[str, Any]:
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    cancel_fn = getattr(handle, "cancel_sample_transport", None)
    if not callable(cancel_fn):
        raise HTTPException(status_code=501, detail="sample transport cancel is not supported")
    cancelled = bool(cancel_fn())
    status_fn = getattr(handle, "sample_transport_status", None)
    status = dict(status_fn() or {}) if callable(status_fn) else {"active": False}
    return {"ok": True, "cancelled": cancelled, "status": status}


@router.post("/api/rt/sample-transport/config")
def update_sample_transport_config(
    payload: SampleTransportUpdatePayload,
) -> Dict[str, Any]:
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    update_fn = getattr(handle, "update_sample_transport", None)
    if not callable(update_fn):
        raise HTTPException(status_code=501, detail="sample transport update is not supported")
    try:
        updated = bool(
            update_fn(
                base_interval_s=payload.base_interval_s,
                ratio=payload.ratio,
                channel_rpm=payload.channel_rpm,
                direct_max_speed_usteps_per_s=payload.direct_max_speed_usteps_per_s,
                direct_acceleration_usteps_per_s2=payload.direct_acceleration_usteps_per_s2,
                poll_s=payload.poll_s,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=409, detail="sample transport is not active")
    status_fn = getattr(handle, "sample_transport_status", None)
    status = dict(status_fn() or {}) if callable(status_fn) else {"active": True}
    return {"ok": True, "status": status}


@router.post("/api/rt/c1/clear-jam")
def clear_c1_jam() -> Dict[str, Any]:
    handle = shared_state.rt_handle
    if handle is None:
        raise HTTPException(status_code=409, detail="rt runtime is not ready")
    if not bool(getattr(handle, "started", False)):
        raise HTTPException(status_code=409, detail="rt runtime is not started")
    clear_fn = getattr(handle, "clear_c1_pause", None)
    if not callable(clear_fn):
        raise HTTPException(status_code=501, detail="c1 jam clearing is not supported")
    try:
        result = dict(clear_fn() or {})
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True, **result}


__all__ = ["router"]
