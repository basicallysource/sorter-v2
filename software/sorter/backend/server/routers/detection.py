"""Detection configuration, API keys, and detection test/debug endpoints."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from blob_manager import (
    BLOB_DIR,
    getApiKeys,
    getClassificationDetectionConfig,
    getHiveConfig,
    setApiKeys,
    setHiveConfig,
)
from role_aliases import (
    CLASSIFICATION_CHANNEL_ROLE,
)
from server import shared_state
from server.classification_training import getClassificationTrainingManager
from server.detection_config.common import (
    feeder_role_label as _feeder_role_label,
    public_aux_scope as _public_aux_scope,
    public_feeder_roles as _public_feeder_roles,
)
from rt.contracts.registry import DETECTORS
from rt.perception.detector_metadata import (
    detection_algorithm_definition,
    normalize_detection_algorithm,
)
from server.services.detection_config import (
    AuxiliaryDetectionSaveRequest,
    ClassificationDetectionSaveRequest,
    DetectionConfigApplyError,
    DetectionConfigService,
    DetectionConfigValidationError,
    FeederDetectionSaveRequest,
)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_API_KEY_PROVIDERS = ("openrouter",)

# ---------------------------------------------------------------------------
# Detection algorithm helper functions
# ---------------------------------------------------------------------------


def _normalize_feeder_role(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    if candidate in {CLASSIFICATION_CHANNEL_ROLE, "carousel"}:
        candidate = CLASSIFICATION_CHANNEL_ROLE
    if candidate not in _public_feeder_roles() and candidate != CLASSIFICATION_CHANNEL_ROLE:
        raise HTTPException(status_code=400, detail="Unsupported feeder role.")
    return candidate


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
    return DetectionConfigService(
        rt_handle=shared_state.rt_handle,
    ).get_classification_detection_config()


@router.post("/api/classification/detection-config")
def save_classification_detection_config(
    payload: ClassificationDetectionConfigPayload,
) -> Dict[str, Any]:
    service = DetectionConfigService(
        rt_handle=shared_state.rt_handle,
    )
    try:
        return service.save_classification_detection_config(
            ClassificationDetectionSaveRequest(
                algorithm=payload.algorithm,
                openrouter_model=payload.openrouter_model,
            )
        )
    except DetectionConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DetectionConfigApplyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Feeder detection config
# ---------------------------------------------------------------------------


@router.get("/api/feeder/detection-config")
def get_feeder_detection_config(role: str | None = Query(default=None)) -> Dict[str, Any]:
    role = _normalize_feeder_role(role)
    return DetectionConfigService(
        rt_handle=shared_state.rt_handle,
    ).get_feeder_detection_config(role)


@router.post("/api/feeder/detection-config")
def save_feeder_detection_config(
    payload: AuxiliaryDetectionConfigPayload,
    role: str | None = Query(default=None),
) -> Dict[str, Any]:
    role = _normalize_feeder_role(role)
    service = DetectionConfigService(
        rt_handle=shared_state.rt_handle,
    )
    try:
        return service.save_feeder_detection_config(
            FeederDetectionSaveRequest(
                role=role,
                algorithm=payload.algorithm,
                openrouter_model=payload.openrouter_model,
                sample_collection_enabled=payload.sample_collection_enabled,
            )
        )
    except DetectionConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DetectionConfigApplyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Classification C-channel (C4) detection config
# ---------------------------------------------------------------------------


@router.get("/api/carousel/detection-config")
@router.get("/api/classification-channel/detection-config")
def get_carousel_detection_config() -> Dict[str, Any]:
    return DetectionConfigService(
        rt_handle=shared_state.rt_handle,
    ).get_auxiliary_detection_config()


@router.post("/api/carousel/detection-config")
@router.post("/api/classification-channel/detection-config")
def save_carousel_detection_config(
    payload: AuxiliaryDetectionConfigPayload,
) -> Dict[str, Any]:
    aux_scope = _public_aux_scope()
    service = DetectionConfigService(
        rt_handle=shared_state.rt_handle,
    )
    try:
        return service.save_auxiliary_detection_config(
            AuxiliaryDetectionSaveRequest(
                algorithm=payload.algorithm,
                openrouter_model=payload.openrouter_model,
                sample_collection_enabled=payload.sample_collection_enabled,
            ),
            aux_scope=aux_scope,
        )
    except DetectionConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DetectionConfigApplyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# rt-runtime detection helpers
# ---------------------------------------------------------------------------
#
# The Hive detectors in rt/ are baseline-free YOLO/NanoDet feature extractors,
# so there is no legacy MOG2/heatmap-diff style baseline capture to port. The
# baseline-capture endpoints below return HTTP 501 with a clean message; the
# detect/current endpoints run the configured rt Hive detector on the latest
# frame and return the Svelte settings dropdown payload shape.


def _baseline_not_supported_response(scope_label: str) -> HTTPException:
    return HTTPException(
        status_code=501,
        detail=(
            f"{scope_label} baseline capture is not available in the new runtime — "
            "the Hive detectors are baseline-free."
        ),
    )


def _find_rt_perception_runner(feed_id: str):
    """Return the rt PerceptionRunner for ``feed_id`` or ``None``.

    Prefers the handle's ``runner_for_feed`` accessor (added with the
    boot-race fix) so any rebuilt runner is picked up automatically;
    falls back to linear scan for older handle shapes.
    """
    handle = shared_state.rt_handle
    if handle is None:
        return None
    accessor = getattr(handle, "runner_for_feed", None)
    if callable(accessor):
        runner = accessor(feed_id)
        if runner is not None:
            return runner
    for runner in getattr(handle, "perception_runners", []) or []:
        pipeline = getattr(runner, "_pipeline", None)
        if pipeline is None:
            continue
        feed = getattr(pipeline, "feed", None)
        if feed is not None and getattr(feed, "feed_id", None) == feed_id:
            return runner
    return None


def _zone_bbox_and_points(zone: Any, frame_shape: tuple[int, int]) -> tuple[
    list[int] | None, int, list[list[int]] | None
]:
    """Compute (zone_bbox_xyxy, point_count, polygon_points) for payload."""
    from rt.contracts.feed import PolygonZone, RectZone

    if zone is None:
        return None, 0, None
    h, w = int(frame_shape[0]), int(frame_shape[1])
    if isinstance(zone, RectZone):
        x1 = max(0, int(zone.x))
        y1 = max(0, int(zone.y))
        x2 = min(w, int(zone.x + zone.w))
        y2 = min(h, int(zone.y + zone.h))
        return [x1, y1, x2, y2], 4, [
            [x1, y1], [x2, y1], [x2, y2], [x1, y2],
        ]
    if isinstance(zone, PolygonZone):
        xs = [int(p[0]) for p in zone.vertices]
        ys = [int(p[1]) for p in zone.vertices]
        if not xs or not ys:
            return None, 0, None
        x1 = max(0, min(xs))
        y1 = max(0, min(ys))
        x2 = min(w, max(xs))
        y2 = min(h, max(ys))
        points = [[int(p[0]), int(p[1])] for p in zone.vertices]
        return [x1, y1, x2, y2], len(points), points
    return None, 0, None


def _empty_detect_payload(
    *,
    algorithm: str,
    message: str,
    frame_resolution: list[int] | None = None,
    zone_bbox: list[int] | None = None,
    zone_point_count: int = 0,
) -> Dict[str, Any]:
    return {
        "algorithm": algorithm,
        "found": False,
        "bbox": None,
        "candidate_bboxes": [],
        "candidate_previews": [],
        "bbox_count": 0,
        "score": None,
        "zone_bbox": zone_bbox,
        "frame_resolution": frame_resolution,
        "zone_point_count": zone_point_count,
        "message": message,
        "_sample_capture": None,
    }


def _candidate_preview_b64(
    raw: Any,
    bbox: list[int] | tuple[int, int, int, int] | None,
    *,
    max_side_px: int = 160,
    jpeg_quality: int = 82,
) -> str | None:
    if raw is None or bbox is None or not hasattr(raw, "shape"):
        return None
    try:
        frame_h, frame_w = int(raw.shape[0]), int(raw.shape[1])
        x1, y1, x2, y2 = (int(v) for v in bbox)
        x1 = max(0, min(frame_w - 1, x1))
        x2 = max(0, min(frame_w, x2))
        y1 = max(0, min(frame_h - 1, y1))
        y2 = max(0, min(frame_h, y2))
        if x2 <= x1 or y2 <= y1:
            return None
        crop = raw[y1:y2, x1:x2]
        if crop is None or getattr(crop, "size", 0) <= 0:
            return None
        crop_h, crop_w = int(crop.shape[0]), int(crop.shape[1])
        longest = max(crop_h, crop_w)

        import base64
        import cv2

        if longest > max_side_px:
            scale = float(max_side_px) / float(longest)
            resized_w = max(1, int(round(crop_w * scale)))
            resized_h = max(1, int(round(crop_h * scale)))
            crop = cv2.resize(crop, (resized_w, resized_h), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(
            ".jpg",
            crop,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)],
        )
        if not ok:
            return None
        return base64.b64encode(encoded.tobytes()).decode("ascii")
    except Exception:
        return None


def _candidate_previews_b64(
    raw: Any,
    candidate_bboxes: list[list[int] | tuple[int, int, int, int]] | None,
) -> list[str | None]:
    if raw is None or not isinstance(candidate_bboxes, list):
        return []
    return [
        _candidate_preview_b64(raw, candidate)
        for candidate in candidate_bboxes[:6]
    ]


def _detect_from_rt_pipeline(
    *,
    scope: str,
    feed_id: str,
    scope_label: str,
) -> Dict[str, Any]:
    """Run the pipeline's configured detector once on the latest feed frame.

    Returns a payload matching the legacy ``debug*Detection`` contract:
    ``algorithm``, ``found``, ``bbox``, ``candidate_bboxes``, ``bbox_count``,
    ``score``, ``message``, ``zone_bbox``, ``frame_resolution``,
    ``zone_point_count``, plus the ``_sample_capture`` bridge dict expected by
    ``_finalize_aux_detection_debug_payload``.
    """
    runner = _find_rt_perception_runner(feed_id)
    if runner is None:
        return _empty_detect_payload(
            algorithm=normalize_detection_algorithm(scope, None),
            message=f"rt perception runner for {scope_label} is not available.",
        )

    pipeline = runner._pipeline  # type: ignore[attr-defined]
    feed = pipeline.feed
    zone = pipeline.zone
    detector = pipeline.detector
    slug = getattr(detector, "key", normalize_detection_algorithm(scope, None))

    frame = feed.latest()
    if frame is None or getattr(frame, "raw", None) is None:
        return _empty_detect_payload(
            algorithm=slug,
            message=f"No frame available on the {scope_label} camera.",
        )

    raw = frame.raw
    frame_h, frame_w = int(raw.shape[0]), int(raw.shape[1])
    zone_bbox, point_count, _polygon_points = _zone_bbox_and_points(
        zone, (frame_h, frame_w)
    )

    try:
        batch = detector.detect(frame, zone)
    except Exception as exc:
        return _empty_detect_payload(
            algorithm=slug,
            message=f"Detector raised: {exc}",
            frame_resolution=[frame_w, frame_h],
            zone_bbox=zone_bbox,
            zone_point_count=point_count,
        )

    detections = list(batch.detections)
    candidate_bboxes = [list(det.bbox_xyxy) for det in detections]
    candidate_previews = _candidate_previews_b64(raw, candidate_bboxes)
    best = max(detections, key=lambda det: float(det.score)) if detections else None
    bbox = list(best.bbox_xyxy) if best is not None else None
    score = float(best.score) if best is not None else None
    definition = detection_algorithm_definition(slug)
    label = definition.label if definition is not None else slug
    message = (
        f"{label}: {len(detections)} candidate(s) on the {scope_label} frame."
        if detections
        else f"{label}: no object detected on the {scope_label} frame."
    )

    sample_capture = {
        "input_image": raw,
        "frame": raw,
    }

    return {
        "algorithm": slug,
        "found": bool(detections),
        "bbox": bbox,
        "candidate_bboxes": candidate_bboxes,
        "candidate_previews": candidate_previews,
        "bbox_count": len(candidate_bboxes),
        "score": score,
        "zone_bbox": zone_bbox,
        "frame_resolution": [frame_w, frame_h],
        "zone_point_count": point_count,
        "message": message,
        "_sample_capture": sample_capture,
    }


def _detect_from_standalone_camera(
    *,
    scope: str,
    camera_role: str,
    scope_label: str,
    slug: str,
) -> Dict[str, Any]:
    """Grab a frame directly from camera_service (no rt pipeline wired).

    Used for classification chamber top/bottom cameras where the rt bootstrap
    doesn't build a perception pipeline. Builds a detector ad-hoc, runs one
    inference on a full-frame RectZone, and returns the same payload shape.
    """
    from rt.contracts.feed import FeedFrame, RectZone

    service = shared_state.camera_service
    if service is None:
        return _empty_detect_payload(
            algorithm=slug,
            message="Camera service not initialised.",
        )
    feed = service.get_feed(camera_role)
    if feed is None:
        return _empty_detect_payload(
            algorithm=slug,
            message=f"No camera assigned to {scope_label}.",
        )

    cframe = None
    get_frame = getattr(feed, "get_frame", None)
    if callable(get_frame):
        try:
            cframe = get_frame(annotated=False)
        except TypeError:
            cframe = get_frame()
    raw = getattr(cframe, "raw", None) if cframe is not None else None
    if raw is None:
        return _empty_detect_payload(
            algorithm=slug,
            message=f"No frame available on the {scope_label} camera.",
        )

    h, w = int(raw.shape[0]), int(raw.shape[1])
    zone = RectZone(x=0, y=0, w=w, h=h)
    frame_seq = int(getattr(cframe, "frame_seq", 0) or 0)
    timestamp = float(getattr(cframe, "timestamp", 0.0) or 0.0)
    monotonic_ts = float(getattr(cframe, "monotonic_ts", 0.0) or 0.0)
    frame = FeedFrame(
        feed_id=f"{camera_role}_adhoc",
        camera_id=camera_role,
        raw=raw,
        gray=None,
        timestamp=timestamp,
        monotonic_ts=monotonic_ts or time.monotonic(),
        frame_seq=frame_seq,
    )

    try:
        detector = DETECTORS.create(slug)
    except LookupError:
        return _empty_detect_payload(
            algorithm=slug,
            message=f"Detector '{slug}' is not registered.",
            frame_resolution=[w, h],
            zone_bbox=[0, 0, w, h],
            zone_point_count=4,
        )
    except Exception as exc:
        return _empty_detect_payload(
            algorithm=slug,
            message=f"Detector '{slug}' failed to load: {exc}",
            frame_resolution=[w, h],
            zone_bbox=[0, 0, w, h],
            zone_point_count=4,
        )

    try:
        batch = detector.detect(frame, zone)
    except Exception as exc:
        try:
            detector.stop()
        except Exception:
            pass
        return _empty_detect_payload(
            algorithm=slug,
            message=f"Detector raised: {exc}",
            frame_resolution=[w, h],
            zone_bbox=[0, 0, w, h],
            zone_point_count=4,
        )
    try:
        detector.stop()
    except Exception:
        pass

    detections = list(batch.detections)
    candidate_bboxes = [list(det.bbox_xyxy) for det in detections]
    candidate_previews = _candidate_previews_b64(raw, candidate_bboxes)
    best = max(detections, key=lambda det: float(det.score)) if detections else None
    bbox = list(best.bbox_xyxy) if best is not None else None
    score = float(best.score) if best is not None else None
    definition = detection_algorithm_definition(slug)
    label = definition.label if definition is not None else slug
    message = (
        f"{label}: {len(detections)} candidate(s) on the {scope_label} frame."
        if detections
        else f"{label}: no object detected on the {scope_label} frame."
    )
    sample_capture = {
        "input_image": raw,
        "frame": raw,
        "top_frame": raw if camera_role == "classification_top" else None,
        "bottom_frame": raw if camera_role == "classification_bottom" else None,
        "top_zone": zone if camera_role == "classification_top" else None,
        "bottom_zone": zone if camera_role == "classification_bottom" else None,
    }
    return {
        "algorithm": slug,
        "found": bool(detections),
        "bbox": bbox,
        "candidate_bboxes": candidate_bboxes,
        "candidate_previews": candidate_previews,
        "bbox_count": len(candidate_bboxes),
        "score": score,
        "zone_bbox": [0, 0, w, h],
        "frame_resolution": [w, h],
        "zone_point_count": 4,
        "message": message,
        "_sample_capture": sample_capture,
    }


# ---------------------------------------------------------------------------
# Classification C-channel (C4) baseline capture — rt detectors are baseline-free
# ---------------------------------------------------------------------------


@router.post("/api/carousel/detection/baseline/capture")
@router.post("/api/classification-channel/detection/baseline/capture")
def capture_carousel_detection_baseline() -> Dict[str, Any]:
    scope_label = (
        "Classification C-channel (C4)"
        if _public_aux_scope() == CLASSIFICATION_CHANNEL_ROLE
        else "Carousel"
    )
    raise _baseline_not_supported_response(scope_label)


# ---------------------------------------------------------------------------
# Detection debug/test endpoints
# ---------------------------------------------------------------------------


@router.post("/api/classification/detect/{camera}")
def debug_classification_detection(camera: str) -> Dict[str, Any]:
    if camera not in {"top", "bottom"}:
        raise HTTPException(status_code=400, detail="Unsupported classification camera.")

    camera_role = "classification_top" if camera == "top" else "classification_bottom"
    saved = getClassificationDetectionConfig()
    slug = normalize_detection_algorithm(
        "classification",
        saved.get("algorithm") if isinstance(saved, dict) else None,
    )
    scope_label = f"classification {camera}"
    payload = _detect_from_standalone_camera(
        scope="classification",
        camera_role=camera_role,
        scope_label=scope_label,
        slug=slug,
    )

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
        try:
            getClassificationTrainingManager().saveDetectionDebugCapture(
                camera=camera,
                algorithm=str(payload.get("algorithm") or ""),
                openrouter_model=None,
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
    if isinstance(sample_capture, dict):
        try:
            getClassificationTrainingManager().saveAuxiliaryDetectionCapture(
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

    # UI role -> rt feed_id (c_channel_2 → c2_feed, c_channel_3 → c3_feed,
    # classification_channel → c4_feed).
    feed_id = {
        "c_channel_2": "c2_feed",
        "c_channel_3": "c3_feed",
        CLASSIFICATION_CHANNEL_ROLE: "c4_feed",
    }.get(role)
    if feed_id is None:
        raise HTTPException(status_code=400, detail="Unsupported feeder role.")

    scope_label = _feeder_role_label(role)
    payload = _detect_from_rt_pipeline(
        scope="feeder",
        feed_id=feed_id,
        scope_label=scope_label,
    )
    sample_capture = payload.pop("_sample_capture", None) if isinstance(payload, dict) else None
    if isinstance(payload, dict):
        payload["camera"] = role
    return _finalize_aux_detection_debug_payload(
        role=role,
        payload=payload,
        sample_capture=sample_capture,
        openrouter_model=None,
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


@router.post("/api/carousel/detect/current")
@router.post("/api/classification-channel/detect/current")
def debug_carousel_detection() -> Dict[str, Any]:
    aux_scope = _public_aux_scope()  # "carousel" or "classification_channel"
    scope_label = (
        "Classification C-channel (C4)"
        if aux_scope == CLASSIFICATION_CHANNEL_ROLE
        else "carousel"
    )
    algorithm_scope = "classification_channel" if aux_scope == CLASSIFICATION_CHANNEL_ROLE else "carousel"
    payload = _detect_from_rt_pipeline(
        scope=algorithm_scope,
        feed_id="c4_feed",
        scope_label=scope_label,
    )
    sample_capture = payload.pop("_sample_capture", None) if isinstance(payload, dict) else None
    return _finalize_aux_detection_debug_payload(
        role="carousel",
        payload=payload,
        sample_capture=sample_capture,
        openrouter_model=None,
    )


# ---------------------------------------------------------------------------
# Classification baseline capture — rt detectors are baseline-free
# ---------------------------------------------------------------------------


@router.post("/api/classification/baseline/capture")
def capture_classification_baseline() -> Dict[str, Any]:
    raise _baseline_not_supported_response("Classification chamber")


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
