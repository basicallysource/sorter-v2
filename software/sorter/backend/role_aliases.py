from __future__ import annotations

from typing import Any, Mapping

from machine_setup import machine_setup_key_from_feeding_mode, normalize_machine_setup_key

LEGACY_CAROUSEL_ROLE = "carousel"
CLASSIFICATION_CHANNEL_ROLE = "classification_channel"
AUXILIARY_CLASSIFICATION_ROLES = frozenset(
    {LEGACY_CAROUSEL_ROLE, CLASSIFICATION_CHANNEL_ROLE}
)


def machine_setup_key_from_config(config: Mapping[str, Any] | None) -> str:
    if isinstance(config, Mapping):
        machine_setup = config.get("machine_setup")
        if isinstance(machine_setup, Mapping):
            setup_key = normalize_machine_setup_key(machine_setup.get("type"))
            if setup_key is not None:
                return setup_key

        feeding = config.get("feeding")
        if isinstance(feeding, Mapping):
            return machine_setup_key_from_feeding_mode(feeding.get("mode"))

    return machine_setup_key_from_feeding_mode(None)


def uses_classification_channel_setup(config: Mapping[str, Any] | None) -> bool:
    return machine_setup_key_from_config(config) == CLASSIFICATION_CHANNEL_ROLE


def public_aux_camera_role(config: Mapping[str, Any] | None) -> str:
    return (
        CLASSIFICATION_CHANNEL_ROLE
        if uses_classification_channel_setup(config)
        else LEGACY_CAROUSEL_ROLE
    )


def is_auxiliary_classification_role(role: str | None) -> bool:
    return isinstance(role, str) and role in AUXILIARY_CLASSIFICATION_ROLES


def publicize_camera_role(role: str, config: Mapping[str, Any] | None) -> str:
    if role == LEGACY_CAROUSEL_ROLE:
        return public_aux_camera_role(config)
    return role


def internalize_camera_role(role: str) -> str:
    if role == CLASSIFICATION_CHANNEL_ROLE:
        return LEGACY_CAROUSEL_ROLE
    return role


def lookup_camera_role_keys(
    role: str,
    config: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    internal_role = internalize_camera_role(role)
    if internal_role != LEGACY_CAROUSEL_ROLE:
        return (internal_role,)
    if uses_classification_channel_setup(config):
        return (CLASSIFICATION_CHANNEL_ROLE, LEGACY_CAROUSEL_ROLE)
    return (LEGACY_CAROUSEL_ROLE,)


def stored_camera_role_key(
    role: str,
    config: Mapping[str, Any] | None,
) -> str:
    internal_role = internalize_camera_role(role)
    if internal_role == LEGACY_CAROUSEL_ROLE and uses_classification_channel_setup(config):
        return CLASSIFICATION_CHANNEL_ROLE
    return internal_role


def public_feeder_detection_roles(
    config: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if uses_classification_channel_setup(config):
        return ("c_channel_2", "c_channel_3", CLASSIFICATION_CHANNEL_ROLE)
    return ("c_channel_2", "c_channel_3")


def publicize_feeder_role(
    role: str,
    config: Mapping[str, Any] | None,
) -> str:
    if role == LEGACY_CAROUSEL_ROLE and uses_classification_channel_setup(config):
        return CLASSIFICATION_CHANNEL_ROLE
    return role


def internalize_feeder_role(role: str) -> str:
    return internalize_camera_role(role)


def auxiliary_detection_scope(config: Mapping[str, Any] | None) -> str:
    return public_aux_camera_role(config)


def lookup_auxiliary_detection_scopes(
    config: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if uses_classification_channel_setup(config):
        return (CLASSIFICATION_CHANNEL_ROLE, LEGACY_CAROUSEL_ROLE)
    return (LEGACY_CAROUSEL_ROLE,)
