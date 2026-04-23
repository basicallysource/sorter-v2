"""Application service for detection-config read/save use cases.

Detection decisions flow through the rt graph. When a change requires a
live detector swap, the service asks
``rt_handle.rebuild_runner_for_role(...)`` to rebuild the affected runner.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from role_aliases import CLASSIFICATION_CHANNEL_ROLE
from rt.perception.detector_metadata import (
    detection_algorithm_options,
    normalize_detection_algorithm,
    scope_supports_detection_algorithm,
)
from server.detection_config.common import (
    detection_algorithm_label as _detection_algorithm_label,
    detection_algorithm_uses_baseline as _detection_algorithm_uses_baseline,
    feeder_algorithm_by_role_from_config as _feeder_algorithm_by_role_from_config,
    feeder_role_label as _feeder_role_label,
    get_carousel_detection_config,
    get_classification_channel_detection_config,
    get_classification_detection_config,
    get_feeder_detection_config,
    openrouter_model_options as _openrouter_model_options,
    public_aux_scope as _public_aux_scope,
    public_feeder_roles as _public_feeder_roles,
    set_carousel_detection_config,
    set_classification_channel_detection_config,
    set_classification_detection_config,
    set_feeder_detection_config,
)
from server.services.llm_client import normalize_openrouter_model as _normalize_openrouter_model


class DetectionConfigValidationError(ValueError):
    """Raised when a config payload is invalid for the requested scope."""


class DetectionConfigApplyError(RuntimeError):
    """Raised when a validated config could not be applied live."""


@dataclass(slots=True, frozen=True, kw_only=True)
class ClassificationDetectionSaveRequest:
    algorithm: str
    openrouter_model: str | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class FeederDetectionSaveRequest:
    role: str | None
    algorithm: str
    openrouter_model: str | None = None
    sample_collection_enabled: bool | None = None


@dataclass(slots=True, frozen=True, kw_only=True)
class AuxiliaryDetectionSaveRequest:
    algorithm: str
    openrouter_model: str | None = None
    sample_collection_enabled: bool | None = None


_FEEDER_ROLE_KEY_TO_RT_ROLE: dict[str, str] = {
    "c_channel_2": "c2",
    "c_channel_3": "c3",
    CLASSIFICATION_CHANNEL_ROLE: "c4",
}


def _saved_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _feeder_sample_collection_by_role(saved: dict[str, Any]) -> dict[str, bool]:
    saved_by_role = saved.get("sample_collection_enabled_by_role")
    saved_by_role = saved_by_role if isinstance(saved_by_role, dict) else {}
    fallback = saved.get("sample_collection_enabled")
    return {
        channel_role: bool(saved_by_role.get(channel_role, fallback))
        for channel_role in _public_feeder_roles()
    }


@dataclass(slots=True, kw_only=True)
class DetectionConfigService:
    rt_handle: Any | None

    # ------------------------------------------------------------------
    # Read flows
    # ------------------------------------------------------------------

    def get_classification_detection_config(self) -> dict[str, Any]:
        saved = _saved_dict(get_classification_detection_config())
        return {
            "ok": True,
            "algorithm": normalize_detection_algorithm("classification", saved.get("algorithm")),
            "openrouter_model": _normalize_openrouter_model(saved.get("openrouter_model")),
            "available_algorithms": detection_algorithm_options("classification"),
            "available_openrouter_models": _openrouter_model_options(),
        }

    def get_feeder_detection_config(self, role: str | None) -> dict[str, Any]:
        saved = _saved_dict(get_feeder_detection_config())
        algorithm_by_role = _feeder_algorithm_by_role_from_config(saved)
        algorithm = (
            algorithm_by_role.get(role)
            if role is not None
            else normalize_detection_algorithm("feeder", saved.get("algorithm"))
        )
        enabled_by_role = _feeder_sample_collection_by_role(saved)
        sample_collection_enabled = (
            bool(enabled_by_role.get(role))
            if role is not None
            else any(enabled_by_role.values())
        )
        return {
            "ok": True,
            "role": role,
            "algorithm": algorithm,
            "algorithm_by_role": algorithm_by_role,
            "openrouter_model": _normalize_openrouter_model(saved.get("openrouter_model")),
            "sample_collection_enabled": sample_collection_enabled,
            "sample_collection_enabled_by_role": enabled_by_role,
            "sample_collection_supported": True,
            "available_algorithms": detection_algorithm_options("feeder"),
            "available_openrouter_models": _openrouter_model_options(),
        }

    def get_auxiliary_detection_config(self) -> dict[str, Any]:
        aux_scope = _public_aux_scope()
        algorithm_scope = (
            "classification_channel"
            if aux_scope == CLASSIFICATION_CHANNEL_ROLE
            else "carousel"
        )
        saved = _saved_dict(
            get_classification_channel_detection_config()
            if aux_scope == CLASSIFICATION_CHANNEL_ROLE
            else get_carousel_detection_config()
        )
        return {
            "ok": True,
            "algorithm": normalize_detection_algorithm(algorithm_scope, saved.get("algorithm")),
            "openrouter_model": _normalize_openrouter_model(saved.get("openrouter_model")),
            "sample_collection_enabled": bool(saved.get("sample_collection_enabled")),
            "sample_collection_supported": True,
            "available_algorithms": detection_algorithm_options(algorithm_scope),
            "available_openrouter_models": _openrouter_model_options(),
            "scope": aux_scope,
        }

    # ------------------------------------------------------------------
    # Save flows
    # ------------------------------------------------------------------

    def save_classification_detection_config(
        self,
        request: ClassificationDetectionSaveRequest,
    ) -> dict[str, Any]:
        if not scope_supports_detection_algorithm("classification", request.algorithm):
            raise DetectionConfigValidationError(
                "Unsupported classification detection algorithm."
            )
        algorithm = normalize_detection_algorithm("classification", request.algorithm)
        openrouter_model = _normalize_openrouter_model(request.openrouter_model)
        set_classification_detection_config(
            {"algorithm": algorithm, "openrouter_model": openrouter_model}
        )

        algorithm_label = _detection_algorithm_label("classification", algorithm)
        uses_baseline = _detection_algorithm_uses_baseline("classification", algorithm)
        message = f"Classification chamber detection switched to {algorithm_label}."
        if uses_baseline:
            message += " Capture an empty baseline if detection stays unavailable."
        return {
            "ok": True,
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
            "baseline_loaded": False,
            "uses_baseline": uses_baseline,
            "message": message,
        }

    def save_feeder_detection_config(
        self,
        request: FeederDetectionSaveRequest,
    ) -> dict[str, Any]:
        if not scope_supports_detection_algorithm("feeder", request.algorithm):
            raise DetectionConfigValidationError(
                "Unsupported feeder detection algorithm."
            )
        role = request.role
        algorithm = normalize_detection_algorithm("feeder", request.algorithm)
        openrouter_model = _normalize_openrouter_model(request.openrouter_model)
        saved = _saved_dict(get_feeder_detection_config())
        algorithm_by_role = _feeder_algorithm_by_role_from_config(saved)
        enabled_by_role = _feeder_sample_collection_by_role(saved)
        if role is not None:
            algorithm_by_role[role] = algorithm
        else:
            for channel_role in _public_feeder_roles():
                algorithm_by_role[channel_role] = algorithm
        if isinstance(request.sample_collection_enabled, bool):
            flag = bool(request.sample_collection_enabled)
            if role is not None:
                enabled_by_role[role] = flag
            else:
                for channel_role in _public_feeder_roles():
                    enabled_by_role[channel_role] = flag

        sample_collection_enabled = (
            bool(enabled_by_role.get(role))
            if role is not None
            else any(enabled_by_role.values())
        )
        set_feeder_detection_config(
            {
                "algorithm": (
                    algorithm
                    if role is None
                    else normalize_detection_algorithm("feeder", saved.get("algorithm"))
                ),
                "algorithm_by_role": dict(algorithm_by_role),
                "openrouter_model": openrouter_model,
                "sample_collection_enabled": sample_collection_enabled,
                "sample_collection_enabled_by_role": dict(enabled_by_role),
            }
        )
        self._rebuild_rt_runner_for_feeder_role(role)

        role_label = _feeder_role_label(role)
        algorithm_label = _detection_algorithm_label("feeder", algorithm)
        message = f"{role_label} detection uses {algorithm_label}."
        if sample_collection_enabled:
            message += (
                f" Event-driven Gemini teacher sample collection is enabled "
                f"for {role_label.lower()} moves."
            )
        elif role is not None:
            message += (
                f" Event-driven Gemini teacher sample collection is disabled "
                f"for {role_label.lower()} moves."
            )
        return {
            "ok": True,
            "role": role,
            "algorithm": algorithm,
            "algorithm_by_role": algorithm_by_role,
            "openrouter_model": openrouter_model,
            "sample_collection_enabled": sample_collection_enabled,
            "sample_collection_enabled_by_role": enabled_by_role,
            "sample_collection_supported": True,
            "message": message,
        }

    def save_auxiliary_detection_config(
        self,
        request: AuxiliaryDetectionSaveRequest,
        *,
        aux_scope: str,
    ) -> dict[str, Any]:
        algorithm_scope = (
            "classification_channel"
            if aux_scope == CLASSIFICATION_CHANNEL_ROLE
            else "carousel"
        )
        if not scope_supports_detection_algorithm(algorithm_scope, request.algorithm):
            raise DetectionConfigValidationError(
                "Unsupported carousel detection algorithm."
            )
        algorithm = normalize_detection_algorithm(algorithm_scope, request.algorithm)
        openrouter_model = _normalize_openrouter_model(request.openrouter_model)
        saved = _saved_dict(
            get_classification_channel_detection_config()
            if aux_scope == CLASSIFICATION_CHANNEL_ROLE
            else get_carousel_detection_config()
        )
        sample_collection_enabled = (
            bool(request.sample_collection_enabled)
            if isinstance(request.sample_collection_enabled, bool)
            else bool(saved.get("sample_collection_enabled"))
        )

        target_config = {
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
            "sample_collection_enabled": sample_collection_enabled,
        }
        if aux_scope == CLASSIFICATION_CHANNEL_ROLE:
            set_classification_channel_detection_config(target_config)
            self._rebuild_rt_runner_for_feeder_role(CLASSIFICATION_CHANNEL_ROLE)
        else:
            set_carousel_detection_config(target_config)

        algorithm_label = _detection_algorithm_label(algorithm_scope, algorithm)
        uses_baseline = _detection_algorithm_uses_baseline(algorithm_scope, algorithm)
        scope_label = (
            "Classification C-channel (C4)"
            if aux_scope == CLASSIFICATION_CHANNEL_ROLE
            else "Carousel"
        )
        message = f"{scope_label} detection switched to {algorithm_label}."
        if uses_baseline:
            message += " Capture a fresh baseline if detection stays unavailable."
        if sample_collection_enabled:
            message += (
                " Event-driven Gemini teacher sample collection is enabled "
                "and will take effect when Heatmap Diff is active."
            )
        return {
            "ok": True,
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
            "sample_collection_enabled": sample_collection_enabled,
            "sample_collection_supported": True,
            "uses_baseline": uses_baseline,
            "scope": aux_scope,
            "message": message,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_rt_runner_for_feeder_role(self, feeder_role: str | None) -> None:
        handle = self.rt_handle
        if handle is None or not hasattr(handle, "rebuild_runner_for_role"):
            return
        if feeder_role is None:
            targets = [_FEEDER_ROLE_KEY_TO_RT_ROLE[key] for key in ("c_channel_2", "c_channel_3")]
        else:
            rt_role = _FEEDER_ROLE_KEY_TO_RT_ROLE.get(feeder_role)
            targets = [rt_role] if rt_role else []
        for rt_role in targets:
            try:
                handle.rebuild_runner_for_role(rt_role)
            except Exception:
                # Config persistence must succeed even if the live runner
                # rebuild fails; /api/rt/status will expose the fallout.
                pass


__all__ = [
    "AuxiliaryDetectionSaveRequest",
    "ClassificationDetectionSaveRequest",
    "DetectionConfigApplyError",
    "DetectionConfigService",
    "DetectionConfigValidationError",
    "FeederDetectionSaveRequest",
]
