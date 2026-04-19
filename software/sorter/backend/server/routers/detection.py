"""Detection configuration, API keys, and detection test/debug endpoints."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from blob_manager import (
    BLOB_DIR,
    getApiKeys,
    getCarouselDetectionConfig,
    getClassificationDetectionConfig,
    getFeederDetectionConfig,
    getHiveConfig,
    setApiKeys,
    setCarouselDetectionConfig,
    setClassificationDetectionConfig,
    setFeederDetectionConfig,
    setHiveConfig,
)
from server import shared_state
from server.classification_training import getClassificationTrainingManager
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

SUPPORTED_API_KEY_PROVIDERS = ("openrouter",)
FEEDER_DETECTION_ROLES = ("c_channel_2", "c_channel_3", "carousel")

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
    if candidate not in FEEDER_DETECTION_ROLES:
        raise HTTPException(status_code=400, detail="Unsupported feeder role.")
    return candidate


def _feeder_algorithm_by_role_from_config(
    config: dict[str, Any] | None,
) -> dict[str, str]:
    saved_by_role = (
        config.get("algorithm_by_role")
        if isinstance(config, dict) and isinstance(config.get("algorithm_by_role"), dict)
        else {}
    )
    fallback = config.get("algorithm") if isinstance(config, dict) else None
    return {
        role: _normalize_feeder_detection_algorithm(saved_by_role.get(role) or fallback)
        for role in FEEDER_DETECTION_ROLES
    }


def _feeder_role_label(role: str | None) -> str:
    if role == "c_channel_2":
        return "C-channel 2"
    if role == "c_channel_3":
        return "C-channel 3"
    if role == "carousel":
        return "Classification channel"
    return "C-channel"


def _openrouter_model_label(model: str) -> str:
    if model == "google/gemini-3-flash-preview":
        return "Gemini 3 Flash Preview"
    if model == "google/gemini-3.1-flash-lite-preview":
        return "Gemini 3.1 Flash-Lite Preview"
    if model == "google/gemini-3.1-pro-preview":
        return "Gemini 3.1 Pro Preview"
    return model


def _openrouter_model_options() -> list[dict[str, str]]:
    return [
        {
            "id": model,
            "label": _openrouter_model_label(model),
        }
        for model in _supported_openrouter_models()
    ]


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


class ApiKeySavePayload(BaseModel):
    provider: str
    key: str


class HiveTargetPayload(BaseModel):
    id: str | None = None
    name: str = ""
    url: str = ""
    api_token: str = ""
    enabled: bool = False


class HiveRegisterPayload(BaseModel):
    target_name: str = ""
    url: str
    email: str
    password: str
    machine_name: str
    machine_description: str = ""


class HiveBackfillPayload(BaseModel):
    session_ids: list[str] | None = None
    target_ids: list[str] | None = None


class HivePurgePayload(BaseModel):
    target_ids: list[str] | None = None


# ---------------------------------------------------------------------------
# Classification baseline helpers
# ---------------------------------------------------------------------------


def _collect_classification_baseline_frames(
    capture: Any,
    sample_count: int = shared_state.CLASSIFICATION_BASELINE_SAMPLES,
    timeout_s: float = shared_state.CLASSIFICATION_BASELINE_CAPTURE_TIMEOUT_S,
    interval_s: float = shared_state.CLASSIFICATION_BASELINE_CAPTURE_INTERVAL_S,
) -> list[np.ndarray]:
    frames: list[np.ndarray] = []
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
    frames: list[np.ndarray],
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
# API keys endpoints
# ---------------------------------------------------------------------------


@router.get("/api/settings/api-keys")
def get_api_keys() -> Dict[str, Any]:
    saved = getApiKeys()
    masked: Dict[str, str | None] = {}
    for provider in SUPPORTED_API_KEY_PROVIDERS:
        key = saved.get(provider) or os.environ.get("OPENROUTER_API_KEY", "")
        if key:
            masked[provider] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
        else:
            masked[provider] = None
    return {"ok": True, "keys": masked}


@router.post("/api/settings/api-keys")
def save_api_key(payload: ApiKeySavePayload) -> Dict[str, Any]:
    if payload.provider not in SUPPORTED_API_KEY_PROVIDERS:
        raise HTTPException(400, f"Unsupported provider '{payload.provider}'.")
    saved = {"openrouter": payload.key.strip()}
    setApiKeys(saved)
    os.environ["OPENROUTER_API_KEY"] = payload.key.strip()
    return {"ok": True, "message": f"API key for {payload.provider} saved and activated."}


# ---------------------------------------------------------------------------
# Hive upload config
# ---------------------------------------------------------------------------


def _load_hive_targets() -> list[dict[str, Any]]:
    config = getHiveConfig() or {}
    targets = config.get("targets")
    if not isinstance(targets, list):
        return []
    return [dict(target) for target in targets if isinstance(target, dict)]


def _save_hive_targets(targets: list[dict[str, Any]]) -> None:
    setHiveConfig({"targets": targets})


def _mask_hive_token(token: str | None) -> str | None:
    if not isinstance(token, str) or not token:
        return None
    return token[:8] + "..." + token[-4:] if len(token) > 12 else "***"


def _empty_hive_uploader_status(enabled: bool) -> Dict[str, Any]:
    return {
        "enabled": enabled,
        "server_reachable": False,
        "queue_size": 0,
        "uploaded": 0,
        "failed": 0,
        "requeued": 0,
        "last_error": None,
    }


@router.get("/api/settings/hive")
def get_hive_config() -> Dict[str, Any]:
    uploader_status = getClassificationTrainingManager().getHiveUploaderStatus()
    uploader_targets = uploader_status.get("targets") if isinstance(uploader_status, dict) else []
    uploader_by_id = {
        item.get("id"): item
        for item in uploader_targets
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    targets = _load_hive_targets()

    return {
        "ok": True,
        "configured_count": len(targets),
        "enabled_count": sum(1 for target in targets if bool(target.get("enabled", False))),
        "targets": [
            {
                "id": target["id"],
                "name": target.get("name") or target.get("url"),
                "url": target.get("url", ""),
                "machine_id": target.get("machine_id"),
                "api_token_masked": _mask_hive_token(target.get("api_token")),
                "enabled": bool(target.get("enabled", False)),
                "uploader": (
                    dict(uploader_by_id[target["id"]])
                    if target["id"] in uploader_by_id
                    else _empty_hive_uploader_status(bool(target.get("enabled", False)))
                ),
            }
            for target in targets
        ],
    }


@router.post("/api/settings/hive")
def save_hive_config(payload: HiveTargetPayload) -> Dict[str, Any]:
    targets = _load_hive_targets()
    target_id = payload.id.strip() if isinstance(payload.id, str) and payload.id.strip() else uuid4().hex[:12]
    existing = next((target for target in targets if target.get("id") == target_id), None)

    url = payload.url.strip().rstrip("/")
    if not url:
        raise HTTPException(400, "Hive URL is required.")

    api_token = ""
    if payload.api_token and not payload.api_token.endswith("..."):
        api_token = payload.api_token.strip()
    elif existing and isinstance(existing.get("api_token"), str):
        api_token = existing["api_token"]

    if not api_token:
        raise HTTPException(400, "Hive machine token is required.")

    next_target = {
        "id": target_id,
        "name": payload.name.strip() or (existing.get("name") if existing else "") or url,
        "url": url,
        "api_token": api_token,
        "machine_id": existing.get("machine_id") if existing else None,
        "enabled": payload.enabled,
    }

    if existing is None:
        targets.append(next_target)
    else:
        targets = [next_target if target.get("id") == target_id else target for target in targets]

    _save_hive_targets(targets)
    getClassificationTrainingManager().reloadHiveUploader()
    return {"ok": True, "message": "Hive target saved.", "target_id": target_id}


@router.delete("/api/settings/hive")
def clear_hive_config(target_id: str | None = Query(default=None)) -> Dict[str, Any]:
    if not target_id:
        _save_hive_targets([])
        getClassificationTrainingManager().reloadHiveUploader()
        return {"ok": True, "message": "All Hive targets removed."}

    targets = _load_hive_targets()
    next_targets = [target for target in targets if target.get("id") != target_id]
    if len(next_targets) == len(targets):
        raise HTTPException(404, "Hive target not found.")

    _save_hive_targets(next_targets)
    getClassificationTrainingManager().reloadHiveUploader()
    return {"ok": True, "message": "Hive target removed."}


@router.post("/api/settings/hive/register")
def hive_register(payload: HiveRegisterPayload) -> Dict[str, Any]:
    import requests

    base_url = payload.url.strip().rstrip("/")
    try:
        response = requests.post(
            f"{base_url}/api/machine/register",
            json={
                "email": payload.email,
                "password": payload.password,
                "machine_name": payload.machine_name,
                "machine_description": payload.machine_description,
            },
            timeout=15,
        )
    except Exception as exc:
        raise HTTPException(502, f"Could not reach Hive server: {exc}")

    if not response.ok:
        try:
            body = response.json()
            message = body.get("error", response.text)
        except Exception:
            message = response.text
        raise HTTPException(response.status_code, f"Hive registration failed: {message}")

    data = response.json()
    raw_token = data.get("raw_token", "")
    machine_id = data.get("id", "")

    targets = _load_hive_targets()
    target_id = uuid4().hex[:12]
    target_name = payload.target_name.strip() or base_url
    targets.append(
        {
            "id": target_id,
            "name": target_name,
            "url": base_url,
            "api_token": raw_token,
            "enabled": True,
            "machine_id": str(machine_id),
        }
    )
    _save_hive_targets(targets)
    getClassificationTrainingManager().reloadHiveUploader()
    return {
        "ok": True,
        "target_id": target_id,
        "target_name": target_name,
        "machine_id": str(machine_id),
        "machine_name": data.get("name", payload.machine_name),
        "token_prefix": data.get("token_prefix", raw_token[:8]),
    }


@router.post("/api/settings/hive/backfill")
def hive_backfill(payload: HiveBackfillPayload = HiveBackfillPayload()) -> Dict[str, Any]:
    return getClassificationTrainingManager().backfillToHive(
        session_ids=payload.session_ids,
        target_ids=payload.target_ids,
    )


@router.post("/api/settings/hive/purge")
def hive_purge(payload: HivePurgePayload = HivePurgePayload()) -> Dict[str, Any]:
    return getClassificationTrainingManager().purgeHiveQueue(target_ids=payload.target_ids)


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
    algorithm_by_role = _feeder_algorithm_by_role_from_config(saved if isinstance(saved, dict) else None)
    algorithm = (
        algorithm_by_role.get(role)
        if role is not None
        else _normalize_feeder_detection_algorithm(
            saved.get("algorithm") if isinstance(saved, dict) else None
        )
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
        for channel_role in FEEDER_DETECTION_ROLES
    }
    sample_collection_enabled = (
        bool(sample_collection_enabled_by_role.get(role))
        if role is not None
        else any(sample_collection_enabled_by_role.values())
    )
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "getFeederDetectionAlgorithm"):
        try:
            if hasattr(shared_state.vision_manager, "getFeederDetectionAlgorithms"):
                algorithm_by_role = {
                    channel_role: _normalize_feeder_detection_algorithm(algo)
                    for channel_role, algo in shared_state.vision_manager.getFeederDetectionAlgorithms().items()
                    if channel_role in FEEDER_DETECTION_ROLES
                }
                algorithm = (
                    algorithm_by_role.get(role)
                    if role is not None
                    else _normalize_feeder_detection_algorithm(
                        shared_state.vision_manager.getFeederDetectionAlgorithm()
                    )
                )
            else:
                algorithm = _normalize_feeder_detection_algorithm(
                    shared_state.vision_manager.getFeederDetectionAlgorithm(role)
                    if role is not None
                    else shared_state.vision_manager.getFeederDetectionAlgorithm()
                )
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
                for channel_role in FEEDER_DETECTION_ROLES
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
        "algorithm_by_role": algorithm_by_role,
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
    algorithm_by_role = _feeder_algorithm_by_role_from_config(saved if isinstance(saved, dict) else None)
    saved_by_role = (
        saved.get("sample_collection_enabled_by_role")
        if isinstance(saved, dict) and isinstance(saved.get("sample_collection_enabled_by_role"), dict)
        else {}
    )
    sample_collection_enabled_by_role = {
        channel_role: bool(saved_by_role.get(channel_role, saved.get("sample_collection_enabled")))
        if isinstance(saved, dict)
        else False
        for channel_role in FEEDER_DETECTION_ROLES
    }
    if role is not None:
        algorithm_by_role[role] = algorithm
    else:
        for channel_role in FEEDER_DETECTION_ROLES:
            algorithm_by_role[channel_role] = algorithm
    if isinstance(payload.sample_collection_enabled, bool):
        if role is not None:
            sample_collection_enabled_by_role[role] = bool(payload.sample_collection_enabled)
        else:
            for channel_role in FEEDER_DETECTION_ROLES:
                sample_collection_enabled_by_role[channel_role] = bool(payload.sample_collection_enabled)
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setFeederDetectionAlgorithm"):
        try:
            if role is not None:
                shared_state.vision_manager.setFeederDetectionAlgorithm(algorithm, role)
            else:
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
                    for channel_role in FEEDER_DETECTION_ROLES:
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
            "algorithm": (
                algorithm
                if role is None
                else _normalize_feeder_detection_algorithm(
                    saved.get("algorithm") if isinstance(saved, dict) else None
                )
            ),
            "algorithm_by_role": algorithm_by_role,
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
        "algorithm_by_role": algorithm_by_role,
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
            payload["saved_to_library"] = True
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
            payload["saved_to_library"] = True
        except Exception as exc:
            payload["saved_to_library"] = False
            payload["saved_sample_error"] = str(exc)
    else:
        payload["saved_to_library"] = False
    payload["ok"] = True
    return payload


@router.post("/api/feeder/detect/{role}")
def debug_feeder_detection(role: str) -> Dict[str, Any]:
    role = _normalize_feeder_role(role)
    if role is None:
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


def _decode_jpeg_b64(b64: str):
    import base64 as _b
    import numpy as _np
    import cv2 as _cv2

    try:
        raw = _b.b64decode(b64)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid base64")
    arr = _np.frombuffer(raw, dtype=_np.uint8)
    img = _cv2.imdecode(arr, _cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="could not decode image")
    return img


@router.post("/api/feeder/tracking/recognize")
def feeder_tracking_recognize(body: Dict[str, Any]) -> Dict[str, Any]:
    """Send one or more tracked-piece crops to the Brickognize classifier
    synchronously. Pass ``jpeg_b64`` for a single image or ``jpegs_b64``
    for a multi-image query — Brickognize uses all views as evidence for
    a single final prediction, which is much more robust on a tracked
    piece where we have 5–12 angles of the same part.
    """
    from classification.brickognize import (
        _classifyImages,
        _pickBestColor,
        _pickBestItem,
    )

    single = body.get("jpeg_b64")
    multi = body.get("jpegs_b64")
    images = []
    if isinstance(multi, list) and multi:
        images = [_decode_jpeg_b64(b) for b in multi if isinstance(b, str) and b]
    elif isinstance(single, str) and single:
        images = [_decode_jpeg_b64(single)]
    if not images:
        raise HTTPException(
            status_code=400, detail="jpeg_b64 or jpegs_b64 required"
        )
    try:
        result = _classifyImages(images)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"brickognize failed: {exc}")
    best_item, best_view = _pickBestItem(result, None)
    best_color = _pickBestColor(result, None)
    return {
        "image_count": len(images),
        "best_item": best_item,
        "best_view": best_view,
        "best_color": best_color,
        "items": result.get("items", []),
    }


@router.delete("/api/feeder/tracking/history")
def feeder_tracking_history_clear() -> Dict[str, Any]:
    """Tabula-rasa — wipe all persisted + in-memory tracked pieces.

    Drops every completed track, deletes the JSON files under
    ``blob/tracked_history/``, and clears the in-process ring buffer.
    Live tracks that are still being tracked are untouched — they'll be
    archived next time they die.
    """
    vm = shared_state.vision_manager
    if vm is None or not hasattr(vm, "_piece_history"):
        raise HTTPException(status_code=503, detail="Tracker history not available.")
    try:
        vm._piece_history.reset()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to clear history: {exc}")
    return {"ok": True}


@router.get("/api/feeder/tracking/history")
def feeder_tracking_history(limit: int = 30, min_sectors: int = 3) -> Dict[str, Any]:
    """Ring buffer of recent completed tracks (summary only — no big JPEGs).

    ``min_sectors`` hides finished tracks that didn't cover at least that
    many angular channel sectors — useful for filtering out noise/short
    flickers. Live tracks are always shown regardless.
    """
    vm = shared_state.vision_manager
    if vm is None or not hasattr(vm, "listFeederTrackHistory"):
        raise HTTPException(status_code=503, detail="Tracker history not available.")
    limit = max(1, min(int(limit), 200))
    min_sectors = max(0, min(int(min_sectors), 12))
    return {"items": vm.listFeederTrackHistory(limit=limit, min_sectors=min_sectors)}


@router.get("/api/feeder/tracking/history/{global_id}")
def feeder_tracking_history_detail(global_id: int) -> Dict[str, Any]:
    vm = shared_state.vision_manager
    if vm is None or not hasattr(vm, "getFeederTrackHistoryDetail"):
        raise HTTPException(status_code=503, detail="Tracker history not available.")
    entry = vm.getFeederTrackHistoryDetail(int(global_id))
    if entry is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    return entry


@router.get("/api/feeder/tracking/pending")
def feeder_tracking_pending() -> Dict[str, Any]:
    """Debug: show pending cross-camera handoff entries + current zone config."""
    vm = shared_state.vision_manager
    if vm is None or not hasattr(vm, "_piece_handoff_manager"):
        raise HTTPException(status_code=503, detail="Handoff manager not available.")
    manager = vm._piece_handoff_manager
    return {
        "pending": manager.pending_snapshot(),
        "entry_zones": {role: poly for role, poly in manager._entry_zones.items()},
        "exit_zones": {role: poly for role, poly in manager._exit_zones.items()},
        "handoff_window_s": manager.handoff_window_s,
    }


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


# ---------------------------------------------------------------------------
# Sample storage management
# ---------------------------------------------------------------------------

TRAINING_ROOT = BLOB_DIR / "classification_training"


def _session_stats(session_dir: Path) -> Dict[str, Any]:
    """Compute sample count and disk size for a single session directory."""
    metadata_dir = session_dir / "metadata"
    sample_count = sum(1 for f in metadata_dir.glob("*.json")) if metadata_dir.is_dir() else 0
    total_bytes = 0
    for f in session_dir.rglob("*"):
        if f.is_file():
            total_bytes += f.stat().st_size
    manifest_path = session_dir / "manifest.json"
    session_name = None
    created_at = None
    if manifest_path.is_file():
        try:
            import json as _json
            manifest = _json.loads(manifest_path.read_text())
            session_name = manifest.get("session_name")
            created_at = manifest.get("created_at")
        except Exception:
            pass
    return {
        "session_id": session_dir.name,
        "session_name": session_name,
        "created_at": created_at,
        "sample_count": sample_count,
        "size_bytes": total_bytes,
    }


@router.get("/api/samples/storage")
def get_sample_storage() -> Dict[str, Any]:
    """List all local sample sessions with stats."""
    sessions: List[Dict[str, Any]] = []
    if TRAINING_ROOT.is_dir():
        for child in sorted(TRAINING_ROOT.iterdir()):
            if child.is_dir():
                sessions.append(_session_stats(child))
    total_samples = sum(s["sample_count"] for s in sessions)
    total_bytes = sum(s["size_bytes"] for s in sessions)
    return {
        "sessions": sessions,
        "total_samples": total_samples,
        "total_bytes": total_bytes,
    }


@router.delete("/api/samples/storage/{session_id}")
def delete_sample_session(session_id: str) -> Dict[str, Any]:
    """Delete a single sample session."""
    session_dir = TRAINING_ROOT / session_id
    if not session_dir.is_dir() or not session_dir.resolve().is_relative_to(TRAINING_ROOT.resolve()):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    sample_count = sum(1 for f in (session_dir / "metadata").glob("*.json")) if (session_dir / "metadata").is_dir() else 0
    shutil.rmtree(session_dir)
    return {"ok": True, "message": f"Deleted session '{session_id}' ({sample_count} samples)."}


@router.delete("/api/samples/storage")
def purge_all_samples() -> Dict[str, Any]:
    """Delete all sample sessions."""
    deleted = 0
    total_samples = 0
    if TRAINING_ROOT.is_dir():
        for child in sorted(TRAINING_ROOT.iterdir()):
            if child.is_dir():
                metadata_dir = child / "metadata"
                total_samples += sum(1 for f in metadata_dir.glob("*.json")) if metadata_dir.is_dir() else 0
                shutil.rmtree(child)
                deleted += 1
    return {"ok": True, "message": f"Purged {deleted} sessions ({total_samples} samples)."}
