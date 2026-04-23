"""Application service for detection-config save use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from blob_manager import (
    getCarouselDetectionConfig,
    getClassificationChannelDetectionConfig,
    getFeederDetectionConfig,
    setCarouselDetectionConfig,
    setClassificationChannelDetectionConfig,
    setClassificationDetectionConfig,
    setFeederDetectionConfig,
)
from role_aliases import CLASSIFICATION_CHANNEL_ROLE
from rt.perception.detector_metadata import (
    normalize_detection_algorithm,
    scope_supports_detection_algorithm,
)
from server.detection_config.common import (
    auxiliary_sample_collection_supported as _auxiliary_sample_collection_supported,
    detection_algorithm_label as _detection_algorithm_label,
    detection_algorithm_uses_baseline as _detection_algorithm_uses_baseline,
    feeder_algorithm_by_role_from_config as _feeder_algorithm_by_role_from_config,
    feeder_role_label as _feeder_role_label,
    feeder_sample_collection_supported as _feeder_sample_collection_supported,
    internal_feeder_role as _internal_feeder_role,
    public_feeder_roles as _public_feeder_roles,
)
from vision.gemini_sam_detector import normalize_openrouter_model as _normalize_openrouter_model


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


@dataclass(slots=True, kw_only=True)
class DetectionConfigService:
    vision_manager: Any | None
    rt_handle: Any | None

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
        setClassificationDetectionConfig(
            {
                "algorithm": algorithm,
                "openrouter_model": openrouter_model,
            }
        )

        baseline_loaded = False
        vision_manager = self.vision_manager
        if vision_manager is not None and hasattr(
            vision_manager, "setClassificationDetectionAlgorithm"
        ):
            try:
                baseline_loaded = bool(
                    vision_manager.setClassificationDetectionAlgorithm(algorithm)
                )
                if hasattr(vision_manager, "setClassificationOpenRouterModel"):
                    vision_manager.setClassificationOpenRouterModel(openrouter_model)
            except ValueError as exc:
                raise DetectionConfigValidationError(str(exc)) from exc
            except Exception as exc:
                raise DetectionConfigApplyError(
                    f"Failed to apply classification detection config: {exc}"
                ) from exc

        algorithm_label = _detection_algorithm_label("classification", algorithm)
        uses_baseline = _detection_algorithm_uses_baseline("classification", algorithm)
        message = (
            f"Classification chamber detection switched to {algorithm_label}."
            if uses_baseline and baseline_loaded
            else (
                f"Classification chamber detection switched to {algorithm_label}. "
                "Capture an empty baseline if detection stays unavailable."
                if uses_baseline
                else f"Classification chamber detection switched to {algorithm_label}."
            )
        )
        return {
            "ok": True,
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
            "baseline_loaded": baseline_loaded,
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
        internal_role = _internal_feeder_role(role)
        algorithm = normalize_detection_algorithm("feeder", request.algorithm)
        openrouter_model = _normalize_openrouter_model(request.openrouter_model)
        saved = getFeederDetectionConfig()
        algorithm_by_role = _feeder_algorithm_by_role_from_config(
            saved if isinstance(saved, dict) else None
        )
        saved_by_role = (
            saved.get("sample_collection_enabled_by_role")
            if isinstance(saved, dict)
            and isinstance(saved.get("sample_collection_enabled_by_role"), dict)
            else {}
        )
        sample_collection_enabled_by_role = {
            channel_role: bool(saved_by_role.get(channel_role, saved.get("sample_collection_enabled")))
            if isinstance(saved, dict)
            else False
            for channel_role in _public_feeder_roles()
        }
        if role is not None:
            algorithm_by_role[role] = algorithm
        else:
            for channel_role in _public_feeder_roles():
                algorithm_by_role[channel_role] = algorithm
        if isinstance(request.sample_collection_enabled, bool):
            if role is not None:
                sample_collection_enabled_by_role[role] = bool(
                    request.sample_collection_enabled
                )
            else:
                for channel_role in _public_feeder_roles():
                    sample_collection_enabled_by_role[channel_role] = bool(
                        request.sample_collection_enabled
                    )

        vision_manager = self.vision_manager
        if vision_manager is not None and hasattr(
            vision_manager, "setFeederDetectionAlgorithm"
        ):
            try:
                if role is not None:
                    vision_manager.setFeederDetectionAlgorithm(algorithm, internal_role)
                else:
                    vision_manager.setFeederDetectionAlgorithm(algorithm)
                if hasattr(vision_manager, "setFeederOpenRouterModel"):
                    vision_manager.setFeederOpenRouterModel(openrouter_model)
                if hasattr(vision_manager, "setFeederSampleCollectionEnabled"):
                    if role is not None:
                        sample_collection_enabled_by_role[role] = bool(
                            vision_manager.setFeederSampleCollectionEnabled(
                                sample_collection_enabled_by_role[role], internal_role
                            )
                        )
                    else:
                        for channel_role in _public_feeder_roles():
                            sample_collection_enabled_by_role[channel_role] = bool(
                                vision_manager.setFeederSampleCollectionEnabled(
                                    sample_collection_enabled_by_role[channel_role],
                                    _internal_feeder_role(channel_role),
                                )
                            )
            except ValueError as exc:
                raise DetectionConfigValidationError(str(exc)) from exc
            except Exception as exc:
                raise DetectionConfigApplyError(
                    f"Failed to apply feeder detection config: {exc}"
                ) from exc

        sample_collection_enabled = (
            bool(sample_collection_enabled_by_role.get(role))
            if role is not None
            else any(sample_collection_enabled_by_role.values())
        )
        setFeederDetectionConfig(
            {
                "algorithm": (
                    algorithm
                    if role is None
                    else normalize_detection_algorithm(
                        "feeder",
                        saved.get("algorithm") if isinstance(saved, dict) else None
                    )
                ),
                "algorithm_by_role": dict(algorithm_by_role),
                "openrouter_model": openrouter_model,
                "sample_collection_enabled": sample_collection_enabled,
                "sample_collection_enabled_by_role": dict(
                    sample_collection_enabled_by_role
                ),
            }
        )
        self._rebuild_rt_runner_for_feeder_role(role)

        role_label = _feeder_role_label(role)
        algorithm_label = _detection_algorithm_label("feeder", algorithm)
        sample_collection_supported = _feeder_sample_collection_supported(
            vision_manager, role
        )
        message = f"{role_label} detection uses {algorithm_label}."
        if sample_collection_supported:
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
        else:
            message += (
                " Event-driven Gemini teacher sample collection is unavailable "
                f"for {role_label.lower()} in the current camera setup."
            )
        return {
            "ok": True,
            "role": role,
            "algorithm": algorithm,
            "algorithm_by_role": algorithm_by_role,
            "openrouter_model": openrouter_model,
            "sample_collection_enabled": sample_collection_enabled,
            "sample_collection_enabled_by_role": sample_collection_enabled_by_role,
            "sample_collection_supported": sample_collection_supported,
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
        saved = (
            getClassificationChannelDetectionConfig()
            if aux_scope == CLASSIFICATION_CHANNEL_ROLE
            else getCarouselDetectionConfig()
        )
        sample_collection_enabled = (
            bool(request.sample_collection_enabled)
            if isinstance(request.sample_collection_enabled, bool)
            else bool(saved.get("sample_collection_enabled"))
            if isinstance(saved, dict)
            else False
        )

        vision_manager = self.vision_manager
        if vision_manager is not None and hasattr(
            vision_manager, "setCarouselDetectionAlgorithm"
        ):
            try:
                vision_manager.setCarouselDetectionAlgorithm(algorithm)
                if hasattr(vision_manager, "setCarouselOpenRouterModel"):
                    vision_manager.setCarouselOpenRouterModel(openrouter_model)
                if hasattr(vision_manager, "setCarouselSampleCollectionEnabled"):
                    sample_collection_enabled = bool(
                        vision_manager.setCarouselSampleCollectionEnabled(
                            sample_collection_enabled
                        )
                    )
            except ValueError as exc:
                raise DetectionConfigValidationError(str(exc)) from exc
            except Exception as exc:
                raise DetectionConfigApplyError(
                    f"Failed to apply carousel detection config: {exc}"
                ) from exc

        target_config = {
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
            "sample_collection_enabled": sample_collection_enabled,
        }
        if aux_scope == CLASSIFICATION_CHANNEL_ROLE:
            setClassificationChannelDetectionConfig(target_config)
            self._rebuild_rt_runner_for_feeder_role(CLASSIFICATION_CHANNEL_ROLE)
        else:
            setCarouselDetectionConfig(target_config)

        algorithm_label = _detection_algorithm_label(algorithm_scope, algorithm)
        uses_baseline = _detection_algorithm_uses_baseline(algorithm_scope, algorithm)
        scope_label = (
            "Classification C-channel (C4)"
            if aux_scope == CLASSIFICATION_CHANNEL_ROLE
            else "Carousel"
        )
        sample_collection_supported = _auxiliary_sample_collection_supported(
            vision_manager
        )
        return {
            "ok": True,
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
            "sample_collection_enabled": sample_collection_enabled,
            "sample_collection_supported": sample_collection_supported,
            "uses_baseline": uses_baseline,
            "scope": aux_scope,
            "message": (
                f"{scope_label} detection switched to {algorithm_label}. "
                "Capture a fresh baseline if detection stays unavailable. "
                "Event-driven Gemini teacher sample collection is enabled for classical triggers."
                if uses_baseline and sample_collection_enabled and sample_collection_supported
                else (
                    f"{scope_label} detection switched to {algorithm_label}. "
                    "Event-driven Gemini teacher sample collection is enabled "
                    "and will take effect when Heatmap Diff is active."
                    if sample_collection_enabled and sample_collection_supported
                    else (
                        f"{scope_label} detection switched to {algorithm_label}. "
                        "Capture a fresh baseline if detection stays unavailable. "
                        "Event-driven Gemini teacher sample collection is unavailable "
                        "for the current camera setup."
                        if uses_baseline and not sample_collection_supported
                        else (
                            f"{scope_label} detection switched to {algorithm_label}. "
                            "Event-driven Gemini teacher sample collection is unavailable "
                            "for the current camera setup."
                            if not sample_collection_supported
                            else (
                                f"{scope_label} detection switched to {algorithm_label}. "
                                "Capture a fresh baseline if detection stays unavailable."
                                if uses_baseline
                                else f"{scope_label} detection switched to {algorithm_label}."
                            )
                        )
                    )
                )
            ),
        }

    def _rebuild_rt_runner_for_feeder_role(self, feeder_role: str | None) -> None:
        handle = self.rt_handle
        if handle is None or not hasattr(handle, "rebuild_runner_for_role"):
            return
        targets: list[str] = []
        if feeder_role is None:
            for key in ("c_channel_2", "c_channel_3"):
                rt_role = _FEEDER_ROLE_KEY_TO_RT_ROLE.get(key)
                if rt_role:
                    targets.append(rt_role)
        else:
            rt_role = _FEEDER_ROLE_KEY_TO_RT_ROLE.get(feeder_role)
            if rt_role:
                targets.append(rt_role)
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
