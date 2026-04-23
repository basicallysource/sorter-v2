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


# ---------------------------------------------------------------------------
# Detection-config blob readers/writers — adapters over ``toml_config`` that
# map each UI scope onto the ``[detection.<scope>]`` table.
# ---------------------------------------------------------------------------


def get_classification_detection_config() -> dict | None:
    from toml_config import getDetectionConfig
    return getDetectionConfig("classification")


def set_classification_detection_config(config: dict) -> None:
    from toml_config import setDetectionConfig
    setDetectionConfig("classification", config)


def get_feeder_detection_config() -> dict | None:
    from toml_config import getDetectionConfig
    return getDetectionConfig("feeder")


def set_feeder_detection_config(config: dict) -> None:
    from toml_config import setDetectionConfig
    setDetectionConfig("feeder", config)


def get_carousel_detection_config() -> dict | None:
    from toml_config import getDetectionConfig, _read_toml
    return getDetectionConfig(auxiliary_detection_scope(_read_toml()))


def set_carousel_detection_config(config: dict) -> None:
    from toml_config import setDetectionConfig, _read_toml
    setDetectionConfig(auxiliary_detection_scope(_read_toml()), config)


def get_classification_channel_detection_config() -> dict | None:
    from toml_config import getDetectionConfig
    return getDetectionConfig("classification_channel")


def set_classification_channel_detection_config(config: dict) -> None:
    from toml_config import setDetectionConfig
    setDetectionConfig("classification_channel", config)


__all__ = [
    "detection_algorithm_label",
    "detection_algorithm_uses_baseline",
    "feeder_algorithm_by_role_from_config",
    "feeder_role_label",
    "get_carousel_detection_config",
    "get_classification_channel_detection_config",
    "get_classification_detection_config",
    "get_feeder_detection_config",
    "internal_feeder_role",
    "openrouter_model_label",
    "openrouter_model_options",
    "public_aux_scope",
    "public_feeder_roles",
    "set_carousel_detection_config",
    "set_classification_channel_detection_config",
    "set_classification_detection_config",
    "set_feeder_detection_config",
]
