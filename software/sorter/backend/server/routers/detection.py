"""Detection configuration, API keys, and detection test/debug endpoints."""

from __future__ import annotations

import os
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
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
from perception.overlay import drawChannelZones
from server import shared_state
from server.classification_training import getClassificationTrainingManager
from vision.detection_registry import (
    detection_algorithm_definition,
    detection_algorithm_options,
    normalize_detection_algorithm,
    scope_supports_detection_algorithm,
)

router = APIRouter()


def _draw_perception_debug(
    info: Dict[str, Any],
    channel: Any,
    *,
    frame: Any,
    raw_bboxes: list,
    on_bboxes: list,
    panel_lines: List[str],
):
    """Shared renderer for the perception-debug overlays. Draws the crop rect
    (white), mask (cyan), rejected raw detections (orange), kept detections
    (green), arc center (magenta), and a translucent spec panel, then returns
    JPEG bytes (4K downscaled for transfer). ``frame`` is the PerceptionFrame to
    draw on (the cropped or the full-frame one); ``raw_bboxes`` is every model
    detection for the mode; ``on_bboxes`` the subset drawn green."""
    img = frame.bgr.copy()
    h, w = img.shape[:2]
    s = max(1.0, w / 1280.0)  # scale strokes/text so it reads on 720p and 4K
    thick = max(2, int(round(2 * s)))

    crop = info.get("crop_rect")
    if crop is not None:
        cv2.rectangle(
            img, (int(crop[0]), int(crop[1])), (int(crop[2]), int(crop[3])),
            (255, 255, 255), max(1, thick - 1),
        )

    drawChannelZones(img, channel, thick)

    on_set = {tuple(int(v) for v in b) for b in on_bboxes}
    for b in raw_bboxes:  # rejected raw → orange (drawn first)
        bb = tuple(int(v) for v in b)
        if bb in on_set:
            continue
        x1, y1, x2, y2 = bb
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 165, 255), thick)
        cv2.circle(img, ((x1 + x2) // 2, (y1 + y2) // 2), max(4, int(5 * s)), (0, 165, 255), -1)

    for b in on_bboxes:  # kept → green
        x1, y1, x2, y2 = (int(b[0]), int(b[1]), int(b[2]), int(b[3]))
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 255, 0), thick)
        cv2.circle(img, ((x1 + x2) // 2, (y1 + y2) // 2), max(4, int(5 * s)), (0, 255, 0), -1)

    if info.get("center") is not None:
        cx0, cy0 = info["center"]
        cv2.circle(img, (int(cx0), int(cy0)), max(6, int(10 * s)), (255, 0, 255), -1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    fs = 0.5 * s
    ft = max(1, int(round(s)))
    (_, line_h), base = cv2.getTextSize("Ag", font, fs, ft)
    row = line_h + base + int(6 * s)
    pad = int(10 * s)
    panel_w = min(w, max((cv2.getTextSize(ln, font, fs, ft)[0][0] for ln in panel_lines), default=0) + 2 * pad)
    panel_h = row * len(panel_lines) + pad
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (panel_w, panel_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, img, 0.45, 0, img)
    y = pad + line_h
    for ln in panel_lines:
        cv2.putText(img, ln, (pad, y), font, fs, (0, 255, 255), ft, cv2.LINE_AA)
        y += row

    max_w = 1600
    if w > max_w:
        scale = max_w / float(w)
        img = cv2.resize(img, (max_w, int(round(h * scale))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise HTTPException(status_code=500, detail="encode failed")
    import io
    return StreamingResponse(io.BytesIO(buf.tobytes()), media_type="image/jpeg")


def _model_spec_lines(info: Dict[str, Any], frame: Any) -> List[str]:
    """Camera + exact-model lines shared by both debug overlays."""
    w_h = frame.bgr.shape[1], frame.bgr.shape[0]
    crop = info.get("crop_rect")
    conf = info.get("conf_threshold")
    return [
        f"ch {info['channel_id']}  role={info['camera_source_id']}"
        + (f"  cam_src={info['camera_source']}" if info.get("camera_source") is not None else ""),
        f"frame {w_h[0]}x{w_h[1]}   crop "
        + (f"{int(crop[2]) - int(crop[0])}x{int(crop[3]) - int(crop[1])}" if crop is not None else "full"),
        f"algo: {info.get('algorithm_id')}",
        f"model: {info.get('model_name')}",
        (f"imgsz={info.get('imgsz')}  conf={conf:.2f}" if isinstance(conf, (int, float))
         else f"imgsz={info.get('imgsz')}  conf={conf}"),
    ]


def _perception_debug_info(channel_id: int) -> Dict[str, Any]:
    gc = shared_state.gc_ref
    ps = getattr(gc, "perception_service", None) if gc is not None else None
    if ps is None:
        raise HTTPException(status_code=503, detail="perception_service not available")
    if channel_id not in ps.channels():
        raise HTTPException(status_code=404, detail=f"channel {channel_id} not wired")
    info = ps.channel_debug_info(channel_id)
    if info is None:
        raise HTTPException(status_code=409, detail="no inference cycle yet")
    info["_ps"] = ps
    return info


@router.get("/api/perception/debug/status/{channel_id}")
def perception_debug_status(channel_id: int) -> Dict[str, Any]:
    """Pixel-free perception debug status for one channel.

    This mirrors the annotated debug image's metadata and exposes the crop
    plan that a future hardware RGA detection branch should consume.
    """
    info = _perception_debug_info(channel_id)
    frame = info.get("frame")
    frame_shape = getattr(getattr(frame, "bgr", None), "shape", None)
    frame_summary = None
    if frame_shape is not None and len(frame_shape) >= 2:
        frame_summary = {
            "width": int(frame_shape[1]),
            "height": int(frame_shape[0]),
            "timestamp": float(getattr(frame, "timestamp", 0.0) or 0.0),
        }
    full = info.get("full_frame") if isinstance(info.get("full_frame"), dict) else None
    full_summary = None
    if full is not None:
        full_frame = full.get("frame")
        full_shape = getattr(getattr(full_frame, "bgr", None), "shape", None)
        full_summary = {
            "bboxes": full.get("bboxes") or [],
            "infer_ms": full.get("infer_ms"),
            "frame_ts": full.get("frame_ts"),
            "frame": {
                "width": int(full_shape[1]),
                "height": int(full_shape[0]),
            }
            if full_shape is not None and len(full_shape) >= 2
            else None,
        }
    return {
        "ok": True,
        "channel_id": info.get("channel_id"),
        "camera_source_id": info.get("camera_source_id"),
        "camera_source": info.get("camera_source"),
        "algorithm_id": info.get("algorithm_id"),
        "model_name": info.get("model_name"),
        "imgsz": info.get("imgsz"),
        "conf_threshold": info.get("conf_threshold"),
        "core_mask_name": info.get("core_mask_name"),
        "raw_bboxes": info.get("raw_bboxes") or [],
        "on_channel_bboxes": info.get("on_channel_bboxes") or [],
        "crop_rect": info.get("crop_rect"),
        "crop_plan": info.get("crop_plan"),
        "infer_ms": info.get("infer_ms"),
        "frame": frame_summary,
        "full_frame": full_summary,
        "center": info.get("center"),
        "mask_shape": info.get("mask_shape"),
        "n_drop_sections": info.get("n_drop_sections"),
        "n_exit_sections": info.get("n_exit_sections"),
        "n_precise_sections": info.get("n_precise_sections"),
    }


@router.get("/api/perception/debug/annotated/{channel_id}")
def perception_debug_annotated(channel_id: int):
    """The PRODUCTION view: exactly what perception infers and decides on.

    - GREEN  = detections the on-channel mask filter KEPT (drive the machine).
    - ORANGE = RAW model detections the filter REJECTED (model junk vs. filter
      too aggressive is now obvious).
    - WHITE  = the crop region the model actually saw (polygon bounding rect).
    - CYAN   = the polygon mask; MAGENTA = arc center.

    Spec panel stamps the camera, resolution, exact model, and counts. Read-only
    — reuses cached state, runs no new inference."""
    info = _perception_debug_info(channel_id)
    channel = info["_ps"].channels().get(channel_id)
    frame = info["frame"]
    infer_ms = info.get("infer_ms")
    n_raw = len(info["raw_bboxes"])
    n_kept = len(info["on_channel_bboxes"])
    state = info["_ps"].read_state(channel_id)
    lines = _model_spec_lines(info, frame) + [
        f"core={info.get('core_mask_name')}  infer="
        + (f"{infer_ms:.0f}ms" if isinstance(infer_ms, (int, float)) else "?"),
        f"CROPPED (production): raw={n_raw} kept(green)={n_kept} rejected(orange)={n_raw - n_kept}",
        f"state: pieces={state.n_pieces} in_drop={state.in_drop} in_exit={state.in_exit} in_precise={state.in_precise}",
        f"sections drop={info['n_drop_sections']} exit={info['n_exit_sections']} precise={info['n_precise_sections']}",
    ]
    return _draw_perception_debug(
        info, channel, frame=frame,
        raw_bboxes=info["raw_bboxes"],
        on_bboxes=info["on_channel_bboxes"],
        panel_lines=lines,
    )


@router.get("/api/perception/debug/fullframe/{channel_id}")
def perception_debug_fullframe(channel_id: int):
    """The COMPARISON view: what the same model produces on the WHOLE frame, no
    polygon crop — to tell "the crop rect is excluding pieces" from "the model
    just isn't detecting them."

    Runs a SECOND inference per cycle on the worker thread, enabled on demand and
    self-expiring ~10 s after the page stops polling (no steady-state cost). The
    first request after idle returns 425 while the worker produces the first
    full-frame result; the page's auto-refresh picks it up a beat later. Once a
    result exists it is persisted, so the view does not flap back to 425.

    GREEN = full-frame detections whose center lands in the channel mask;
    ORANGE = full-frame detections outside it. WHITE crop rect is drawn for
    reference (it is NOT applied here)."""
    import time as _time

    info = _perception_debug_info(channel_id)
    ps = info["_ps"]
    ps.request_full_frame_debug(channel_id, ttl_s=10.0)
    full = info.get("full_frame")
    if not full or full.get("frame") is None:
        raise HTTPException(
            status_code=425,
            detail="full-frame inference warming up; refresh in a moment",
        )
    frame = full["frame"]
    ff = full.get("bboxes") or []
    channel = ps.channels().get(channel_id)
    from perception.arcs import bboxInsideChannelMask
    on_ff = [b for b in ff if channel is not None and bboxInsideChannelMask(b, channel)]
    ff_ms = full.get("infer_ms")
    age_s = max(0.0, _time.time() - float(full.get("frame_ts") or 0.0))
    n_crop_raw = len(info["raw_bboxes"])
    state = ps.read_state(channel_id)
    lines = _model_spec_lines(info, frame) + [
        f"core={info.get('core_mask_name')}  full-frame infer="
        + (f"{ff_ms:.0f}ms" if isinstance(ff_ms, (int, float)) else "?")
        + (f"  (age {age_s:.1f}s)" if age_s > 1.0 else ""),
        f"FULL-FRAME (no crop): raw={len(ff)} in-mask(green)={len(on_ff)} outside(orange)={len(ff) - len(on_ff)}",
        f"vs CROPPED production raw={n_crop_raw} kept={len(info['on_channel_bboxes'])}",
        f"state: pieces={state.n_pieces} in_drop={state.in_drop} in_exit={state.in_exit} in_precise={state.in_precise}",
    ]
    return _draw_perception_debug(
        info, channel, frame=frame, raw_bboxes=ff, on_bboxes=on_ff, panel_lines=lines,
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUPPORTED_API_KEY_PROVIDERS = ("openrouter",)
FEEDER_DETECTION_ROLES = ("c_channel_2", "c_channel_3", "carousel")
EXIT_STUCK_INCIDENT_KIND = "exit_stuck"
CHANNEL_EXIT_STUCK_SOURCE_KIND = "channel_exit_stuck"
CLASSIFICATION_EXIT_RELEASE_SOURCE_KIND = "classification_exit_release"
CHANNEL_EXIT_STUCK_INCIDENT_KIND = EXIT_STUCK_INCIDENT_KIND
CHANNEL_DROPZONE_STUCK_INCIDENT_KIND = "channel_dropzone_stuck"
C2_SEPARATION_INCIDENT_KIND = "c2_separation_needed"
BULK_FEEDER_STALLED_INCIDENT_KIND = "bulk_feeder_stalled"
FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND = "feeder_detection_unavailable"
DISTRIBUTION_CHUTE_JAM_INCIDENT_KIND = "distribution_chute_jam"
DISTRIBUTION_SERVO_BUS_OFFLINE_INCIDENT_KIND = "distribution_servo_bus_offline"
DISTRIBUTION_NO_BIN_AVAILABLE_INCIDENT_KIND = "distribution_no_bin_available"
CLASSIFICATION_UNRESOLVED_INCIDENT_KIND = "classification_unresolved"
CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND = "classification_multi_drop_collision"
CLASSIFICATION_INTAKE_TIMEOUT_INCIDENT_KIND = "classification_intake_request_timeout"
CLASSIFICATION_TRACK_LOST_INCIDENT_KIND = "classification_track_lost"
CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND = "classification_exit_stuck"
CHANNEL_EXIT_RELEASE_GEAR_RATIO = 130.0 / 12.0
CHANNEL_EXIT_RELEASE_SETTLE_S = 0.12

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


def _hive_sample_collection_enabled() -> bool:
    try:
        return bool(getClassificationTrainingManager().hasEnabledHiveTargets())
    except Exception:
        return False


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
    if model == "google/gemini-3.5-flash":
        return "Gemini 3.5 Flash"
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


class ClassificationExitIncidentActionPayload(BaseModel):
    piece_uuid: Optional[str] = None


class ClassificationExitIncidentTestReleasePayload(BaseModel):
    piece_uuid: Optional[str] = None
    amplitude_output_deg: float
    microsteps_per_second: int
    cycles: int = 1
    acceleration_microsteps_per_second_sq: Optional[int] = None


class ChannelExitIncidentActionPayload(BaseModel):
    channel: Optional[str] = None


class ChannelDropzoneIncidentActionPayload(BaseModel):
    channel: Optional[str] = None
    global_id: Optional[int] = None
    track_id: Optional[int] = None


class Ch2SeparationIncidentActionPayload(BaseModel):
    channel: Optional[str] = None


class ChannelExitIncidentTestReleasePayload(BaseModel):
    channel: Optional[str] = None
    amplitude_output_deg: float
    microsteps_per_second: int
    cycles: int = 1
    acceleration_microsteps_per_second_sq: Optional[int] = None


class HiveLinkPayload(BaseModel):
    """Payload from the OAuth-style Hive linking flow.

    The browser walks the user from the Sorter to the Hive ``/link-machine``
    page, where the machine is registered against the user's already-
    authenticated Hive session. Hive then redirects back to the Sorter with
    the machine's freshly-minted api_token in the URL hash. The Sorter
    frontend reads the hash and POSTs the contents here so the token can be
    persisted next to the other configured Hive targets — no email/password
    ever crosses the wire.
    """

    target_name: str = ""
    url: str
    api_token: str
    machine_id: str = ""
    machine_name: str = ""
    token_prefix: str = ""
    enabled: bool = True


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


def _save_hive_targets(targets: list[dict[str, Any]], primary_target_id: str | None = None) -> None:
    if primary_target_id is None:
        existing = getHiveConfig() or {}
        primary_target_id = existing.get("primary_target_id")
    setHiveConfig({"targets": targets, "primary_target_id": primary_target_id})


def _load_hive_primary_id() -> str | None:
    config = getHiveConfig() or {}
    primary = config.get("primary_target_id")
    return primary if isinstance(primary, str) else None


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
    primary_target_id = _load_hive_primary_id()

    return {
        "ok": True,
        "configured_count": len(targets),
        "enabled_count": sum(1 for target in targets if bool(target.get("enabled", False))),
        "primary_target_id": primary_target_id,
        "targets": [
            {
                "id": target["id"],
                "name": target.get("name") or target.get("url"),
                "url": target.get("url", ""),
                "machine_id": target.get("machine_id"),
                "api_token_masked": _mask_hive_token(target.get("api_token")),
                "enabled": bool(target.get("enabled", False)),
                "is_primary": target["id"] == primary_target_id,
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

    _save_hive_targets(targets, primary_target_id=target_id)
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


class HivePrimaryPayload(BaseModel):
    target_id: str


@router.post("/api/settings/hive/primary")
def set_hive_primary(payload: HivePrimaryPayload) -> Dict[str, Any]:
    target_id = payload.target_id.strip()
    targets = _load_hive_targets()
    if not any(target.get("id") == target_id for target in targets):
        raise HTTPException(404, "Unknown Hive target.")
    _save_hive_targets(targets, primary_target_id=target_id)
    return {"ok": True, "message": "Primary Hive target set.", "primary_target_id": target_id}


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
    _save_hive_targets(targets, primary_target_id=target_id)
    getClassificationTrainingManager().reloadHiveUploader()
    return {
        "ok": True,
        "target_id": target_id,
        "target_name": target_name,
        "machine_id": str(machine_id),
        "machine_name": data.get("name", payload.machine_name),
        "token_prefix": data.get("token_prefix", raw_token[:8]),
    }


@router.post("/api/settings/hive/link")
def hive_link(payload: HiveLinkPayload) -> Dict[str, Any]:
    """Persist a Hive target produced by the OAuth-style linking flow.

    Counterpart to ``hive_register`` for the case where the machine was
    created on the Hive side (the user clicked "Pair this Sorter" on
    Hive while logged in). The Sorter never sees the user's credentials;
    Hive hands the Sorter an ``api_token`` via the return-URL hash and
    the frontend POSTs the bundle here so it can be stored next to any
    existing targets.
    """
    base_url = payload.url.strip().rstrip("/")
    if not base_url:
        raise HTTPException(400, "Hive URL is required.")
    api_token = payload.api_token.strip()
    if not api_token:
        raise HTTPException(400, "api_token is required.")

    target_name = payload.target_name.strip() or base_url
    targets = _load_hive_targets()
    target_id = uuid4().hex[:12]
    targets.append(
        {
            "id": target_id,
            "name": target_name,
            "url": base_url,
            "api_token": api_token,
            "enabled": bool(payload.enabled),
            "machine_id": str(payload.machine_id) if payload.machine_id else "",
        }
    )
    _save_hive_targets(targets, primary_target_id=target_id)
    getClassificationTrainingManager().reloadHiveUploader()
    return {
        "ok": True,
        "target_id": target_id,
        "target_name": target_name,
        "machine_id": str(payload.machine_id),
        "machine_name": payload.machine_name,
        "token_prefix": payload.token_prefix or api_token[:8],
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
# Versioned machine-settings backup to Hive
# ---------------------------------------------------------------------------


class ConfigBackupRestorePayload(BaseModel):
    version: int
    include_calibration: bool = False


@router.get("/api/hive/config-backups")
def hive_config_backups() -> Dict[str, Any]:
    from server import config_backup

    try:
        return {"ok": True, "versions": config_backup.list_versions()}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Failed to list config backups: {exc}")


@router.post("/api/hive/config-backup")
def hive_config_backup_now() -> Dict[str, Any]:
    from server import config_backup

    return config_backup.push_snapshot(trigger="manual")


@router.post("/api/hive/config-backup/restore")
def hive_config_backup_restore(payload: ConfigBackupRestorePayload) -> Dict[str, Any]:
    from server import config_backup
    from server.routers.system import restart_system

    try:
        result = config_backup.restore_version(
            payload.version, include_calibration=payload.include_calibration
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Restore failed: {exc}")
    # The TOML only takes effect after a backend restart.
    restart_system()
    return {**result, "restarting": True}


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
    hive_sample_collection_enabled = _hive_sample_collection_enabled()
    sample_collection_enabled_by_role = {
        channel_role: hive_sample_collection_enabled and _feeder_sample_collection_supported(channel_role)
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
    if role is not None:
        algorithm_by_role[role] = algorithm
    else:
        for channel_role in FEEDER_DETECTION_ROLES:
            algorithm_by_role[channel_role] = algorithm
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setFeederDetectionAlgorithm"):
        try:
            if role is not None:
                shared_state.vision_manager.setFeederDetectionAlgorithm(algorithm, role)
            else:
                shared_state.vision_manager.setFeederDetectionAlgorithm(algorithm)
            if hasattr(shared_state.vision_manager, "setFeederOpenRouterModel"):
                shared_state.vision_manager.setFeederOpenRouterModel(openrouter_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to apply feeder detection config: {exc}")
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "isFeederSampleCollectionEnabled"):
        sample_collection_enabled_by_role = {
            channel_role: bool(shared_state.vision_manager.isFeederSampleCollectionEnabled(channel_role))
            for channel_role in FEEDER_DETECTION_ROLES
        }
    else:
        hive_sample_collection_enabled = _hive_sample_collection_enabled()
        sample_collection_enabled_by_role = {
            channel_role: hive_sample_collection_enabled and _feeder_sample_collection_supported(channel_role)
            for channel_role in FEEDER_DETECTION_ROLES
        }
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
        }
    )
    role_label = _feeder_role_label(role)
    message = f"{role_label} detection uses {_detection_algorithm_label('feeder', algorithm)}."
    sample_collection_supported = _feeder_sample_collection_supported(role)
    if sample_collection_supported:
        if sample_collection_enabled:
            message += f" Enabled Hive targets will receive Gemini teacher samples for {role_label.lower()} moves."
        elif role is not None:
            message += f" No enabled Hive target is currently receiving {role_label.lower()} samples."
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
    sample_collection_enabled = _hive_sample_collection_enabled()
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
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "setCarouselDetectionAlgorithm"):
        try:
            shared_state.vision_manager.setCarouselDetectionAlgorithm(algorithm)
            if hasattr(shared_state.vision_manager, "setCarouselOpenRouterModel"):
                shared_state.vision_manager.setCarouselOpenRouterModel(openrouter_model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to apply carousel detection config: {exc}")
    if shared_state.vision_manager is not None and hasattr(shared_state.vision_manager, "isCarouselSampleCollectionEnabled"):
        sample_collection_enabled = bool(shared_state.vision_manager.isCarouselSampleCollectionEnabled())
    else:
        sample_collection_enabled = _hive_sample_collection_enabled()
    setCarouselDetectionConfig(
        {
            "algorithm": algorithm,
            "openrouter_model": openrouter_model,
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
            f"Carousel detection switched to {algorithm_label}. Capture a fresh baseline if detection stays unavailable. Enabled Hive targets will receive Gemini teacher samples for classical carousel triggers."
            if uses_baseline and sample_collection_enabled and _auxiliary_sample_collection_supported()
            else (
                f"Carousel detection switched to {algorithm_label}. Enabled Hive targets will receive Gemini teacher samples when Heatmap Diff is active."
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
        from subsystems.classification.bbox_projection import (
            translate_bbox_to_crop,
            translate_bboxes_to_crop,
        )
        save_model = None
        if payload.get("algorithm") == "gemini_sam" and hasattr(shared_state.vision_manager, "getClassificationOpenRouterModel"):
            try:
                save_model = shared_state.vision_manager.getClassificationOpenRouterModel()
            except Exception:
                save_model = None
        # Translate full-frame bboxes into zone-crop coords so Hive's
        # overlay aligns with the saved zone image.
        zone_bbox_tuple = (
            tuple(int(v) for v in zone_bbox)
            if isinstance(zone_bbox, (list, tuple)) and len(zone_bbox) >= 4
            else None
        )
        bbox_crop = (
            list(translate_bbox_to_crop(tuple(int(v) for v in bbox), zone_bbox_tuple))
            if isinstance(bbox, (list, tuple)) and len(bbox) >= 4
            and translate_bbox_to_crop(tuple(int(v) for v in bbox), zone_bbox_tuple) is not None
            else None
        )
        candidate_bboxes_crop = (
            [list(c) for c in translate_bboxes_to_crop(
                [tuple(int(v) for v in c) for c in candidate_bboxes if isinstance(c, (list, tuple)) and len(c) >= 4],
                zone_bbox_tuple,
            )]
            if isinstance(candidate_bboxes, list) else []
        )
        debug_result_for_save = dict(payload)
        debug_result_for_save["bbox"] = bbox_crop
        debug_result_for_save["candidate_bboxes"] = candidate_bboxes_crop
        try:
            saved = getClassificationTrainingManager().saveDetectionDebugCapture(
                camera=camera,
                algorithm=str(payload.get("algorithm") or ""),
                openrouter_model=save_model,
                debug_result=debug_result_for_save,
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
    from subsystems.classification.bbox_projection import (
        translate_bbox_to_crop,
        translate_bboxes_to_crop,
    )

    def _sample_crop_bbox() -> tuple[int, int, int, int] | None:
        if not isinstance(sample_capture, dict):
            return None
        image = sample_capture.get("input_image")
        offset = sample_capture.get("crop_offset")
        if not (
            hasattr(image, "shape")
            and isinstance(offset, (list, tuple))
            and len(offset) >= 2
        ):
            return None
        try:
            crop_h = int(image.shape[0])
            crop_w = int(image.shape[1])
            crop_x = int(offset[0])
            crop_y = int(offset[1])
        except Exception:
            return None
        if crop_w <= 0 or crop_h <= 0:
            return None
        return (crop_x, crop_y, crop_x + crop_w, crop_y + crop_h)

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
    # ``bbox`` / ``candidate_bboxes`` are in full-frame coordinates (the hive
    # detector shifts crop-space results back via ``_offsetDetectionResult``).
    # The sample image we archive is the polygon zone-crop (input_image from
    # ``_captureAuxiliarySampleFromFrame``). Translate the bboxes into
    # crop-space before persisting so Hive's overlay lands on the piece.
    zone_bbox_tuple = _sample_crop_bbox() or (
        tuple(int(v) for v in zone_bbox)
        if isinstance(zone_bbox, (list, tuple)) and len(zone_bbox) >= 4
        else None
    )
    bbox_crop = (
        translate_bbox_to_crop(tuple(int(v) for v in bbox), zone_bbox_tuple)
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4
        else None
    )
    candidate_bboxes_crop = (
        translate_bboxes_to_crop(
            [tuple(int(v) for v in c) for c in candidate_bboxes if isinstance(c, (list, tuple)) and len(c) >= 4],
            zone_bbox_tuple,
        )
        if isinstance(candidate_bboxes, list)
        else []
    )
    source_role = role
    vm = shared_state.vision_manager
    if vm is not None and hasattr(vm, "sampleSourceRoleForRole"):
        try:
            source_role = str(vm.sampleSourceRoleForRole(role))
        except Exception:
            source_role = role
    if isinstance(sample_capture, dict) and _auxiliary_sample_collection_supported():
        try:
            saved = getClassificationTrainingManager().saveAuxiliaryDetectionCapture(
                source="settings_detection_test",
                source_role=source_role,
                detection_scope=(
                    "feeder" if role in {"c_channel_2", "c_channel_3"} else "carousel"
                ),
                capture_reason="settings_detection_test",
                detection_algorithm=str(payload.get("algorithm") or ""),
                detection_openrouter_model=openrouter_model,
                detection_found=bool(payload.get("found")),
                detection_bbox=list(bbox_crop) if bbox_crop is not None else None,
                detection_candidate_bboxes=[list(c) for c in candidate_bboxes_crop],
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
        result = _classifyImages(shared_state.gc_ref, images)
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


@router.get("/api/classification-channel/debug")
def classification_channel_debug() -> Dict[str, Any]:
    controller = shared_state.controller_ref
    if controller is None or not hasattr(controller, "coordinator"):
        raise HTTPException(status_code=503, detail="Controller not available.")

    coordinator = controller.coordinator
    transport = getattr(coordinator, "transport", None)
    if transport is None or not hasattr(transport, "activePieces"):
        raise HTTPException(status_code=503, detail="Classification transport not available.")

    zone_manager = getattr(transport, "zone_manager", None)
    active_pieces = list(transport.activePieces())
    pieces_by_uuid = {piece.uuid: piece for piece in active_pieces}
    zones = list(zone_manager.zones()) if zone_manager is not None else []
    zones_by_uuid = {zone.piece_uuid: zone for zone in zones}
    irl_config = getattr(coordinator, "irl_config", None)
    cc_cfg = getattr(irl_config, "classification_channel_config", None)

    def _piece_payload(piece: Any) -> Dict[str, Any]:
        zone = zones_by_uuid.get(piece.uuid)
        return {
            "uuid": piece.uuid,
            "track_global_id": piece.tracked_global_id,
            "stage": getattr(getattr(piece, "stage", None), "value", str(getattr(piece, "stage", None))),
            "classification_status": getattr(
                getattr(piece, "classification_status", None),
                "value",
                str(getattr(piece, "classification_status", None)),
            ),
            "part_id": piece.part_id,
            "color_id": piece.color_id,
            "color_name": piece.color_name,
            "category_id": piece.category_id,
            "destination_bin": list(piece.destination_bin) if piece.destination_bin else None,
            "thumbnail_present": bool(piece.thumbnail),
            "top_image_present": bool(piece.top_image),
            "bottom_image_present": bool(piece.bottom_image),
            "brickognize_preview_url": piece.brickognize_preview_url,
            "brickognize_source_view": piece.brickognize_source_view,
            "size_class": piece.classification_channel_size_class,
            "zone_state": piece.classification_channel_zone_state,
            "zone_center_deg": piece.classification_channel_zone_center_deg,
            "zone_half_width_deg": piece.classification_channel_zone_half_width_deg,
            "soft_guard_deg": piece.classification_channel_soft_guard_deg,
            "hard_guard_deg": piece.classification_channel_hard_guard_deg,
            "created_at": piece.created_at,
            "updated_at": piece.updated_at,
            "feeding_started_at": piece.feeding_started_at,
            "carousel_detected_confirmed_at": piece.carousel_detected_confirmed_at,
            "carousel_snapping_started_at": piece.carousel_snapping_started_at,
            "carousel_snapping_completed_at": piece.carousel_snapping_completed_at,
            "classified_at": piece.classified_at,
            "zone": zone.to_overlay_payload() if zone is not None else None,
        }

    drop_angle_deg = float(getattr(cc_cfg, "drop_angle_deg", 0.0)) if cc_cfg is not None else None
    drop_tolerance_deg = (
        float(getattr(cc_cfg, "drop_tolerance_deg", 0.0)) if cc_cfg is not None else None
    )
    point_of_no_return_deg = (
        float(getattr(cc_cfg, "point_of_no_return_deg", 0.0)) if cc_cfg is not None else None
    )
    intake_angle_deg = float(getattr(cc_cfg, "intake_angle_deg", 0.0)) if cc_cfg is not None else None

    drop_window_piece_uuids: list[str] = []
    if zone_manager is not None and drop_angle_deg is not None and drop_tolerance_deg is not None:
        drop_window_piece_uuids = list(
            zone_manager.pieces_in_window(
                center_deg=drop_angle_deg,
                tolerance_deg=drop_tolerance_deg,
            )
        )

    runtime_stats = (
        getattr(shared_state.gc_ref, "runtime_stats", None)
        if shared_state.gc_ref is not None
        else None
    )
    recognizer_counts = {
        "recognize_fired_total": 0,
        "recognize_skipped_no_crops": 0,
        "recognize_skipped_no_carousel_crops": 0,
        "recognize_skipped_not_on_carousel": 0,
        "recognize_skipped_carousel_quota": 0,
        "recognize_skipped_carousel_dwell": 0,
        "brickognize_empty_result": 0,
        "brickognize_timeout_total": 0,
    }
    if runtime_stats is not None:
        source = getattr(runtime_stats, "_recognizer_counts", None)
        if isinstance(source, dict):
            for key in recognizer_counts:
                value = source.get(key)
                if isinstance(value, int):
                    recognizer_counts[key] = value

    return {
        "dynamic_mode": bool(getattr(transport, "dynamic_mode", False)),
        "counts": {
            "active_pieces": len(active_pieces),
            "zones": len(zones),
            "pending_classifications": len(getattr(transport, "_pending_classifications", {})),
            "drop_window_pieces": len(drop_window_piece_uuids),
            **recognizer_counts,
        },
        "gates": {
            "classification_ready": getattr(coordinator.shared, "classification_ready", None),
            "distribution_ready": getattr(coordinator.shared, "distribution_ready", None),
        },
        "positions": {
            "hood_piece_uuid": getattr(transport, "_hood_piece_uuid", None),
            "positioning_piece_uuid": getattr(transport, "_positioning_piece_uuid", None),
            "exit_piece_uuid": getattr(getattr(transport, "_exit_piece", None), "uuid", None),
        },
        "config": {
            "intake_angle_deg": intake_angle_deg,
            "drop_angle_deg": drop_angle_deg,
            "drop_tolerance_deg": drop_tolerance_deg,
            "point_of_no_return_deg": point_of_no_return_deg,
            "positioning_window_deg": float(getattr(cc_cfg, "positioning_window_deg", 0.0))
            if cc_cfg is not None
            else None,
            "max_zones": int(getattr(cc_cfg, "max_zones", 0)) if cc_cfg is not None else None,
        },
        "drop_window_piece_uuids": drop_window_piece_uuids,
        "hard_collisions": list(zone_manager.hard_collisions()) if zone_manager is not None else [],
        "active_pieces": [_piece_payload(piece) for piece in active_pieces],
        "zones": [zone.to_overlay_payload() for zone in zones],
        "exit_release_incident": _classification_channel_exit_incident_snapshot_or_none(),
    }


def _classification_channel_running_state() -> Any:
    controller = shared_state.controller_ref
    coordinator = getattr(controller, "coordinator", None) if controller is not None else None
    classification = getattr(coordinator, "classification", None) if coordinator is not None else None
    states_map = getattr(classification, "states_map", None)
    if isinstance(states_map, dict):
        for state in states_map.values():
            if hasattr(state, "approveExitReleaseIncident"):
                return state
    current_state = getattr(classification, "current_state", None)
    state_obj = None
    if isinstance(states_map, dict) and current_state is not None:
        state_obj = states_map.get(current_state)
    if state_obj is not None and hasattr(state_obj, "approveExitReleaseIncident"):
        return state_obj
    raise HTTPException(status_code=503, detail="Classification-channel runtime not available.")


def _classification_channel_exit_incident_snapshot_or_none() -> Dict[str, Any] | None:
    try:
        running = _classification_channel_running_state()
    except HTTPException:
        return None
    snapshot = running.exitReleaseIncidentSnapshot()
    return snapshot if isinstance(snapshot, dict) else None


@router.get("/api/classification-channel/exit-incident")
def classification_channel_exit_incident() -> Dict[str, Any]:
    return {
        "ok": True,
        "incident": _classification_channel_exit_incident_snapshot_or_none(),
    }


@router.post("/api/classification-channel/exit-incident/continue")
def classification_channel_exit_incident_continue(
    payload: ClassificationExitIncidentActionPayload | None = None,
) -> Dict[str, Any]:
    running = _classification_channel_running_state()
    try:
        incident = running.approveExitReleaseIncident(
            None if payload is None else payload.piece_uuid
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "incident": incident}


@router.post("/api/classification-channel/exit-incident/test-release")
def classification_channel_exit_incident_test_release(
    payload: ClassificationExitIncidentTestReleasePayload,
) -> Dict[str, Any]:
    running = _classification_channel_running_state()
    try:
        result = running.testExitReleaseIncident(
            piece_uuid=payload.piece_uuid,
            amplitude_output_deg=payload.amplitude_output_deg,
            microsteps_per_second=payload.microsteps_per_second,
            cycles=payload.cycles,
            acceleration_microsteps_per_second_sq=payload.acceleration_microsteps_per_second_sq,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "release": result}


@router.post("/api/classification-channel/exit-incident/clear")
def classification_channel_exit_incident_clear(
    payload: ClassificationExitIncidentActionPayload | None = None,
) -> Dict[str, Any]:
    running = _classification_channel_running_state()
    try:
        result = running.clearExitReleaseIncident(
            None if payload is None else payload.piece_uuid
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.post("/api/classification-channel/fallback-incident/clear")
def classification_channel_fallback_incident_clear(
    payload: ClassificationExitIncidentActionPayload | None = None,
) -> Dict[str, Any]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    fallback_kinds = {
        CLASSIFICATION_UNRESOLVED_INCIDENT_KIND,
        CLASSIFICATION_MULTI_DROP_COLLISION_INCIDENT_KIND,
        CLASSIFICATION_INTAKE_TIMEOUT_INCIDENT_KIND,
        CLASSIFICATION_TRACK_LOST_INCIDENT_KIND,
        CLASSIFICATION_EXIT_STUCK_INCIDENT_KIND,
    }
    if not isinstance(active, dict) or active.get("kind") not in fallback_kinds:
        for kind in fallback_kinds:
            runtime_stats.clearActiveIncident(kind=kind)
        return {"ok": True, "cleared": False, "reason": "no_active_incident"}

    requested_piece_uuid = None if payload is None else payload.piece_uuid
    if (
        isinstance(requested_piece_uuid, str)
        and requested_piece_uuid.strip()
        and requested_piece_uuid.strip() != active.get("piece_uuid")
    ):
        raise HTTPException(
            status_code=400,
            detail="The active classification incident belongs to another piece.",
        )

    kind = str(active.get("kind"))
    runtime_stats.clearActiveIncident(
        kind=kind,
        piece_uuid=(
            str(active.get("piece_uuid"))
            if isinstance(active.get("piece_uuid"), str)
            else None
        ),
    )
    return {
        "ok": True,
        "cleared": True,
        "kind": kind,
        "piece_uuid": active.get("piece_uuid"),
        "channel": "c4",
    }


def _runtime_stats_or_503() -> Any:
    runtime_stats = (
        getattr(shared_state.gc_ref, "runtime_stats", None)
        if shared_state.gc_ref is not None
        else None
    )
    if runtime_stats is None:
        raise HTTPException(status_code=503, detail="Runtime stats are not available.")
    return runtime_stats


def _normalize_channel_exit_channel(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip().lower().replace("-", "_")
    if candidate in ("c2", "ch2", "c_channel_2", "channel_2"):
        return "c2"
    if candidate in ("c3", "ch3", "c_channel_3", "channel_3"):
        return "c3"
    raise HTTPException(status_code=400, detail="Unsupported channel exit incident channel.")


def _normalize_channel_dropzone_channel(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip().lower().replace("-", "_")
    if candidate in ("c2", "ch2", "c_channel_2", "channel_2"):
        return "c2"
    if candidate in ("c3", "ch3", "c_channel_3", "channel_3"):
        return "c3"
    if candidate in (
        "c4",
        "ch4",
        "channel_4",
        "c_channel_4",
        "carousel",
        "classification",
        "classification_channel",
    ):
        return "c4"
    raise HTTPException(status_code=400, detail="Unsupported channel dropzone incident channel.")


def _active_channel_exit_incident(
    requested_channel: str | None = None,
) -> tuple[Any, Dict[str, Any]]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    if not isinstance(active, dict) or not _is_channel_exit_incident(active):
        raise HTTPException(status_code=409, detail="No C2/C3 exit incident is waiting.")

    active_channel = _normalize_channel_exit_channel(str(active.get("channel") or ""))
    wanted_channel = _normalize_channel_exit_channel(requested_channel)
    if wanted_channel is not None and wanted_channel != active_channel:
        raise HTTPException(status_code=400, detail="The active exit incident belongs to another channel.")

    active["channel"] = active_channel
    return runtime_stats, active


def _is_channel_exit_incident(active: Dict[str, Any]) -> bool:
    kind = active.get("kind")
    source_kind = active.get("source_kind")
    if kind == "channel_exit_stuck":
        return True
    if kind != CHANNEL_EXIT_STUCK_INCIDENT_KIND:
        return False
    if source_kind not in (None, CHANNEL_EXIT_STUCK_SOURCE_KIND):
        return False
    try:
        _normalize_channel_exit_channel(str(active.get("channel") or ""))
    except HTTPException:
        return False
    return True


def _payload_global_id(payload: ChannelDropzoneIncidentActionPayload | None) -> int | None:
    if payload is None:
        return None
    value = payload.global_id if payload.global_id is not None else payload.track_id
    return int(value) if value is not None else None


def _active_channel_dropzone_incident(
    requested_channel: str | None = None,
    requested_global_id: int | None = None,
) -> tuple[Any, Dict[str, Any]]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    if not isinstance(active, dict) or active.get("kind") != CHANNEL_DROPZONE_STUCK_INCIDENT_KIND:
        raise HTTPException(status_code=409, detail="No channel dropzone incident is waiting.")

    active_channel = _normalize_channel_dropzone_channel(str(active.get("channel") or ""))
    wanted_channel = _normalize_channel_dropzone_channel(requested_channel)
    if wanted_channel is not None and wanted_channel != active_channel:
        raise HTTPException(status_code=400, detail="The active dropzone incident belongs to another channel.")

    active_global_id = active.get("global_id", active.get("track_id"))
    if not isinstance(active_global_id, int):
        raise HTTPException(status_code=409, detail="The active dropzone incident has no tracker id.")
    if requested_global_id is not None and int(requested_global_id) != int(active_global_id):
        raise HTTPException(status_code=400, detail="The active dropzone incident belongs to another tracker id.")

    active["channel"] = active_channel
    active["global_id"] = int(active_global_id)
    active["track_id"] = int(active_global_id)
    return runtime_stats, active


def _feeding_runtime_state_or_503() -> Any:
    controller = shared_state.controller_ref
    coordinator = getattr(controller, "coordinator", None) if controller is not None else None
    feeder = getattr(coordinator, "feeder", None)
    states_map = getattr(feeder, "states_map", None)
    if isinstance(states_map, dict):
        for state in states_map.values():
            if hasattr(state, "acknowledgeDropzoneStuckIncident"):
                return state
    raise HTTPException(status_code=503, detail="Feeder runtime not available.")


def _active_irl_or_503() -> Any:
    irl = shared_state.getActiveIRL() or shared_state.hardware_runtime_irl
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Start or home the system first.")
    return irl


def _channel_exit_stepper(channel: str) -> tuple[str, Any]:
    irl = _active_irl_or_503()
    if channel == "c2":
        stepper_key = "c_channel_2"
        stepper = getattr(irl, "c_channel_2_rotor_stepper", None)
    elif channel == "c3":
        stepper_key = "c_channel_3"
        stepper = getattr(irl, "c_channel_3_rotor_stepper", None)
    else:
        raise HTTPException(status_code=400, detail="Unsupported channel exit incident channel.")
    if stepper is None:
        raise HTTPException(status_code=500, detail=f"Stepper '{stepper_key}' unavailable.")
    return stepper_key, stepper


def _validate_channel_exit_release_payload(
    payload: ChannelExitIncidentTestReleasePayload,
) -> dict[str, Any]:
    amplitude_output = float(payload.amplitude_output_deg)
    if amplitude_output < 0.1 or amplitude_output > 12.0:
        raise HTTPException(status_code=400, detail="amplitude_output_deg must be between 0.1 and 12.0.")
    speed = int(payload.microsteps_per_second)
    if speed < 100 or speed > 16000:
        raise HTTPException(status_code=400, detail="microsteps_per_second must be between 100 and 16000.")
    cycles = int(payload.cycles)
    if cycles < 1 or cycles > 20:
        raise HTTPException(status_code=400, detail="cycles must be between 1 and 20.")
    if payload.acceleration_microsteps_per_second_sq is None:
        acceleration = max(1000, min(48000, int(round(speed * 3.0))))
    else:
        acceleration = int(payload.acceleration_microsteps_per_second_sq)
        if acceleration < 1000 or acceleration > 48000:
            raise HTTPException(
                status_code=400,
                detail="acceleration_microsteps_per_second_sq must be between 1000 and 48000.",
            )
    return {
        "amplitude_output_deg": amplitude_output,
        "microsteps_per_second": speed,
        "acceleration_microsteps_per_second_sq": acceleration,
        "cycles": cycles,
    }


def _channel_exit_release_plan(
    *,
    amplitude_output_deg: float,
    cycles: int,
) -> list[tuple[str, float, float]]:
    amplitude_stepper = float(amplitude_output_deg) * CHANNEL_EXIT_RELEASE_GEAR_RATIO
    plan: list[tuple[str, float, float]] = []
    for cycle in range(1, cycles + 1):
        is_last_cycle = cycle == cycles
        plan.extend(
            [
                (f"manual-test.{cycle}.cw", amplitude_stepper, CHANNEL_EXIT_RELEASE_SETTLE_S),
                (f"manual-test.{cycle}.ccw-cross", -2.0 * amplitude_stepper, CHANNEL_EXIT_RELEASE_SETTLE_S),
                (f"manual-test.{cycle}.cw-return", amplitude_stepper, 0.0 if is_last_cycle else CHANNEL_EXIT_RELEASE_SETTLE_S),
            ]
        )
    return plan


def _publish_channel_exit_incident_status(
    runtime_stats: Any,
    incident: Dict[str, Any],
    *,
    status: str,
    **extra: Any,
) -> None:
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    if not isinstance(active, dict):
        return
    if not _is_channel_exit_incident(active):
        return
    if active.get("channel") != incident.get("channel"):
        return
    updated = dict(active)
    updated.update(extra)
    updated["status"] = status
    updated["awaiting_operator"] = status == "waiting_for_operator"
    runtime_stats.setActiveIncident(updated)


def _estimate_channel_exit_move_timeout_ms(stepper: Any, move_deg: float, speed: int) -> int:
    estimate_fn = getattr(stepper, "estimateMoveDegreesMs", None)
    if callable(estimate_fn):
        try:
            estimate = int(estimate_fn(abs(float(move_deg)), max_speed=max(1, int(speed))))
            return max(1500, estimate + 1500)
        except Exception:
            pass
    return 5000


def _run_channel_exit_release_motion(
    *,
    runtime_stats: Any,
    incident: Dict[str, Any],
    stepper: Any,
    lock: threading.Lock,
    plan: list[tuple[str, float, float]],
    speed: int,
    acceleration: int,
) -> None:
    ok = True
    error: str | None = None
    strokes_completed = 0
    try:
        try:
            stepper.enabled = True
        except Exception:
            pass
        for label, move_deg, settle_s in plan:
            try:
                stepper.set_speed_limits(16, int(speed))
            except Exception as exc:
                raise RuntimeError(f"Could not apply exit-release speed: {exc}") from exc
            set_acceleration = getattr(stepper, "set_acceleration", None)
            if callable(set_acceleration):
                try:
                    set_acceleration(int(acceleration))
                except Exception as exc:
                    raise RuntimeError(f"Could not apply exit-release acceleration: {exc}") from exc

            move_blocking = getattr(stepper, "move_degrees_blocking", None)
            if callable(move_blocking):
                moved = bool(
                    move_blocking(
                        float(move_deg),
                        timeout_ms=_estimate_channel_exit_move_timeout_ms(stepper, move_deg, speed),
                    )
                )
            else:
                move = getattr(stepper, "move_degrees", None)
                if not callable(move):
                    raise RuntimeError("Stepper does not support degree moves.")
                moved = bool(move(float(move_deg)))
                time.sleep(max(0.0, _estimate_channel_exit_move_timeout_ms(stepper, move_deg, speed) / 1000.0))
            if not moved:
                raise RuntimeError(f"Exit-release move {label} was not acknowledged.")
            strokes_completed += 1
            if settle_s > 0.0:
                time.sleep(float(settle_s))
    except Exception as exc:
        ok = False
        error = str(exc)
    finally:
        _publish_channel_exit_incident_status(
            runtime_stats,
            incident,
            status="waiting_for_operator",
            last_test_ok=ok,
            last_test_error=error,
            last_test_completed_at=time.time(),
            last_test_strokes_completed=strokes_completed,
        )
        lock.release()


@router.post("/api/feeder/channel-exit-incident/test-release")
def feeder_channel_exit_incident_test_release(
    payload: ChannelExitIncidentTestReleasePayload,
) -> Dict[str, Any]:
    runtime_stats, incident = _active_channel_exit_incident(payload.channel)
    stepper_key, stepper = _channel_exit_stepper(str(incident["channel"]))
    release = _validate_channel_exit_release_payload(payload)
    plan = _channel_exit_release_plan(
        amplitude_output_deg=float(release["amplitude_output_deg"]),
        cycles=int(release["cycles"]),
    )

    stopped = getattr(stepper, "stopped", True)
    if stopped is False:
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper_key}' is still moving.")

    lock = shared_state.pulse_locks.setdefault(stepper_key, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper_key}' is already moving.")

    result = {
        "channel": incident["channel"],
        **release,
        "first_stroke_stepper_deg": plan[0][1] if plan else 0.0,
        "stroke_count": len(plan),
    }
    _publish_channel_exit_incident_status(
        runtime_stats,
        incident,
        status="manual_test_running",
        **result,
    )
    threading.Thread(
        target=_run_channel_exit_release_motion,
        kwargs={
            "runtime_stats": runtime_stats,
            "incident": incident,
            "stepper": stepper,
            "lock": lock,
            "plan": plan,
            "speed": int(release["microsteps_per_second"]),
            "acceleration": int(release["acceleration_microsteps_per_second_sq"]),
        },
        daemon=True,
    ).start()
    return {"ok": True, "release": result}


@router.post("/api/feeder/channel-exit-incident/clear")
def feeder_channel_exit_incident_clear(
    payload: ChannelExitIncidentActionPayload | None = None,
) -> Dict[str, Any]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    if not isinstance(active, dict) or not _is_channel_exit_incident(active):
        runtime_stats.clearActiveIncident(kind=CHANNEL_EXIT_STUCK_INCIDENT_KIND)
        return {"ok": True, "cleared": False, "reason": "no_active_incident"}

    active_channel = _normalize_channel_exit_channel(str(active.get("channel") or ""))
    requested_channel = _normalize_channel_exit_channel(None if payload is None else payload.channel)
    if requested_channel is not None and requested_channel != active_channel:
        raise HTTPException(status_code=400, detail="The active exit incident belongs to another channel.")

    runtime_stats.clearActiveIncident(kind=str(active.get("kind") or CHANNEL_EXIT_STUCK_INCIDENT_KIND))
    return {"ok": True, "cleared": True, "channel": active_channel}


@router.post("/api/feeder/channel-dropzone-incident/acknowledge")
def feeder_channel_dropzone_incident_acknowledge(
    payload: ChannelDropzoneIncidentActionPayload | None = None,
) -> Dict[str, Any]:
    _runtime_stats, active = _active_channel_dropzone_incident(
        None if payload is None else payload.channel,
        _payload_global_id(payload),
    )
    feeding = _feeding_runtime_state_or_503()
    try:
        return feeding.acknowledgeDropzoneStuckIncident(
            active["channel"],
            int(active["global_id"]),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/feeder/channel-dropzone-incident/clear")
def feeder_channel_dropzone_incident_clear(
    payload: ChannelDropzoneIncidentActionPayload | None = None,
) -> Dict[str, Any]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    if not isinstance(active, dict) or active.get("kind") != CHANNEL_DROPZONE_STUCK_INCIDENT_KIND:
        runtime_stats.clearActiveIncident(kind=CHANNEL_DROPZONE_STUCK_INCIDENT_KIND)
        return {"ok": True, "cleared": False, "reason": "no_active_incident"}

    _runtime_stats, active = _active_channel_dropzone_incident(
        None if payload is None else payload.channel,
        _payload_global_id(payload),
    )
    feeding = _feeding_runtime_state_or_503()
    try:
        return feeding.clearDropzoneStuckIncident(
            active["channel"],
            int(active["global_id"]),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/feeder/ch2-separation-incident/clear")
def feeder_ch2_separation_incident_clear(
    payload: Ch2SeparationIncidentActionPayload | None = None,
) -> Dict[str, Any]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    if not isinstance(active, dict) or active.get("kind") != C2_SEPARATION_INCIDENT_KIND:
        runtime_stats.clearActiveIncident(kind=C2_SEPARATION_INCIDENT_KIND)
        return {"ok": True, "cleared": False, "reason": "no_active_incident"}

    requested_channel = _normalize_channel_exit_channel(None if payload is None else payload.channel)
    if requested_channel is not None and requested_channel != "c2":
        raise HTTPException(status_code=400, detail="The active separation incident belongs to C2.")

    runtime_stats.clearActiveIncident(kind=C2_SEPARATION_INCIDENT_KIND)
    return {"ok": True, "cleared": True, "channel": "c2"}


@router.post("/api/feeder/bulk-feed-incident/clear")
def feeder_bulk_feed_incident_clear(
    payload: Ch2SeparationIncidentActionPayload | None = None,
) -> Dict[str, Any]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    if not isinstance(active, dict) or active.get("kind") != BULK_FEEDER_STALLED_INCIDENT_KIND:
        runtime_stats.clearActiveIncident(kind=BULK_FEEDER_STALLED_INCIDENT_KIND)
        return {"ok": True, "cleared": False, "reason": "no_active_incident"}

    requested_channel = None if payload is None else payload.channel
    if requested_channel is not None and requested_channel not in {"c1", "ch1", "bulk_feeder"}:
        raise HTTPException(status_code=400, detail="The active bulk-feed incident belongs to C1.")

    runtime_stats.clearActiveIncident(kind=BULK_FEEDER_STALLED_INCIDENT_KIND)
    return {"ok": True, "cleared": True, "channel": "c1"}


@router.post("/api/feeder/detection-incident/clear")
def feeder_detection_incident_clear() -> Dict[str, Any]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    if not isinstance(active, dict) or active.get("kind") != FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND:
        runtime_stats.clearActiveIncident(kind=FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND)
        return {"ok": True, "cleared": False, "reason": "no_active_incident"}

    runtime_stats.clearActiveIncident(kind=FEEDER_DETECTION_UNAVAILABLE_INCIDENT_KIND)
    return {"ok": True, "cleared": True, "channel": "feeder"}


@router.post("/api/distribution/incident/clear")
def distribution_incident_clear() -> Dict[str, Any]:
    runtime_stats = _runtime_stats_or_503()
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    distribution_kinds = {
        DISTRIBUTION_CHUTE_JAM_INCIDENT_KIND,
        DISTRIBUTION_SERVO_BUS_OFFLINE_INCIDENT_KIND,
        DISTRIBUTION_NO_BIN_AVAILABLE_INCIDENT_KIND,
    }
    if not isinstance(active, dict) or active.get("kind") not in distribution_kinds:
        for kind in distribution_kinds:
            runtime_stats.clearActiveIncident(kind=kind)
        return {"ok": True, "cleared": False, "reason": "no_active_incident"}

    kind = str(active.get("kind"))
    if kind == DISTRIBUTION_NO_BIN_AVAILABLE_INCIDENT_KIND:
        approver = getattr(shared_state, "approveDistributionNoBinPassthrough", None)
        if callable(approver):
            try:
                approver(active.get("piece_uuid") if isinstance(active.get("piece_uuid"), str) else None)
            except Exception:
                pass
    runtime_stats.clearActiveIncident(kind=kind)
    return {"ok": True, "cleared": True, "kind": kind, "channel": "distribution"}


@router.post("/api/classification-channel/wall-phase")
def classification_channel_wall_phase(
    include_lines: bool = False,
) -> Dict[str, Any]:
    frame = _classification_channel_live_frame()

    from vision.c4_wall_phase import detect_c4_wall_phase

    result = detect_c4_wall_phase(frame.raw)
    return {
        "ok": True,
        "frame_luma": _frame_luma_payload(frame.raw),
        **result.as_dict(include_lines=include_lines),
    }


def _frame_luma_payload(frame_bgr: Any) -> Dict[str, Any]:
    if frame_bgr is None or not hasattr(frame_bgr, "shape"):
        return {}
    try:
        if len(frame_bgr.shape) == 3:
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame_bgr
        if gray.size == 0:
            return {}
        return {
            "mean": float(np.mean(gray)),
            "p95": float(np.percentile(gray, 95)),
            "max": int(np.max(gray)),
            "nonblack_gt25_ratio": float(np.mean(gray > 25)),
        }
    except Exception:
        return {}


def _classification_channel_live_frame() -> Any:
    vm = shared_state.vision_manager
    if vm is None or not hasattr(vm, "getCaptureThreadForRole"):
        raise HTTPException(status_code=503, detail="Vision manager not available.")

    capture = vm.getCaptureThreadForRole("carousel")
    if capture is None:
        capture = vm.getCaptureThreadForRole("classification_channel")
    if capture is None:
        raise HTTPException(status_code=503, detail="Classification-channel camera not available.")
    frame = capture.latest_frame
    if frame is None:
        raise HTTPException(status_code=503, detail="No live classification-channel frame available.")
    return frame


@router.post("/api/classification-channel/sector-occupancy")
def classification_channel_sector_occupancy(
    include_lines: bool = False,
    force_detection: bool = False,
) -> Dict[str, Any]:
    vm = shared_state.vision_manager
    if vm is None:
        raise HTTPException(status_code=503, detail="Vision manager not available.")
    if not hasattr(vm, "getClassificationChannelDetectionCandidates"):
        raise HTTPException(status_code=503, detail="Classification-channel detection is unavailable.")

    frame = _classification_channel_live_frame()
    from vision.c4_wall_phase import detect_c4_wall_phase
    from subsystems.classification_channel.five_sector_platter import (
        C4FiveSectorPlatter,
        C4SectorDetection,
    )

    phase = detect_c4_wall_phase(frame.raw)
    irl_config = _active_irl_config()
    platter = C4FiveSectorPlatter.from_irl_config(irl_config)
    phase_offset = phase.sector_offset_deg if phase.sector_offset_deg is not None else 0.0

    if phase.center_x is None or phase.center_y is None:
        return {
            "ok": False,
            "message": phase.message,
            "frame_luma": _frame_luma_payload(frame.raw),
            "wall_phase": phase.as_dict(include_lines=include_lines),
            "sectors": [],
            "candidate_bboxes": [],
            "detections": [],
        }

    try:
        candidate_bboxes = vm.getClassificationChannelDetectionCandidates(
            force=force_detection,
            frame=frame,
        )
    except TypeError:
        candidate_bboxes = vm.getClassificationChannelDetectionCandidates(
            force=force_detection,
        )

    detections: list[C4SectorDetection] = []
    detection_payloads: list[dict[str, Any]] = []
    center_xy = (float(phase.center_x), float(phase.center_y))
    for index, candidate in enumerate(candidate_bboxes):
        if not isinstance(candidate, (list, tuple)) or len(candidate) < 4:
            continue
        bbox = tuple(float(value) for value in candidate[:4])
        detection = C4SectorDetection.from_bbox(
            bbox,
            center_xy=center_xy,
            confidence=1.0,
            track_id=index,
        )
        detections.append(detection)
        detection_payloads.append(
            {
                "bbox": [int(round(value)) for value in bbox],
                "angle_deg": detection.angle_deg,
                "sector_index": platter.sector_for_angle(
                    detection.angle_deg,
                    wall_offset_deg=phase_offset,
                ),
            }
        )

    handoff_sector, exit_sector = _classification_channel_role_sectors(
        platter,
        phase_offset,
        irl_config,
    )
    sectors = platter.occupancy_from_detections(
        detections,
        wall_offset_deg=phase_offset,
        handoff_sector=handoff_sector,
        exit_sector=exit_sector,
    )
    return {
        "ok": True,
        "frame_resolution": [int(frame.raw.shape[1]), int(frame.raw.shape[0])],
        "frame_luma": _frame_luma_payload(frame.raw),
        "sector_count": platter.sector_count,
        "sector_size_deg": platter.sector_size_deg,
        "sector_offset_deg": phase.sector_offset_deg,
        "phase_ok": phase.ok,
        "wall_phase": phase.as_dict(include_lines=include_lines),
        "handoff_sector": handoff_sector,
        "exit_sector": exit_sector,
        "candidate_bboxes": [
            [int(round(value)) for value in candidate[:4]]
            for candidate in candidate_bboxes
            if isinstance(candidate, (list, tuple)) and len(candidate) >= 4
        ],
        "detections": detection_payloads,
        "sectors": [sector.as_dict() for sector in sectors],
    }


def _active_irl_config() -> Any:
    controller = shared_state.controller_ref
    if controller is not None and hasattr(controller, "coordinator"):
        coordinator = controller.coordinator
        config = getattr(coordinator, "irl_config", None)
        if config is not None:
            return config
    return None


def _classification_channel_role_sectors(
    platter: Any,
    phase_offset_deg: float,
    irl_config: Any,
) -> tuple[int | None, int | None]:
    cfg = getattr(irl_config, "classification_channel_config", None)
    if cfg is None:
        return None, None
    handoff_sector = None
    exit_sector = None
    intake_angle = getattr(cfg, "intake_angle_deg", None)
    if isinstance(intake_angle, (int, float)):
        handoff_sector = platter.sector_for_angle(
            float(intake_angle),
            wall_offset_deg=phase_offset_deg,
        )
    drop_angle = getattr(cfg, "drop_angle_deg", None)
    if isinstance(drop_angle, (int, float)):
        exit_sector = platter.sector_for_angle(
            float(drop_angle),
            wall_offset_deg=phase_offset_deg,
        )
    return handoff_sector, exit_sector


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
