"""Tuning endpoints for runtime-adjustable parameters."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from toml_config import (
    getClassificationChannelRev01Config,
    setClassificationChannelRev01Config,
    getGoToAngleConfig,
    setGoToAngleConfig,
    getPulsePerceptionConfig,
    setPulsePerceptionConfig,
)
from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import FIELD_META
from subsystems.feeder.go_to_angle.config import FIELD_META as GO_TO_ANGLE_FIELD_META
from subsystems.feeder.pulse_perception.config import FIELD_META as PULSE_PERCEPTION_FIELD_META

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
