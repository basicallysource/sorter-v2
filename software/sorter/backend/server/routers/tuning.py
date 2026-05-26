"""Tuning endpoints for runtime-adjustable parameters."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from toml_config import getClassificationChannelRev01Config, setClassificationChannelRev01Config
from subsystems.classification_channel.simple_state_machine_rev01.rev01_config import FIELD_META

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
