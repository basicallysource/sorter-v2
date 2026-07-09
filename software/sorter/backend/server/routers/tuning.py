"""Tuning endpoints for runtime-adjustable parameters."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException

from server import shared_state
from toml_config import (
    getClassificationChannelRev01Config,
    setClassificationChannelRev01Config,
    getGoToAngleConfig,
    setGoToAngleConfig,
    getActiveTrackerType,
    setActiveTrackerType,
    getTrackerConfig,
    setTrackerConfig,
    getPulsePerceptionConfig,
    setPulsePerceptionConfig,
    getConstantMovementConfig,
    setConstantMovementConfig,
    getUpstreamMatchConfig,
    setUpstreamMatchConfig,
)
from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import FIELD_META
from subsystems.feeder.go_to_angle.config import FIELD_META as GO_TO_ANGLE_FIELD_META
from subsystems.feeder.pulse_perception.config import FIELD_META as PULSE_PERCEPTION_FIELD_META
from subsystems.feeder.constant_movement.config import FIELD_META as CONSTANT_MOVEMENT_FIELD_META
from perception.tracker_config import TRACKER_SPECS
from perception.upstream_capture import (
    EMBED_MODEL,
    FIELD_META as UPSTREAM_MATCH_FIELD_META,
    anchorImageB64s,
    configFromDict as upstreamConfigFromDict,
)

router = APIRouter()


@router.get("/api/tuning/classification-channel-rev01")
def get_cc_rev01_config() -> dict[str, Any]:
    return {
        "config": getClassificationChannelRev01Config(),
        "fields": FIELD_META,
    }


@router.post("/api/tuning/classification-channel-rev01")
def set_cc_rev01_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setClassificationChannelRev01Config(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"config": updated}


@router.get("/api/tuning/feeder-go-to-angle")
def get_go_to_angle_config() -> dict[str, Any]:
    return {
        "config": getGoToAngleConfig(),
        "fields": GO_TO_ANGLE_FIELD_META,
    }


@router.post("/api/tuning/feeder-go-to-angle")
def set_go_to_angle_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setGoToAngleConfig(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"config": updated}


@router.get("/api/tuning/feeder-pulse-perception")
def get_pulse_perception_config() -> dict[str, Any]:
    return {
        "config": getPulsePerceptionConfig(),
        "fields": PULSE_PERCEPTION_FIELD_META,
    }


@router.post("/api/tuning/feeder-pulse-perception")
def set_pulse_perception_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setPulsePerceptionConfig(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"config": updated}


@router.get("/api/tuning/feeder-constant-movement")
def get_constant_movement_config() -> dict[str, Any]:
    return {
        "config": getConstantMovementConfig(),
        "fields": CONSTANT_MOVEMENT_FIELD_META,
    }


@router.post("/api/tuning/feeder-constant-movement")
def set_constant_movement_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setConstantMovementConfig(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"config": updated}


@router.get("/api/tuning/object-tracker")
def get_object_tracker_config() -> dict[str, Any]:
    # All trackers up front so the UI can switch between them client-side; the
    # active one is flagged separately.
    return {
        "active_type": getActiveTrackerType(),
        "trackers": [
            {
                "type": t,
                "label": spec.label,
                "description": spec.description,
                "fields": spec.field_meta,
                "config": getTrackerConfig(t),
            }
            for t, spec in TRACKER_SPECS.items()
        ],
    }


@router.post("/api/tuning/object-tracker")
def set_object_tracker_config(body: dict[str, Any]) -> dict[str, Any]:
    # Body may carry {type, config} to save one tracker's params and/or
    # {active_type} to switch the active tracker. The page sends both on Save.
    cfg_type = body.get("type")
    config = body.get("config")
    active_type = body.get("active_type")
    try:
        if cfg_type is not None and isinstance(config, dict):
            if cfg_type not in TRACKER_SPECS:
                raise ValueError(f"unknown tracker type: {cfg_type}")
            setTrackerConfig(cfg_type, config)
        if active_type is not None:
            if active_type not in TRACKER_SPECS:
                raise ValueError(f"unknown tracker type: {active_type}")
            setActiveTrackerType(active_type)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return get_object_tracker_config()


def _upstreamStore():
    gc = shared_state.gc_ref
    service = getattr(gc, "perception_service", None) if gc is not None else None
    return getattr(service, "upstream_store", None) if service is not None else None


@router.get("/api/tuning/upstream-match")
def get_upstream_match_config() -> dict[str, Any]:
    store = _upstreamStore()
    return {
        "config": getUpstreamMatchConfig(),
        "fields": UPSTREAM_MATCH_FIELD_META,
        "stats": store.stats() if store is not None else None,
    }


@router.post("/api/tuning/upstream-match")
def set_upstream_match_config(body: dict[str, Any]) -> dict[str, Any]:
    try:
        updated = setUpstreamMatchConfig(body)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    store = _upstreamStore()
    if store is not None:
        store.configure(upstreamConfigFromDict(updated))
    return {"config": updated}


@router.get("/api/tuning/upstream-match/crops")
def list_upstream_crops(offset: int = 0, limit: int = 60, channel: int | None = None) -> dict[str, Any]:
    store = _upstreamStore()
    if store is None:
        raise HTTPException(status_code=503, detail="upstream store not running (perception inactive?)")
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    ch = channel if channel in (2, 3) else None
    return store.listCrops(offset=offset, limit=limit, channel=ch)


@router.post("/api/tuning/upstream-match/search")
def search_upstream_match(body: dict[str, Any]) -> dict[str, Any]:
    uuid = body.get("uuid")
    if not isinstance(uuid, str) or not uuid.strip():
        raise HTTPException(status_code=400, detail="uuid is required")
    uuid = uuid.strip()
    store = _upstreamStore()
    if store is None:
        raise HTTPException(status_code=503, detail="upstream store not running (perception inactive?)")
    gc = shared_state.gc_ref
    runtime_stats = getattr(gc, "runtime_stats", None) if gc is not None else None
    payload = runtime_stats.lookupKnownObject(uuid) if runtime_stats is not None else None
    if payload is None:
        raise HTTPException(status_code=404, detail="piece not found (aged out of lookup?)")

    # Persisted defaults overlaid with any live overrides from the tuning form,
    # so the operator can sweep params without saving.
    cfg_dict = {**getUpstreamMatchConfig()}
    for k, v in body.items():
        if k != "uuid":
            cfg_dict[k] = v
    cfg = upstreamConfigFromDict(cfg_dict)

    b64s = anchorImageB64s(payload)
    ref_ts = (
        payload.get("first_carousel_seen_ts")
        or payload.get("created_at")
        or time.time()
    )
    result = store.search(b64s, float(ref_ts), cfg)
    return {
        "anchor": {
            "uuid": uuid,
            "ref_ts": float(ref_ts),
            "part_id": payload.get("part_id"),
            "part_name": payload.get("part_name"),
            "color_name": payload.get("color_name"),
            "confidence": payload.get("confidence"),
            "n_embeddings": result.get("n_anchor_embedded", 0),
            "embedding_method": EMBED_MODEL,
            "images": b64s[:8],
        },
        "candidates": result.get("candidates", []),
        "error": result.get("error"),
        "stats": store.stats(),
        "config": cfg_dict,
    }
