"""Feed profiles: named sets of the feeder's and the classification channel's
tuning, one per kind of piece (feed_profiles.py)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import feed_profiles

router = APIRouter()


class SaveBody(BaseModel):
    label: str
    description: str = ""
    # Save over this profile instead of making a new one.
    id: str | None = None


@router.get("/api/feed-profiles")
def list_feed_profiles() -> dict[str, Any]:
    return feed_profiles.listProfiles()


@router.post("/api/feed-profiles")
def save_feed_profile(body: SaveBody) -> dict[str, Any]:
    try:
        return feed_profiles.saveProfile(body.label, body.description, body.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/feed-profiles/{profile_id}/apply")
def apply_feed_profile(profile_id: str) -> dict[str, Any]:
    try:
        return feed_profiles.applyProfile(profile_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such feed profile.")


@router.delete("/api/feed-profiles/{profile_id}")
def delete_feed_profile(profile_id: str) -> dict[str, Any]:
    return feed_profiles.deleteProfile(profile_id)
