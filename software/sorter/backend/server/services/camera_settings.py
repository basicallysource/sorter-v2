"""Camera per-role settings and color-profile persistence.

Pure domain logic: reads picture_settings and color_profile entries from
``machine_params``, writes color_profile updates, and normalizes camera
role aliases. No HTTP or transport concerns — callers translate the
domain errors raised here into transport-level responses.
"""

from __future__ import annotations

from typing import Any, Dict

from irl.config import (
    cameraColorProfileToDict,
    cameraPictureSettingsToDict,
    parseCameraColorProfile,
    parseCameraPictureSettings,
)
from role_aliases import lookup_camera_role_keys, stored_camera_role_key
from server.config_helpers import (
    read_machine_params_config,
    write_machine_params_config,
)


CAMERA_SETUP_ROLES = {
    "feeder",
    "c_channel_2",
    "c_channel_3",
    "carousel",
    "classification_channel",
    "classification_top",
    "classification_bottom",
}


class CameraSettingsWriteError(RuntimeError):
    """Raised when persisting a camera color profile fails."""


def get_role_config_value(
    config: Dict[str, Any],
    table_name: str,
    role: str,
) -> Any:
    """Return the config value for ``role`` in ``table_name``, resolving aliases."""
    table = config.get(table_name, {})
    if not isinstance(table, dict):
        return None
    for lookup_role in lookup_camera_role_keys(role, config):
        if lookup_role in table:
            return table.get(lookup_role)
    return None


def _get_camera_color_profile_table(config: Dict[str, Any]) -> Dict[str, Any]:
    profiles = config.get("camera_color_profiles", {})
    return profiles if isinstance(profiles, dict) else {}


def picture_settings_for_role(
    config: Dict[str, Any],
    role: str,
) -> Dict[str, Any]:
    """Picture-settings dict for ``role`` or defaults if unset."""
    return cameraPictureSettingsToDict(
        parseCameraPictureSettings(
            get_role_config_value(config, "camera_picture_settings", role)
        )
    )


def camera_color_profile_for_role(
    config: Dict[str, Any],
    role: str,
) -> Dict[str, Any]:
    """Color-profile dict for ``role`` or defaults if unset."""
    return cameraColorProfileToDict(
        parseCameraColorProfile(
            get_role_config_value(config, "camera_color_profiles", role)
        )
    )


def save_camera_color_profile(
    role: str,
    payload: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Persist ``payload`` as the color profile for ``role``.

    Raises :class:`CameraSettingsWriteError` on persistence failure.
    """
    params_path, config = read_machine_params_config()
    parsed = parseCameraColorProfile(payload)
    profile_dict = cameraColorProfileToDict(parsed)
    profiles = _get_camera_color_profile_table(config)
    config_role = stored_camera_role_key(role, config)
    if parsed.enabled:
        # Carousel and classification_channel are two names for the same
        # physical camera role — keep only one entry when enabling either.
        if config_role == "classification_channel":
            profiles.pop("carousel", None)
        elif config_role == "carousel":
            profiles.pop("classification_channel", None)
        profiles[config_role] = profile_dict
    else:
        profiles.pop(config_role, None)
    config["camera_color_profiles"] = profiles

    try:
        write_machine_params_config(params_path, config)
    except Exception as exc:
        raise CameraSettingsWriteError(f"Failed to write config: {exc}") from exc

    return {
        "ok": True,
        "role": role,
        "profile": profile_dict,
        "applied_live": False,
    }


def restore_camera_color_profile(role: str, profile: Dict[str, Any]) -> None:
    """Best-effort restore; swallows errors since this runs in cleanup paths."""
    try:
        save_camera_color_profile(role, profile)
    except Exception:
        pass


__all__ = [
    "CAMERA_SETUP_ROLES",
    "CameraSettingsWriteError",
    "camera_color_profile_for_role",
    "get_role_config_value",
    "picture_settings_for_role",
    "restore_camera_color_profile",
    "save_camera_color_profile",
]
