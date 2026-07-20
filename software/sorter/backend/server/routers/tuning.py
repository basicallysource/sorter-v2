"""Tuning endpoints for runtime-adjustable parameters."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

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
    getClassificationProviders,
    setClassificationProviders,
)
from classification.providers import COLOR_PROVIDER_SPECS, MOLD_PROVIDER_SPECS
from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import FIELD_META
from subsystems.feeder.go_to_angle.config import FIELD_META as GO_TO_ANGLE_FIELD_META
from subsystems.feeder.pulse_perception.config import FIELD_META as PULSE_PERCEPTION_FIELD_META
from subsystems.feeder.constant_movement.config import FIELD_META as CONSTANT_MOVEMENT_FIELD_META
from perception.tracker_config import TRACKER_SPECS

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


@router.get("/api/tuning/classification-providers")
def get_classification_providers() -> dict[str, Any]:
    active = getClassificationProviders()
    return {
        "active": active,
        "color_providers": [
            {"id": s.id, "label": s.label, "description": s.description}
            for s in COLOR_PROVIDER_SPECS.values()
        ],
        "mold_providers": [
            {"id": s.id, "label": s.label, "description": s.description}
            for s in MOLD_PROVIDER_SPECS.values()
        ],
    }


@router.post("/api/tuning/classification-providers")
def set_classification_providers(body: dict[str, Any]) -> dict[str, Any]:
    try:
        if "color_provider" in body and body["color_provider"] not in COLOR_PROVIDER_SPECS:
            raise ValueError(f"unknown color provider: {body['color_provider']}")
        if "mold_provider" in body and body["mold_provider"] not in MOLD_PROVIDER_SPECS:
            raise ValueError(f"unknown mold provider: {body['mold_provider']}")
        setClassificationProviders(body)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return get_classification_providers()


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
