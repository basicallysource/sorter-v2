"""Settings > Sorting: the feed profile the machine runs (feed_profiles.py)
and how pieces are identified (sorting_mode.py)."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import feed_profiles
import machine_toml
import sorting_mode

router = APIRouter()


class ActiveBody(BaseModel):
    id: str


class ProfileBody(BaseModel):
    label: str
    description: str = ""
    # {"feeder": {...}, "classification_channel": {...}}: only what it changes.
    values: dict[str, dict[str, Any]] = {}
    # Save over this profile of one's own.
    id: Optional[str] = None


class ModeBody(BaseModel):
    mode: Optional[str] = None
    assumed_part_id: Optional[str] = None
    assumed_part_name: Optional[str] = None


def _base() -> dict[str, dict[str, Any]]:
    """Each section's values without any profile: what "Default" runs."""
    from hardware_settings.feeder import feederDrive
    from subsystems.classification_channel.two_piece.rev01_config import (
        configToDict as rev01ToDict,
        defaultConfig as rev01Default,
    )
    from subsystems.feeder.pulse_perception.config import (
        configToDict as feederToDict,
        defaultConfig as feederDefault,
        migrateLegacyKeys,
    )

    config = machine_toml.read()
    drive = feederDrive(config)
    feeder = feederToDict(feederDefault(drive))
    stored = config.get("feeder_pulse_perception")
    if isinstance(stored, dict):
        feeder.update({k: v for k, v in migrateLegacyKeys(stored).items() if k in feeder})
    c4 = rev01ToDict(rev01Default(drive))
    stored = config.get("classification_channel_rev01")
    if isinstance(stored, dict):
        c4.update({k: v for k, v in stored.items() if k in c4})
    return {"feeder": feeder, "classification_channel": c4}


def _fields() -> dict[str, list[dict]]:
    from subsystems.classification_channel.two_piece.rev01_config import fieldMeta as rev01Fields
    from subsystems.feeder.pulse_perception.config import fieldMeta as feederFields

    return {"feeder": feederFields(), "classification_channel": rev01Fields()}


def _listing() -> dict[str, Any]:
    return {**feed_profiles.listProfiles(), "base": _base(), "fields": _fields()}


@router.get("/api/sorting/feed-profiles")
def list_feed_profiles() -> dict[str, Any]:
    return _listing()


@router.post("/api/sorting/feed-profiles/active")
def set_active_feed_profile(body: ActiveBody) -> dict[str, Any]:
    try:
        feed_profiles.setActive(body.id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such feed profile.")
    return _listing()


@router.post("/api/sorting/feed-profiles")
def save_feed_profile(body: ProfileBody) -> dict[str, Any]:
    try:
        feed_profiles.saveProfile(body.label, body.description, body.values, body.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _listing()


@router.delete("/api/sorting/feed-profiles/{profile_id}")
def delete_feed_profile(profile_id: str) -> dict[str, Any]:
    try:
        feed_profiles.deleteProfile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _listing()


@router.get("/api/sorting/mode")
def get_sorting_mode() -> dict[str, Any]:
    return sorting_mode.get()


@router.post("/api/sorting/mode")
def set_sorting_mode(body: ModeBody) -> dict[str, Any]:
    try:
        return sorting_mode.update(body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
