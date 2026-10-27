"""What this sorter shares with each Hive (sharing.py), the person's agreement
to it, and what was uploaded, hour by hour (upload_stats.py): the Data page."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import channel_crop_store
import control_data_store
import local_state
import piece_image_store
import sample_store
import sharing
import telemetry_store
import upload_stats
from server import shared_state

router = APIRouter()

# The local storage summary counts every store's rows; the page polls.
LOCAL_SUMMARY_TTL_S = 60.0
_local_lock = threading.Lock()
_local_cached: tuple[float, dict[str, Any]] | None = None


def _targets() -> tuple[list[dict[str, Any]], Optional[str]]:
    config = local_state.get_hive_config() or {}
    targets = [dict(target) for target in config.get("targets", []) if isinstance(target, dict)]
    primary = config.get("primary_target_id")
    return targets, primary if isinstance(primary, str) else None


def _view() -> Dict[str, Any]:
    targets, primary = _targets()
    return sharing.view(targets, primary)


def _knownTarget(target_id: str) -> None:
    targets, _primary = _targets()
    if not any(target.get("id") == target_id for target in targets):
        raise HTTPException(404, "Unknown Hive.")


@router.get("/api/sharing")
def get_sharing() -> Dict[str, Any]:
    return _view()


class SharingPayload(BaseModel):
    # None: every Hive. A target's id: that Hive's overrides.
    target_id: Optional[str] = None
    values: Dict[str, bool] = {}


@router.post("/api/sharing")
def set_sharing(payload: SharingPayload) -> Dict[str, Any]:
    try:
        if payload.target_id is None:
            sharing.setEveryHive(payload.values)
        else:
            _knownTarget(payload.target_id)
            sharing.setForTarget(payload.target_id, payload.values)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _view()


class SharingResetPayload(BaseModel):
    target_id: Optional[str] = None


@router.post("/api/sharing/reset")
def reset_sharing(payload: SharingResetPayload) -> Dict[str, Any]:
    if payload.target_id is None:
        sharing.resetEveryHive()
    else:
        _knownTarget(payload.target_id)
        sharing.resetTarget(payload.target_id)
    return _view()


class ConsentPayload(BaseModel):
    version: int
    values: Dict[str, bool] = {}


@router.post("/api/sharing/consent")
def record_consent(payload: ConsentPayload) -> Dict[str, Any]:
    try:
        sharing.recordConsent(payload.version, payload.values)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _view()


def _localSummary() -> dict[str, Any]:
    """{"local": what each store keeps, "disk": free space}, cached a minute."""
    global _local_cached
    with _local_lock:
        if _local_cached is not None and time.monotonic() - _local_cached[0] < LOCAL_SUMMARY_TTL_S:
            return _local_cached[1]
    samples = sample_store.stats()
    summary = [
        {"key": upload_stats.KIND_TELEMETRY, **telemetry_store.stats(), "cap_bytes": None},
        {"key": upload_stats.KIND_PIECE_IMAGES, **piece_image_store.storageStats()},
        {
            "key": upload_stats.KIND_SAMPLES,
            "count": samples["stored"],
            "bytes": samples["stored_bytes"],
            "cap_bytes": samples["cap_bytes"],
            "waiting": samples["not_on_every_hive"],
        },
        {"key": upload_stats.KIND_CHANNEL_CROPS, **channel_crop_store.storageStats()},
        {"key": upload_stats.KIND_CONTROL_DATA, **control_data_store.storageStats()},
    ]
    labels = {key: label for key, label, _stream in upload_stats.KINDS}
    result = {
        "local": [{**entry, "label": labels[entry["key"]]} for entry in summary],
        "disk": {"free_bytes": samples["disk_free_bytes"], "min_free_bytes": samples["min_free_bytes"]},
    }
    with _local_lock:
        _local_cached = (time.monotonic(), result)
    return result


@router.get("/api/sharing/stats")
def get_upload_stats(hours: int = Query(default=24, ge=1, le=24 * 30)) -> Dict[str, Any]:
    """Per Hive, hour by hour: what was uploaded, what never will be, what
    waited and how long the upload budget held things back; and what this
    machine keeps."""
    now = time.time()
    gc = shared_state.gc_ref
    heartbeat = getattr(gc, "hive_heartbeat", None) if gc is not None else None
    worker = getattr(gc, "hive_sync_worker", None) if gc is not None else None
    targets, _primary = _targets()
    hour_starts: list[int] = []
    out_targets = []
    for target in targets:
        series = upload_stats.series(target["id"], hours, now)
        hour_starts = series["hour_starts"]
        beat = heartbeat.status(target["id"]) if heartbeat is not None else {}
        budget = worker.budgetStatus(target["id"]) if worker is not None else None
        out_targets.append(
            {
                "id": target["id"],
                "name": target.get("name") or target.get("url"),
                "enabled": bool(target.get("enabled", False)),
                "reachable": beat.get("server_reachable"),
                "series": series["series"],
                "budget_wait_s": series["budget_wait_s"],
                "last_sent_at": series["last_sent_at"],
                "waiting_now": worker.waitingByKind(target["id"]) if worker is not None else {},
                "upload_budget": (
                    {"bytes_per_minute": budget["bytes_per_minute"], "files_per_minute": budget["files_per_minute"]}
                    if budget else None
                ),
            }
        )
    if not hour_starts:
        last = int(now // 3600) * 3600
        hour_starts = [last - 3600 * i for i in range(hours - 1, -1, -1)]
    return {
        "now": now,
        "hour_starts": hour_starts,
        "kinds": [
            {"key": key, "label": label, "stream": stream, "size": sharing.streamNamed(stream).size}
            for key, label, stream in upload_stats.KINDS
        ],
        "targets": out_targets,
        **_localSummary(),
    }
