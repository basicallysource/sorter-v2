"""Detection configuration, API keys, training library, and detection test/debug endpoints."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from blob_manager import (
    BLOB_DIR,
    getApiKeys,
    getCarouselDetectionConfig,
    getClassificationDetectionConfig,
    getFeederDetectionConfig,
    setApiKeys,
    setCarouselDetectionConfig,
    setClassificationDetectionConfig,
    setFeederDetectionConfig,
)
from server import shared_state
from server.classification_training import getClassificationTrainingManager
from server.local_detector_models import get_local_detector_model, local_detector_model_options
from vision.detection_registry import (
    detection_algorithm_definition,
    detection_algorithm_options,
    normalize_detection_algorithm,
    scope_supports_detection_algorithm,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_API_KEY_PROVIDERS = ("google", "openrouter")

# ---------------------------------------------------------------------------
# Detection algorithm helper functions
# ---------------------------------------------------------------------------


def _normalize_classification_detection_algorithm(value: str | None) -> str:
    return normalize_detection_algorithm("classification", value)


def _normalize_feeder_detection_algorithm(value: str | None) -> str:
    return normalize_detection_algorithm("feeder", value)


def _normalize_carousel_detection_algorithm(value: str | None) -> str:
    return normalize_detection_algorithm("carousel", value)


def _detection_algorithm_label(scope: str, algorithm: str | None) -> str:
    definition = detection_algorithm_definition(normalize_detection_algorithm(scope, algorithm))
    if definition is None:
        return (algorithm or "detection").replace("_", " ")
    return definition.label


def _detection_algorithm_uses_baseline(scope: str, algorithm: str | None) -> bool:
    definition = detection_algorithm_definition(normalize_detection_algorithm(scope, algorithm))
    return bool(definition is not None and definition.needs_baseline)


def _normalize_openrouter_model(value: str | None) -> str:
    from vision.gemini_sam_detector import normalize_openrouter_model

    return normalize_openrouter_model(value)


def _supported_openrouter_models() -> tuple[str, ...]:
    from vision.gemini_sam_detector import SUPPORTED_OPENROUTER_MODELS

    return SUPPORTED_OPENROUTER_MODELS


def _auxiliary_sample_collection_supported() -> bool:
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "supportsCarouselSampleCollection"):
        try:
            return bool(shared_state.vision_manager.supportsCarouselSampleCollection())
        except Exception:
            return False
    return True


def _feeder_sample_collection_supported(role: str | None = None) -> bool:
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "supportsFeederSampleCollection"):
        try:
            return bool(shared_state.vision_manager.supportsFeederSampleCollection(role))
        except Exception:
            return False
    return True


def _normalize_feeder_role(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate not in {"c_channel_2", "c_channel_3"}:
        raise HTTPException(status_code=400, detail="Unsupported feeder role.")
    return candidate


def _feeder_role_label(role: str | None) -> str:
    if role == "c_channel_2":
        return "C-channel 2"
    if role == "c_channel_3":
        return "C-channel 3"
    return "C-channel"


def _openrouter_model_label(model: str) -> str:
    if model == "google/gemini-3-flash-preview":
        return "Gemini 3 Flash Preview"
    if model == "google/gemini-3.1-flash-lite-preview":
        return "Gemini 3.1 Flash-Lite Preview"
    if model == "google/gemini-3.1-pro-preview":
        return "Gemini 3.1 Pro Preview"
    if model == "reka/reka-edge":
        return "Reka Edge"
    if model == "anthropic/claude-sonnet-4.6":
        return "Claude Sonnet 4.6"
    if model == "xiaomi/mimo-v2-omni":
        return "MiMo-V2-Omni"
    if model == "moonshotai/kimi-k2.5":
        return "Kimi K2.5"
    if model == "openai/gpt-5.4":
        return "GPT-5.4"
    if model == "openai/gpt-5.4-nano":
        return "GPT-5.4 Nano"
    if model == "qwen/qwen3.5-flash-02-23":
        return "Qwen3.5-Flash"
    return model


def _openrouter_model_options() -> list[dict[str, str]]:
    return [
        {
            "id": model,
            "label": _openrouter_model_label(model),
        }
        for model in _supported_openrouter_models()
    ]


def _available_retest_model_options() -> list[dict[str, str]]:
    return [*local_detector_model_options(), *_openrouter_model_options()]


def _normalize_retest_model_id(value: str | None) -> str:
    local_model = get_local_detector_model(value)
    if local_model is not None:
        return local_model.id
    return _normalize_openrouter_model(value)


# ---------------------------------------------------------------------------
# Bbox normalization helper
# ---------------------------------------------------------------------------


def _normalize_bbox(
    bbox: list[int] | tuple[int, int, int, int] | None,
    frame_resolution: list[int] | tuple[int, int] | None,
) -> list[float] | None:
    if bbox is None or frame_resolution is None or len(frame_resolution) != 2:
        return None
    frame_w = int(frame_resolution[0])
    frame_h = int(frame_resolution[1])
    if frame_w <= 0 or frame_h <= 0:
        return None
    return [
        max(0.0, min(1.0, float(bbox[0]) / float(frame_w))),
        max(0.0, min(1.0, float(bbox[1]) / float(frame_h))),
        max(0.0, min(1.0, float(bbox[2]) / float(frame_w))),
        max(0.0, min(1.0, float(bbox[3]) / float(frame_h))),
    ]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ClassificationDetectionConfigPayload(BaseModel):
    algorithm: str
    openrouter_model: Optional[str] = None


class AuxiliaryDetectionConfigPayload(BaseModel):
    algorithm: str
    openrouter_model: Optional[str] = None
    sample_collection_enabled: Optional[bool] = None


class ClassificationSampleRetestPayload(BaseModel):
    model_id: Optional[str] = None
    openrouter_model: Optional[str] = None


class ClassificationSamplePromoteRetestPayload(BaseModel):
    retest_id: str


class ClassificationSampleReviewPayload(BaseModel):
    status: Optional[str] = None
    box_corrections: Optional[List[Dict[str, Any]]] = None
    added_boxes: Optional[List[Dict[str, Any]]] = None


class ApiKeySavePayload(BaseModel):
    provider: str
    key: str


# ---------------------------------------------------------------------------
# Classification baseline helpers
# ---------------------------------------------------------------------------


def _collect_classification_baseline_frames(
    capture: Any,
    sample_count: int = shared_state.CLASSIFICATION_BASELINE_SAMPLES,
    timeout_s: float = shared_state.CLASSIFICATION_BASELINE_CAPTURE_TIMEOUT_S,
    interval_s: float = shared_state.CLASSIFICATION_BASELINE_CAPTURE_INTERVAL_S,
) -> List[np.ndarray]:
    frames: List[np.ndarray] = []
    deadline = time.monotonic() + timeout_s
    last_timestamp: float | None = None
    last_accept_at = 0.0

    while len(frames) < sample_count and time.monotonic() < deadline:
        frame = getattr(capture, "latest_frame", None)
        now = time.monotonic()
        if frame is None:
            time.sleep(interval_s)
            continue

        timestamp = float(getattr(frame, "timestamp", 0.0) or 0.0)
        if (
            last_timestamp is not None
            and timestamp == last_timestamp
            and (now - last_accept_at) < interval_s * 1.5
        ):
            time.sleep(interval_s)
            continue

        gray = cv2.cvtColor(frame.raw, cv2.COLOR_BGR2GRAY)
        frames.append(gray.copy())
        last_timestamp = timestamp
        last_accept_at = now
        time.sleep(interval_s)

    return frames


def _write_classification_baseline_frames(
    baseline_dir: Path,
    prefix: str,
    frames: List[np.ndarray],
) -> Dict[str, Any]:
    for old_path in baseline_dir.glob(f"{prefix}_*.png"):
        old_path.unlink(missing_ok=True)

    for index, gray in enumerate(frames):
        cv2.imwrite(str(baseline_dir / f"{prefix}_frame_{index:03d}.png"), gray)

    stack = np.stack(frames, axis=0)
    baseline_min = np.min(stack, axis=0).astype(np.uint8)
    baseline_max = np.max(stack, axis=0).astype(np.uint8)
    cv2.imwrite(str(baseline_dir / f"{prefix}_baseline_min.png"), baseline_min)
    cv2.imwrite(str(baseline_dir / f"{prefix}_baseline_max.png"), baseline_max)

    height, width = baseline_min.shape[:2]
    return {
        "available": True,
        "captured_frames": len(frames),
        "resolution": [width, height],
    }


# ---------------------------------------------------------------------------
# Training sample serialization helpers
# ---------------------------------------------------------------------------


def _classification_training_asset_url(session_id: str, rel_path: str | None) -> str | None:
    if not isinstance(rel_path, str) or not rel_path:
        return None
    return f"/api/classification/training/sessions/{session_id}/file/{rel_path}"


def _serialize_training_sample_summary(sample: Dict[str, Any]) -> Dict[str, Any]:
    session_id = sample.get("session_id") if isinstance(sample.get("session_id"), str) else None
    classification_result = (
        sample.get("classification_result")
        if isinstance(sample.get("classification_result"), dict)
        else None
    )
    return {
        **sample,
        "input_image_url": _classification_training_asset_url(session_id, sample.get("input_image_rel")) if session_id else None,
        "overlay_image_url": _classification_training_asset_url(session_id, sample.get("overlay_image_rel")) if session_id else None,
        "top_frame_url": _classification_training_asset_url(session_id, sample.get("top_frame_rel")) if session_id else None,
        "bottom_frame_url": _classification_training_asset_url(session_id, sample.get("bottom_frame_rel")) if session_id else None,
        "classification_result": (
            {
                **classification_result,
                "selected_crop_url": _classification_training_asset_url(session_id, classification_result.get("selected_crop_rel")),
                "top_crop_url": _classification_training_asset_url(session_id, classification_result.get("top_crop_rel")),
                "bottom_crop_url": _classification_training_asset_url(session_id, classification_result.get("bottom_crop_rel")),
                "result_json_url": _classification_training_asset_url(session_id, classification_result.get("result_json_rel")),
            }
            if session_id and classification_result is not None
            else classification_result
        ),
        "detail_url": (
            f"/classification-samples/{session_id}/{sample.get('sample_id')}"
            if session_id and isinstance(sample.get("sample_id"), str)
            else None
        ),
    }


def _serialize_training_sample_detail(sample: Dict[str, Any]) -> Dict[str, Any]:
    session_id = sample.get("session_id") if isinstance(sample.get("session_id"), str) else None
    distill_result = sample.get("distill_result") if isinstance(sample.get("distill_result"), dict) else None
    retests = sample.get("retests") if isinstance(sample.get("retests"), list) else []
    classification_result = (
        sample.get("classification_result")
        if isinstance(sample.get("classification_result"), dict)
        else None
    )
    return {
        **sample,
        "input_image_url": _classification_training_asset_url(session_id, sample.get("input_image_rel")) if session_id else None,
        "top_zone_url": _classification_training_asset_url(session_id, sample.get("top_zone_rel")) if session_id else None,
        "bottom_zone_url": _classification_training_asset_url(session_id, sample.get("bottom_zone_rel")) if session_id else None,
        "top_frame_url": _classification_training_asset_url(session_id, sample.get("top_frame_rel")) if session_id else None,
        "bottom_frame_url": _classification_training_asset_url(session_id, sample.get("bottom_frame_rel")) if session_id else None,
        "classification_result": (
            {
                **classification_result,
                "selected_crop_url": _classification_training_asset_url(session_id, classification_result.get("selected_crop_rel")),
                "top_crop_url": _classification_training_asset_url(session_id, classification_result.get("top_crop_rel")),
                "bottom_crop_url": _classification_training_asset_url(session_id, classification_result.get("bottom_crop_rel")),
                "result_json_url": _classification_training_asset_url(session_id, classification_result.get("result_json_rel")),
            }
            if session_id and classification_result is not None
            else classification_result
        ),
        "distill_result": (
            {
                **distill_result,
                "overlay_image_url": _classification_training_asset_url(session_id, distill_result.get("overlay_image_rel")),
                "result_json_url": _classification_training_asset_url(session_id, distill_result.get("result_json_rel")),
                "yolo_label_url": _classification_training_asset_url(session_id, distill_result.get("yolo_label_rel")),
            }
            if session_id and distill_result is not None
            else distill_result
        ),
        "retests": [
            {
                **retest,
                "overlay_image_url": _classification_training_asset_url(session_id, retest.get("overlay_image_rel")),
                "result_json_url": _classification_training_asset_url(session_id, retest.get("result_json_rel")),
            }
            for retest in retests
            if isinstance(retest, dict)
        ],
    }


# ---------------------------------------------------------------------------
# API keys endpoints
# ---------------------------------------------------------------------------


@router.get("/api/settings/api-keys")
def get_api_keys() -> Dict[str, Any]:
    saved = getApiKeys()
    masked: Dict[str, str | None] = {}
    for provider in SUPPORTED_API_KEY_PROVIDERS:
        key = saved.get(provider) or os.environ.get(
            "GOOGLE_API_KEY" if provider == "google" else "OPENROUTER_API_KEY", ""
        )
        if key:
            masked[provider] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        else:
            masked[provider] = None
    return {"ok": True, "keys": masked}


@router.post("/api/settings/api-keys")
def save_api_key(payload: ApiKeySavePayload) -> Dict[str, Any]:
    if payload.provider not in SUPPORTED_API_KEY_PROVIDERS:
        raise HTTPException(400, f"Unsupported provider '{payload.provider}'.")
    saved = getApiKeys()
    saved[payload.provider] = payload.key.strip()
    setApiKeys(saved)
    env_var = "GOOGLE_API_KEY" if payload.provider == "google" else "OPENROUTER_API_KEY"
    os.environ[env_var] = payload.key.strip()
    return {"ok": True, "message": f"API key for {payload.provider} saved and activated."}


# ---------------------------------------------------------------------------
# Classification detection config
# ---------------------------------------------------------------------------


@router.get("/api/classification/detection-config")
def get_classification_detection_config() -> Dict[str, Any]:
    saved = getClassificationDetectionConfig()
    algorithm = _normalize_classification_detection_algorithm(
        saved.get("algorithm") if isinstance(saved, dict) else None
    )
    openrouter_model = _normalize_openrouter_model(
        saved.get("openrouter_model") if isinstance(saved, dict) else None
    )
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "getClassificationDetectionAlgorithm"):
        try:
            algorithm = _normalize_classification_detection_algorithm(
                shared_state.vision_manager.getClassificationDetectionAlgorithm()
            )
        except Exception:
            pass
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "getClassificationOpenRouterModel"):
        try:
            openrouter_model = _normalize_openrouter_model(
                shared_state.vision_manager.getClassificationOpenRouterModel()
            )
        except Exception:
            pass
    return {
        "ok": True,
        "algorithm": algorithm,
        "openrouter_model": openrouter_model,
        "available_algorithms": detection_algorithm_options("classification"),
        "available_openrouter_models": _openrouter_model_options(),
    }


@router.post("/api/classification/detection-config")
def save_classification_detection_config(
    payload: ClassificationDetectionConfigPayload,
) -> Dict[str, Any]:
    if not scope_supports_detection_algorithm("classification", payload.algorithm):
        raise HTTPException(status_code=400, detail="Unsupported classification detection algorithm.")
    algorithm = _normalize_classification_detection_algorithm(payload.algorithm)
    openrouter_model = _normalize_openrouter_model(payload.openrouter_model)
    setClassificationDetectionConfig(
        {
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
        }
    )
    baseline_loaded = False
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setClassificationDetectionAlgorithm"):
        try:
            baseline_loaded = bool(shared_state.vision_manager.setClassificationDetectionAlgorithm(algorithm))
            if hasattr(shared_state.vision_manager, "setClassificationOpenRouterModel"):
                shared_state.vision_manager.setClassificationOpenRouterModel(openrouter_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to apply classification detection config: {exc}")

    algorithm_label = _detection_algorithm_label("classification", algorithm)
    uses_baseline = _detection_algorithm_uses_baseline("classification", algorithm)
    message = (
        f"Classification chamber detection switched to {algorithm_label}."
        if uses_baseline and baseline_loaded
        else (
            f"Classification chamber detection switched to {algorithm_label}. Capture an empty baseline if detection stays unavailable."
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


# ---------------------------------------------------------------------------
# Feeder detection config
# ---------------------------------------------------------------------------


@router.get("/api/feeder/detection-config")
def get_feeder_detection_config(role: str | None = Query(default=None)) -> Dict[str, Any]:
    role = _normalize_feeder_role(role)
    saved = getFeederDetectionConfig()
    algorithm = _normalize_feeder_detection_algorithm(
        saved.get("algorithm") if isinstance(saved, dict) else None
    )
    openrouter_model = _normalize_openrouter_model(
        saved.get("openrouter_model") if isinstance(saved, dict) else None
    )
    saved_by_role = (
        saved.get("sample_collection_enabled_by_role")
        if isinstance(saved, dict) and isinstance(saved.get("sample_collection_enabled_by_role"), dict)
        else {}
    )
    sample_collection_enabled_by_role = {
        channel_role: bool(saved_by_role.get(channel_role, saved.get("sample_collection_enabled")))
        if isinstance(saved, dict)
        else False
        for channel_role in ("c_channel_2", "c_channel_3")
    }
    sample_collection_enabled = (
        bool(sample_collection_enabled_by_role.get(role))
        if role is not None
        else any(sample_collection_enabled_by_role.values())
    )
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "getFeederDetectionAlgorithm"):
        try:
            algorithm = _normalize_feeder_detection_algorithm(shared_state.vision_manager.getFeederDetectionAlgorithm())
        except Exception:
            pass
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "getFeederOpenRouterModel"):
        try:
            openrouter_model = _normalize_openrouter_model(shared_state.vision_manager.getFeederOpenRouterModel())
        except Exception:
            pass
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "isFeederSampleCollectionEnabled"):
        try:
            sample_collection_enabled_by_role = {
                channel_role: bool(shared_state.vision_manager.isFeederSampleCollectionEnabled(channel_role))
                for channel_role in ("c_channel_2", "c_channel_3")
            }
            sample_collection_enabled = (
                bool(sample_collection_enabled_by_role.get(role))
                if role is not None
                else any(sample_collection_enabled_by_role.values())
            )
        except Exception:
            sample_collection_enabled = False
    sample_collection_supported = _feeder_sample_collection_supported(role)
    return {
        "ok": True,
        "role": role,
        "algorithm": algorithm,
        "openrouter_model": openrouter_model,
        "sample_collection_enabled": sample_collection_enabled,
        "sample_collection_enabled_by_role": sample_collection_enabled_by_role,
        "sample_collection_supported": sample_collection_supported,
        "available_algorithms": detection_algorithm_options("feeder"),
        "available_openrouter_models": _openrouter_model_options(),
    }


@router.post("/api/feeder/detection-config")
def save_feeder_detection_config(
    payload: AuxiliaryDetectionConfigPayload,
    role: str | None = Query(default=None),
) -> Dict[str, Any]:
    role = _normalize_feeder_role(role)
    if not scope_supports_detection_algorithm("feeder", payload.algorithm):
        raise HTTPException(status_code=400, detail="Unsupported feeder detection algorithm.")
    algorithm = _normalize_feeder_detection_algorithm(payload.algorithm)
    openrouter_model = _normalize_openrouter_model(payload.openrouter_model)
    saved = getFeederDetectionConfig()
    saved_by_role = (
        saved.get("sample_collection_enabled_by_role")
        if isinstance(saved, dict) and isinstance(saved.get("sample_collection_enabled_by_role"), dict)
        else {}
    )
    sample_collection_enabled_by_role = {
        channel_role: bool(saved_by_role.get(channel_role, saved.get("sample_collection_enabled")))
        if isinstance(saved, dict)
        else False
        for channel_role in ("c_channel_2", "c_channel_3")
    }
    if isinstance(payload.sample_collection_enabled, bool):
        if role is not None:
            sample_collection_enabled_by_role[role] = bool(payload.sample_collection_enabled)
        else:
            for channel_role in ("c_channel_2", "c_channel_3"):
                sample_collection_enabled_by_role[channel_role] = bool(payload.sample_collection_enabled)
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setFeederDetectionAlgorithm"):
        try:
            shared_state.vision_manager.setFeederDetectionAlgorithm(algorithm)
            if hasattr(shared_state.vision_manager, "setFeederOpenRouterModel"):
                shared_state.vision_manager.setFeederOpenRouterModel(openrouter_model)
            if hasattr(shared_state.vision_manager, "setFeederSampleCollectionEnabled"):
                if role is not None:
                    sample_collection_enabled_by_role[role] = bool(
                        shared_state.vision_manager.setFeederSampleCollectionEnabled(
                            sample_collection_enabled_by_role[role], role
                        )
                    )
                else:
                    for channel_role in ("c_channel_2", "c_channel_3"):
                        sample_collection_enabled_by_role[channel_role] = bool(
                            shared_state.vision_manager.setFeederSampleCollectionEnabled(
                                sample_collection_enabled_by_role[channel_role],
                                channel_role,
                            )
                        )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to apply feeder detection config: {exc}")
    sample_collection_enabled = (
        bool(sample_collection_enabled_by_role.get(role))
        if role is not None
        else any(sample_collection_enabled_by_role.values())
    )
    setFeederDetectionConfig(
        {
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
            "sample_collection_enabled": sample_collection_enabled,
            "sample_collection_enabled_by_role": sample_collection_enabled_by_role,
        }
    )
    role_label = _feeder_role_label(role)
    message = f"{role_label} detection uses {_detection_algorithm_label('feeder', algorithm)}."
    sample_collection_supported = _feeder_sample_collection_supported(role)
    if sample_collection_supported:
        if sample_collection_enabled:
            message += f" Event-driven Gemini teacher sample collection is enabled for {role_label.lower()} moves."
        elif role is not None:
            message += f" Event-driven Gemini teacher sample collection is disabled for {role_label.lower()} moves."
    else:
        message += f" Event-driven Gemini teacher sample collection is unavailable for {role_label.lower()} in the current camera setup."
    return {
        "ok": True,
        "role": role,
        "algorithm": algorithm,
        "openrouter_model": openrouter_model,
        "sample_collection_enabled": sample_collection_enabled,
        "sample_collection_enabled_by_role": sample_collection_enabled_by_role,
        "sample_collection_supported": sample_collection_supported,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Carousel detection config
# ---------------------------------------------------------------------------


@router.get("/api/carousel/detection-config")
def get_carousel_detection_config() -> Dict[str, Any]:
    saved = getCarouselDetectionConfig()
    algorithm = _normalize_carousel_detection_algorithm(
        saved.get("algorithm") if isinstance(saved, dict) else None
    )
    openrouter_model = _normalize_openrouter_model(
        saved.get("openrouter_model") if isinstance(saved, dict) else None
    )
    sample_collection_enabled = bool(saved.get("sample_collection_enabled")) if isinstance(saved, dict) else False
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "getCarouselDetectionAlgorithm"):
        try:
            algorithm = _normalize_carousel_detection_algorithm(shared_state.vision_manager.getCarouselDetectionAlgorithm())
        except Exception:
            pass
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "getCarouselOpenRouterModel"):
        try:
            openrouter_model = _normalize_openrouter_model(shared_state.vision_manager.getCarouselOpenRouterModel())
        except Exception:
            pass
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "isCarouselSampleCollectionEnabled"):
        try:
            sample_collection_enabled = bool(shared_state.vision_manager.isCarouselSampleCollectionEnabled())
        except Exception:
            sample_collection_enabled = False
    return {
        "ok": True,
        "algorithm": algorithm,
        "openrouter_model": openrouter_model,
        "sample_collection_enabled": sample_collection_enabled,
        "sample_collection_supported": _auxiliary_sample_collection_supported(),
        "available_algorithms": detection_algorithm_options("carousel"),
        "available_openrouter_models": _openrouter_model_options(),
    }


@router.post("/api/carousel/detection-config")
def save_carousel_detection_config(
    payload: AuxiliaryDetectionConfigPayload,
) -> Dict[str, Any]:
    if not scope_supports_detection_algorithm("carousel", payload.algorithm):
        raise HTTPException(status_code=400, detail="Unsupported carousel detection algorithm.")
    algorithm = _normalize_carousel_detection_algorithm(payload.algorithm)
    openrouter_model = _normalize_openrouter_model(payload.openrouter_model)
    saved = getCarouselDetectionConfig()
    sample_collection_enabled = (
        bool(payload.sample_collection_enabled)
        if isinstance(payload.sample_collection_enabled, bool)
        else bool(saved.get("sample_collection_enabled")) if isinstance(saved, dict) else False
    )
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setCarouselDetectionAlgorithm"):
        try:
            shared_state.vision_manager.setCarouselDetectionAlgorithm(algorithm)
            if hasattr(shared_state.vision_manager, "setCarouselOpenRouterModel"):
                shared_state.vision_manager.setCarouselOpenRouterModel(openrouter_model)
            if hasattr(shared_state.vision_manager, "setCarouselSampleCollectionEnabled"):
                sample_collection_enabled = bool(
                    shared_state.vision_manager.setCarouselSampleCollectionEnabled(sample_collection_enabled)
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to apply carousel detection config: {exc}")
    setCarouselDetectionConfig(
        {
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
            "sample_collection_enabled": sample_collection_enabled,
        }
    )
    algorithm_label = _detection_algorithm_label("carousel", algorithm)
    uses_baseline = _detection_algorithm_uses_baseline("carousel", algorithm)
    return {
        "ok": True,
        "algorithm": algorithm,
        "openrouter_model": openrouter_model,
        "sample_collection_enabled": sample_collection_enabled,
        "sample_collection_supported": _auxiliary_sample_collection_supported(),
        "uses_baseline": uses_baseline,
        "message": (
            f"Carousel detection switched to {algorithm_label}. Capture a fresh baseline if detection stays unavailable. Event-driven Gemini teacher sample collection is enabled for classical carousel triggers."
            if uses_baseline and sample_collection_enabled and _auxiliary_sample_collection_supported()
            else (
                f"Carousel detection switched to {algorithm_label}. Event-driven Gemini teacher sample collection is enabled and will take effect when Heatmap Diff is active."
                if sample_collection_enabled and _auxiliary_sample_collection_supported()
                else (
                    f"Carousel detection switched to {algorithm_label}. Capture a fresh baseline if detection stays unavailable. Event-driven Gemini teacher sample collection is unavailable for the current camera setup."
                    if uses_baseline and not _auxiliary_sample_collection_supported()
                    else (
                        f"Carousel detection switched to {algorithm_label}. Event-driven Gemini teacher sample collection is unavailable for the current camera setup."
                        if not _auxiliary_sample_collection_supported()
                        else (
                            f"Carousel detection switched to {algorithm_label}. Capture a fresh baseline if detection stays unavailable."
                            if uses_baseline
                            else f"Carousel detection switched to {algorithm_label}."
                        )
                    )
                )
            )
        ),
    }


# ---------------------------------------------------------------------------
# Carousel baseline capture
# ---------------------------------------------------------------------------


@router.post("/api/carousel/detection/baseline/capture")
def capture_carousel_detection_baseline() -> Dict[str, Any]:
    if shared_state.vision_manager is None:
        raise HTTPException(status_code=503, detail="Vision manager not initialized.")
    ok = bool(shared_state.vision_manager.captureCarouselBaseline())
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Could not capture a carousel baseline. Check the live carousel frame and saved zone first.",
        )
    resolution = None
    capture = shared_state.vision_manager.getCaptureThreadForRole("carousel") if hasattr(shared_state.vision_manager, "getCaptureThreadForRole") else None
    frame = capture.latest_frame if capture is not None else None
    if frame is not None:
        resolution = [int(frame.raw.shape[1]), int(frame.raw.shape[0])]
    return {
        "ok": True,
        "message": "Carousel baseline captured from the current live frame.",
        "cameras": {
            "carousel": {
                "available": True,
                "captured_frames": 1,
                "resolution": resolution,
            }
        },
    }


# ---------------------------------------------------------------------------
# Classification training library CRUD
# ---------------------------------------------------------------------------


@router.get("/api/classification/training/library")
def get_classification_training_library(
    page: int = Query(1, ge=1),
    page_size: int = Query(36, ge=1, le=120),
    search: str | None = None,
    session_id: str | None = None,
    detection_scope: str | None = None,
    source_role: str | None = None,
    capture_reason: str | None = None,
    detection_algorithm: str | None = None,
    classification_status: str | None = None,
    has_classification_result: bool | None = None,
    review_status: str | None = None,
    sort_by: str = Query("captured_at"),
    sort_dir: str = Query("desc"),
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    payload = manager.queryLibrary(
        page=page,
        page_size=page_size,
        search=search,
        session_id=session_id,
        detection_scope=detection_scope,
        source_role=source_role,
        capture_reason=capture_reason,
        detection_algorithm=detection_algorithm,
        classification_status=classification_status,
        has_classification_result=has_classification_result,
        review_status=review_status,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    return {
        "ok": True,
        "sessions": payload.get("sessions", []),
        "pagination": payload.get("pagination", {}),
        "facets": payload.get("facets", {}),
        "query": payload.get("query", {}),
        "worker_status": manager.getWorkerStatus(),
        "samples": [
            _serialize_training_sample_summary(sample)
            for sample in payload.get("samples", [])
            if isinstance(sample, dict)
        ],
    }


@router.get("/api/classification/training/worker-status")
def get_classification_training_worker_status() -> Dict[str, Any]:
    return {
        "ok": True,
        "worker_status": getClassificationTrainingManager().getWorkerStatus(),
    }


@router.post("/api/classification/training/library/clear")
def clear_classification_training_library(
    distill_status: str = Query(...),
    search: str | None = None,
    session_id: str | None = None,
    detection_scope: str | None = None,
    source_role: str | None = None,
    capture_reason: str | None = None,
    detection_algorithm: str | None = None,
    classification_status: str | None = None,
    has_classification_result: bool | None = None,
    review_status: str | None = None,
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        result = manager.clearLibrarySamples(
            distill_status=distill_status,
            search=search,
            session_id=session_id,
            detection_scope=detection_scope,
            source_role=source_role,
            capture_reason=capture_reason,
            detection_algorithm=detection_algorithm,
            classification_status=classification_status,
            has_classification_result=has_classification_result,
            review_status=review_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to clear classification samples: {exc}")
    return result


@router.post("/api/classification/training/library/retry")
def retry_classification_training_library(
    distill_status: str = Query(...),
    search: str | None = None,
    session_id: str | None = None,
    detection_scope: str | None = None,
    source_role: str | None = None,
    capture_reason: str | None = None,
    detection_algorithm: str | None = None,
    classification_status: str | None = None,
    has_classification_result: bool | None = None,
    review_status: str | None = None,
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        result = manager.retryLibrarySamples(
            distill_status=distill_status,
            search=search,
            session_id=session_id,
            detection_scope=detection_scope,
            source_role=source_role,
            capture_reason=capture_reason,
            detection_algorithm=detection_algorithm,
            classification_status=classification_status,
            has_classification_result=has_classification_result,
            review_status=review_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to retry classification samples: {exc}")
    return result


@router.get("/api/classification/training/sessions/{session_id}/samples/{sample_id}")
def get_classification_training_sample_detail(session_id: str, sample_id: str) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        payload = manager.getSampleDetail(session_id, sample_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to load classification sample: {exc}")
    session = payload.get("session", {}) if isinstance(payload, dict) else {}
    sample = payload.get("sample", {}) if isinstance(payload, dict) else {}
    if isinstance(sample, dict):
        sample = _serialize_training_sample_detail(sample)
    return {
        "ok": True,
        "session": session,
        "sample": sample,
        "available_retest_models": _available_retest_model_options(),
        "available_openrouter_models": _openrouter_model_options(),
    }


@router.delete("/api/classification/training/sessions/{session_id}/samples/{sample_id}")
def delete_classification_training_sample(session_id: str, sample_id: str) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        result = manager.deleteSample(session_id, sample_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete classification sample: {exc}")
    return {
        "ok": True,
        "session_id": session_id,
        "sample_id": sample_id,
        "removed_session": bool(result.get("removed_session")),
    }


@router.post("/api/classification/training/sessions/{session_id}/samples/{sample_id}/review")
def review_classification_training_sample(
    session_id: str,
    sample_id: str,
    payload: ClassificationSampleReviewPayload,
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        sample = manager.setSampleReview(
            session_id, sample_id,
            status=payload.status,
            box_corrections=payload.box_corrections,
            added_boxes=payload.added_boxes,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail == "Unknown sample.":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update classification sample review: {exc}")
    return {
        "ok": True,
        "session_id": session_id,
        "sample_id": sample_id,
        "sample": _serialize_training_sample_detail(sample),
    }


@router.get("/api/classification/training/verify-next")
def get_next_unverified_sample() -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    sample = manager.getNextUnverifiedSample()
    if sample is None:
        return {"ok": True, "sample": None, "done": True}
    session_id = sample.pop("_session_id", None)
    return {
        "ok": True,
        "sample": _serialize_training_sample_detail(sample),
        "session_id": session_id,
        "done": False,
    }


@router.get("/api/classification/training/verify-stats")
def get_verify_stats() -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    stats = manager.getVerifyStats()
    return {"ok": True, **stats}


@router.post("/api/classification/training/sessions/{session_id}/samples/{sample_id}/retest")
def retest_classification_training_sample(
    session_id: str,
    sample_id: str,
    payload: ClassificationSampleRetestPayload,
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    model = _normalize_retest_model_id(payload.model_id or payload.openrouter_model)
    try:
        result = manager.runSampleRetest(session_id, sample_id, model_id=model)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to retest classification sample: {exc}")
    retest = result.get("retest", {}) if isinstance(result, dict) else {}
    if isinstance(retest, dict):
        retest = {
            **retest,
            "overlay_image_url": _classification_training_asset_url(session_id, retest.get("overlay_image_rel")),
            "result_json_url": _classification_training_asset_url(session_id, retest.get("result_json_rel")),
        }
    return {
        "ok": True,
        "session_id": session_id,
        "sample_id": sample_id,
        "retest": retest,
    }


@router.post("/api/classification/training/sessions/{session_id}/samples/{sample_id}/retest-all")
def retest_all_classification_training_sample(
    session_id: str,
    sample_id: str,
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        result = manager.runSampleRetests(
            session_id,
            sample_id,
            model_ids=[option["id"] for option in _available_retest_model_options() if isinstance(option, dict) and isinstance(option.get("id"), str)],
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to retest classification sample across all models: {exc}")
    retests = result.get("retests", []) if isinstance(result, dict) else []
    return {
        "ok": True,
        "session_id": session_id,
        "sample_id": sample_id,
        "completed_count": len(retests),
        "retests": [
            {
                **retest,
                "overlay_image_url": _classification_training_asset_url(session_id, retest.get("overlay_image_rel")),
                "result_json_url": _classification_training_asset_url(session_id, retest.get("result_json_rel")),
            }
            for retest in retests
            if isinstance(retest, dict)
        ],
    }


@router.post("/api/classification/training/sessions/{session_id}/samples/{sample_id}/promote-retest")
def promote_retest_to_ground_truth(
    session_id: str,
    sample_id: str,
    payload: ClassificationSamplePromoteRetestPayload,
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        result = manager.promoteRetestToGroundTruth(
            session_id, sample_id, retest_id=payload.retest_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail in ("Unknown sample.", "Unknown retest."):
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to promote retest to ground truth: {exc}")
    sample = result.get("sample", {})
    return {
        "ok": True,
        "session_id": session_id,
        "sample_id": sample_id,
        "sample": _serialize_training_sample_detail(sample),
    }


@router.delete("/api/classification/training/sessions/{session_id}/samples/{sample_id}/retests/{retest_id}")
def delete_classification_training_sample_retest(
    session_id: str,
    sample_id: str,
    retest_id: str,
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        result = manager.deleteSampleRetest(session_id, sample_id, retest_id=retest_id)
    except ValueError as exc:
        detail = str(exc)
        if detail in ("Unknown sample.", "Unknown retest.", "Unknown sample session."):
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete retest: {exc}")
    sample = result.get("sample", {})
    return {
        "ok": True,
        "session_id": session_id,
        "sample_id": sample_id,
        "retest_id": retest_id,
        "sample": _serialize_training_sample_detail(sample),
    }


@router.delete("/api/classification/training/sessions/{session_id}/samples/{sample_id}/retests")
def clear_classification_training_sample_retests(
    session_id: str,
    sample_id: str,
) -> Dict[str, Any]:
    manager = getClassificationTrainingManager()
    try:
        result = manager.clearSampleRetests(session_id, sample_id)
    except ValueError as exc:
        detail = str(exc)
        if detail in ("Unknown sample.", "Unknown sample session."):
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to clear retests: {exc}")
    sample = result.get("sample", {})
    return {
        "ok": True,
        "session_id": session_id,
        "sample_id": sample_id,
        "sample": _serialize_training_sample_detail(sample),
    }


# ---------------------------------------------------------------------------
# Training asset file endpoint
# ---------------------------------------------------------------------------


@router.get("/api/classification/training/sessions/{session_id}/file/{asset_path:path}")
def get_classification_training_asset(session_id: str, asset_path: str) -> FileResponse:
    manager = getClassificationTrainingManager()
    try:
        resolved = manager.resolveAssetPath(session_id, asset_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return FileResponse(resolved)


# ---------------------------------------------------------------------------
# Detection debug/test endpoints
# ---------------------------------------------------------------------------


@router.post("/api/classification/detect/{camera}")
def debug_classification_detection(camera: str) -> Dict[str, Any]:
    if camera not in {"top", "bottom"}:
        raise HTTPException(status_code=400, detail="Unsupported classification camera.")
    if shared_state.vision_manager is None:
        raise HTTPException(status_code=503, detail="Vision manager not initialized.")
    if not hasattr(shared_state.vision_manager, "debugClassificationDetection"):
        raise HTTPException(status_code=503, detail="Classification detection debug is unavailable.")

    try:
        payload = shared_state.vision_manager.debugClassificationDetection(camera, include_capture=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to test classification detection: {exc}")

    sample_capture = payload.pop("_sample_capture", None) if isinstance(payload, dict) else None
    frame_resolution = payload.get("frame_resolution")
    bbox = payload.get("bbox")
    zone_bbox = payload.get("zone_bbox")
    candidate_bboxes = payload.get("candidate_bboxes")
    payload["normalized_bbox"] = _normalize_bbox(bbox, frame_resolution) if isinstance(bbox, (list, tuple)) else None
    payload["normalized_candidate_bboxes"] = (
        [
            normalized
            for normalized in (
                _normalize_bbox(candidate, frame_resolution) for candidate in candidate_bboxes
            )
            if normalized is not None
        ]
        if isinstance(candidate_bboxes, list)
        else []
    )
    payload["normalized_zone_bbox"] = (
        _normalize_bbox(zone_bbox, frame_resolution) if isinstance(zone_bbox, (list, tuple)) else None
    )
    if isinstance(sample_capture, dict):
        save_model = None
        if payload.get("algorithm") == "gemini_sam" and hasattr(shared_state.vision_manager, "getClassificationOpenRouterModel"):
            try:
                save_model = shared_state.vision_manager.getClassificationOpenRouterModel()
            except Exception:
                save_model = None
        try:
            saved = getClassificationTrainingManager().saveDetectionDebugCapture(
                camera=camera,
                algorithm=str(payload.get("algorithm") or ""),
                openrouter_model=save_model,
                debug_result=payload,
                top_zone=sample_capture.get("top_zone"),
                bottom_zone=sample_capture.get("bottom_zone"),
                top_frame=sample_capture.get("top_frame"),
                bottom_frame=sample_capture.get("bottom_frame"),
            )
            saved_sample_id = saved.get("sample_id")
            saved_session_id = saved.get("session_id")
            payload["saved_to_library"] = True
            payload["saved_sample_id"] = saved_sample_id if isinstance(saved_sample_id, str) else None
            payload["saved_session_id"] = saved_session_id if isinstance(saved_session_id, str) else None
            payload["saved_detail_url"] = (
                f"/classification-samples/{saved_session_id}/{saved_sample_id}"
                if isinstance(saved_session_id, str) and isinstance(saved_sample_id, str)
                else None
            )
        except Exception as exc:
            payload["saved_to_library"] = False
            payload["saved_sample_error"] = str(exc)
    payload["ok"] = True
    return payload


def _finalize_aux_detection_debug_payload(
    *,
    role: str,
    payload: Dict[str, Any],
    sample_capture: dict[str, Any] | None,
    openrouter_model: str | None,
) -> Dict[str, Any]:
    frame_resolution = payload.get("frame_resolution")
    bbox = payload.get("bbox")
    zone_bbox = payload.get("zone_bbox")
    candidate_bboxes = payload.get("candidate_bboxes")
    payload["normalized_bbox"] = _normalize_bbox(bbox, frame_resolution) if isinstance(bbox, (list, tuple)) else None
    payload["normalized_candidate_bboxes"] = (
        [
            normalized
            for normalized in (
                _normalize_bbox(candidate, frame_resolution) for candidate in candidate_bboxes
            )
            if normalized is not None
        ]
        if isinstance(candidate_bboxes, list)
        else []
    )
    payload["normalized_zone_bbox"] = (
        _normalize_bbox(zone_bbox, frame_resolution) if isinstance(zone_bbox, (list, tuple)) else None
    )
    if isinstance(sample_capture, dict) and _auxiliary_sample_collection_supported():
        try:
            saved = getClassificationTrainingManager().saveAuxiliaryDetectionCapture(
                source="settings_detection_test",
                source_role=role,
                detection_scope=(
                    "feeder" if role in {"c_channel_2", "c_channel_3"} else "carousel"
                ),
                capture_reason="settings_detection_test",
                detection_algorithm=str(payload.get("algorithm") or ""),
                detection_openrouter_model=openrouter_model,
                detection_found=bool(payload.get("found")),
                detection_bbox=bbox if isinstance(bbox, (list, tuple)) else None,
                detection_candidate_bboxes=candidate_bboxes if isinstance(candidate_bboxes, list) else [],
                detection_bbox_count=int(payload.get("bbox_count") or 0),
                detection_score=float(payload.get("score")) if isinstance(payload.get("score"), (int, float)) else None,
                detection_message=payload.get("message") if isinstance(payload.get("message"), str) else None,
                input_image=sample_capture.get("input_image"),
                source_frame=sample_capture.get("frame"),
            )
            saved_sample_id = saved.get("sample_id")
            saved_session_id = saved.get("session_id")
            payload["saved_to_library"] = True
            payload["saved_sample_id"] = saved_sample_id if isinstance(saved_sample_id, str) else None
            payload["saved_session_id"] = saved_session_id if isinstance(saved_session_id, str) else None
            payload["saved_detail_url"] = (
                f"/classification-samples/{saved_session_id}/{saved_sample_id}"
                if isinstance(saved_session_id, str) and isinstance(saved_sample_id, str)
                else None
            )
        except Exception as exc:
            payload["saved_to_library"] = False
            payload["saved_sample_error"] = str(exc)
    else:
        payload["saved_to_library"] = False
    payload["ok"] = True
    return payload


@router.post("/api/feeder/detect/{role}")
def debug_feeder_detection(role: str) -> Dict[str, Any]:
    if role not in {"c_channel_2", "c_channel_3"}:
        raise HTTPException(status_code=400, detail="Unsupported feeder role.")
    if shared_state.vision_manager is None:
        raise HTTPException(status_code=503, detail="Vision manager not initialized.")
    if not hasattr(shared_state.vision_manager, "debugFeederDetection"):
        raise HTTPException(status_code=503, detail="Feeder detection debug is unavailable.")

    try:
        payload = shared_state.vision_manager.debugFeederDetection(role, include_capture=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to test feeder detection: {exc}")

    sample_capture = payload.pop("_sample_capture", None) if isinstance(payload, dict) else None
    save_model = None
    if payload.get("algorithm") == "gemini_sam" and hasattr(shared_state.vision_manager, "getFeederOpenRouterModel"):
        try:
            save_model = shared_state.vision_manager.getFeederOpenRouterModel()
        except Exception:
            save_model = None
    return _finalize_aux_detection_debug_payload(
        role=role,
        payload=payload,
        sample_capture=sample_capture,
        openrouter_model=save_model,
    )


@router.post("/api/carousel/detect/current")
def debug_carousel_detection() -> Dict[str, Any]:
    if shared_state.vision_manager is None:
        raise HTTPException(status_code=503, detail="Vision manager not initialized.")
    if not hasattr(shared_state.vision_manager, "debugCarouselDetection"):
        raise HTTPException(status_code=503, detail="Carousel detection debug is unavailable.")

    try:
        payload = shared_state.vision_manager.debugCarouselDetection(include_capture=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to test carousel detection: {exc}")

    sample_capture = payload.pop("_sample_capture", None) if isinstance(payload, dict) else None
    save_model = None
    if payload.get("algorithm") == "gemini_sam" and hasattr(shared_state.vision_manager, "getCarouselOpenRouterModel"):
        try:
            save_model = shared_state.vision_manager.getCarouselOpenRouterModel()
        except Exception:
            save_model = None
    return _finalize_aux_detection_debug_payload(
        role="carousel",
        payload=payload,
        sample_capture=sample_capture,
        openrouter_model=save_model,
    )


# ---------------------------------------------------------------------------
# Classification baseline capture
# ---------------------------------------------------------------------------


@router.post("/api/classification/baseline/capture")
def capture_classification_baseline() -> Dict[str, Any]:
    if shared_state.vision_manager is None:
        raise HTTPException(status_code=503, detail="Vision manager not initialized.")

    baseline_dir = BLOB_DIR / "classification_baseline"
    baseline_dir.mkdir(parents=True, exist_ok=True)

    captures = {
        "top": shared_state.vision_manager.getCaptureThreadForRole("classification_top"),
        "bottom": shared_state.vision_manager.getCaptureThreadForRole("classification_bottom"),
    }
    available = {name: capture for name, capture in captures.items() if capture is not None}
    if not available:
        raise HTTPException(status_code=404, detail="No classification cameras are configured.")

    camera_results: Dict[str, Any] = {
        name: {"available": capture is not None, "captured_frames": 0}
        for name, capture in captures.items()
    }
    captured_any = False

    for prefix, capture in available.items():
        frames = _collect_classification_baseline_frames(capture)
        if len(frames) < 2:
            camera_results[prefix] = {
                "available": True,
                "captured_frames": len(frames),
                "error": "Not enough fresh frames were available.",
            }
            continue

        camera_results[prefix] = _write_classification_baseline_frames(baseline_dir, prefix, frames)
        captured_any = True

    if not captured_any:
        raise HTTPException(
            status_code=504,
            detail="Failed to capture enough classification baseline frames from the live cameras.",
        )

    reloaded = bool(shared_state.vision_manager.loadClassificationBaseline())
    if not reloaded:
        raise HTTPException(
            status_code=500,
            detail="Baseline images were captured, but the live classification baseline failed to reload.",
        )

    return {
        "ok": True,
        "message": "Classification baseline captured from the empty chamber and reloaded live.",
        "cameras": camera_results,
        "baseline_dir": str(baseline_dir),
    }
