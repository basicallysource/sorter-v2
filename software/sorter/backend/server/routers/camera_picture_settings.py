"""Router for how a camera role's picture is oriented: rotation and flips,
saved per role and applied to its live capture."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter
from pydantic import BaseModel

import machine_toml
from irl.config import cameraPictureSettingsToDict, cameraSettingsForRole, parseCameraPictureSettings
from server import shared_state
from server.routers.cameras import _require_camera_role, _settings_role

router = APIRouter()


def _get_picture_settings_table(config: Dict[str, Any]) -> Dict[str, Any]:
    picture_settings = config.get("camera_picture_settings", {})
    return picture_settings if isinstance(picture_settings, dict) else {}


def _picture_settings_for_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    _require_camera_role(role)
    picture_settings = _get_picture_settings_table(config)
    return cameraPictureSettingsToDict(parseCameraPictureSettings(cameraSettingsForRole(picture_settings, role)))


class CameraPictureSettingsPayload(BaseModel):
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False


@router.get("/api/cameras/picture-settings/{role}")
def get_camera_picture_settings(role: str) -> Dict[str, Any]:
    """Return persisted picture settings for a camera role."""
    config = machine_toml.read()
    return {
        "role": role,
        "settings": _picture_settings_for_role(config, role),
    }


@router.post("/api/cameras/picture-settings/{role}")
def save_camera_picture_settings(
    role: str,
    payload: CameraPictureSettingsPayload,
) -> Dict[str, Any]:
    """Save and live-apply picture settings for a camera role when possible."""
    _require_camera_role(role)

    with machine_toml.edit() as config:
        picture_settings = _get_picture_settings_table(config)
        parsed = parseCameraPictureSettings(payload.model_dump())
        picture_settings[_settings_role(role)] = cameraPictureSettingsToDict(parsed)
        config["camera_picture_settings"] = picture_settings

    applied_live = False
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setPictureSettingsForRole"):
        try:
            applied_live = bool(shared_state.vision_manager.setPictureSettingsForRole(role, parsed))
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "settings": cameraPictureSettingsToDict(parsed),
        "applied_live": applied_live,
        "message": "Feed orientation saved.",
    }
