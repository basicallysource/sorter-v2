"""Shared rules and mapping helpers for detection-config flows."""

from __future__ import annotations

from typing import Any

from role_aliases import (
    CLASSIFICATION_CHANNEL_ROLE,
    auxiliary_detection_scope,
    internalize_feeder_role,
    public_feeder_detection_roles,
)
from rt.perception.detector_metadata import (
    detection_algorithm_definition,
    normalize_detection_algorithm,
)
from server.config_helpers import read_machine_params_config as _read_machine_params_config


_OPENROUTER_MODEL_LABELS = {
    "google/gemini-3-flash-preview": "Gemini 3 Flash Preview",
    "google/gemini-3.1-flash-lite-preview": "Gemini 3.1 Flash-Lite Preview",
    "google/gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview",
}


def openrouter_model_label(model: str) -> str:
    return _OPENROUTER_MODEL_LABELS.get(model, model)


def openrouter_model_options() -> list[dict[str, str]]:
    from vision.gemini_sam_detector import SUPPORTED_OPENROUTER_MODELS

    return [
        {"id": model, "label": openrouter_model_label(model)}
        for model in SUPPORTED_OPENROUTER_MODELS
    ]


def detection_algorithm_label(scope: str, algorithm: str | None) -> str:
    definition = detection_algorithm_definition(normalize_detection_algorithm(scope, algorithm))
    if definition is None:
        return (algorithm or "detection").replace("_", " ")
    return definition.label


def detection_algorithm_uses_baseline(scope: str, algorithm: str | None) -> bool:
    definition = detection_algorithm_definition(normalize_detection_algorithm(scope, algorithm))
    return bool(definition is not None and definition.needs_baseline)


def _machine_params_config() -> dict[str, Any]:
    _, config = _read_machine_params_config()
    return config if isinstance(config, dict) else {}


def public_feeder_roles() -> tuple[str, ...]:
    return public_feeder_detection_roles(_machine_params_config())


def public_aux_scope() -> str:
    return auxiliary_detection_scope(_machine_params_config())


def internal_feeder_role(value: str | None) -> str | None:
    if value is None:
        return None
    return internalize_feeder_role(value)


def feeder_algorithm_by_role_from_config(
    config: dict[str, Any] | None,
) -> dict[str, str]:
    saved_by_role = (
        config.get("algorithm_by_role")
        if isinstance(config, dict) and isinstance(config.get("algorithm_by_role"), dict)
        else {}
    )
    fallback = config.get("algorithm") if isinstance(config, dict) else None
    return {
        role: normalize_detection_algorithm(
            "feeder",
            saved_by_role.get(role)
            or saved_by_role.get(internal_feeder_role(role) or role)
            or fallback
        )
        for role in public_feeder_roles()
    }


def feeder_role_label(role: str | None) -> str:
    if role == "c_channel_2":
        return "C-channel 2"
    if role == "c_channel_3":
        return "C-channel 3"
    if role == CLASSIFICATION_CHANNEL_ROLE:
        return "Classification C-channel (C4)"
    return "C-channel"


def feeder_sample_collection_supported(
    vision_manager: Any | None,
    role: str | None = None,
) -> bool:
    if vision_manager is not None and hasattr(vision_manager, "supportsFeederSampleCollection"):
        try:
            return bool(
                vision_manager.supportsFeederSampleCollection(
                    internal_feeder_role(role) if role else None
                )
            )
        except Exception:
            return False
    return True


def auxiliary_sample_collection_supported(vision_manager: Any | None) -> bool:
    if vision_manager is not None and hasattr(vision_manager, "supportsCarouselSampleCollection"):
        try:
            return bool(vision_manager.supportsCarouselSampleCollection())
        except Exception:
            return False
    return True


__all__ = [
    "auxiliary_sample_collection_supported",
    "detection_algorithm_label",
    "detection_algorithm_uses_baseline",
    "feeder_algorithm_by_role_from_config",
    "feeder_role_label",
    "feeder_sample_collection_supported",
    "internal_feeder_role",
    "openrouter_model_label",
    "openrouter_model_options",
    "public_aux_scope",
    "public_feeder_roles",
]
