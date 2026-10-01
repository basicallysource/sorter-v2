"""Detection configuration, API keys, and detection test/debug endpoints."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Dict, List
from uuid import uuid4

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import local_state
from hive_telemetry import (
    getTargetTelemetrySettings,
    resetTargetTelemetrySettings,
    setTargetTelemetrySettings,
    telemetryFieldList,
)
from perception.overlay import drawChannelZones
from server import shared_state
from server.classification_training import TRAINING_ROOT, getClassificationTrainingManager
from server.machine_naming import display_name_from_hostname, random_display_name
from server.routers.sorting_profiles import start_first_default_profile_if_none
from server.routers.tailscale import current_hostname
from toml_config import getDetectionConfig, getMachineNickname, setDetectionConfig
from vision.detection_registry import (
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

# Constants

SUPPORTED_API_KEY_PROVIDERS = ("openrouter",)
FEEDER_DETECTION_ROLES = ("c_channel_2", "c_channel_3")
# Detection algorithm helper functions


def _normalize_feeder_detection_algorithm(value: str | None) -> str:
    return normalize_detection_algorithm("feeder", value)


def _normalize_carousel_detection_algorithm(value: str | None) -> str:
    return normalize_detection_algorithm("carousel", value)


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


# Pydantic models


class DetectionConfigPayload(BaseModel):
    algorithm: str


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


# API keys endpoints


@router.get("/api/settings/api-keys")
def get_api_keys() -> Dict[str, Any]:
    saved = local_state.get_api_keys()
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
    local_state.set_api_keys(saved)
    os.environ["OPENROUTER_API_KEY"] = payload.key.strip()
    return {"ok": True, "message": f"API key for {payload.provider} saved and activated."}


# Hive upload config


def _load_hive_targets() -> list[dict[str, Any]]:
    config = local_state.get_hive_config() or {}
    targets = config.get("targets")
    if not isinstance(targets, list):
        return []
    return [dict(target) for target in targets if isinstance(target, dict)]


def _save_hive_targets(targets: list[dict[str, Any]], primary_target_id: str | None = None) -> None:
    if primary_target_id is None:
        existing = local_state.get_hive_config() or {}
        primary_target_id = existing.get("primary_target_id")
    local_state.set_hive_config({"targets": targets, "primary_target_id": primary_target_id})


def _reloadHiveConsumers() -> dict[str, Any]:
    # Reload both the sample uploader and the piece-history sync worker so a
    # target add/remove/enable takes effect without a backend restart.
    status = getClassificationTrainingManager().reloadHiveUploader()
    gc = shared_state.gc_ref
    if gc is not None and getattr(gc, "hive_sync_worker", None) is not None:
        gc.hive_sync_worker.reload()
    return status


def _load_hive_primary_id() -> str | None:
    config = local_state.get_hive_config() or {}
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
        "telemetry_fields": telemetryFieldList(),
        "targets": [
            {
                "id": target["id"],
                "name": target.get("name") or target.get("url"),
                "url": target.get("url", ""),
                "machine_id": target.get("machine_id"),
                "api_token_masked": _mask_hive_token(target.get("api_token")),
                "enabled": bool(target.get("enabled", False)),
                "is_primary": target["id"] == primary_target_id,
                "telemetry": getTargetTelemetrySettings(target["id"]),
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
    if existing and isinstance(existing.get("telemetry"), dict):
        next_target["telemetry"] = existing["telemetry"]

    if existing is None:
        targets.append(next_target)
    else:
        targets = [next_target if target.get("id") == target_id else target for target in targets]

    _save_hive_targets(targets)
    _reloadHiveConsumers()
    return {"ok": True, "message": "Hive target saved.", "target_id": target_id}


@router.delete("/api/settings/hive")
def clear_hive_config(target_id: str | None = Query(default=None)) -> Dict[str, Any]:
    if not target_id:
        _save_hive_targets([])
        _reloadHiveConsumers()
        return {"ok": True, "message": "All Hive targets removed."}

    targets = _load_hive_targets()
    next_targets = [target for target in targets if target.get("id") != target_id]
    if len(next_targets) == len(targets):
        raise HTTPException(404, "Hive target not found.")

    _save_hive_targets(next_targets)
    _reloadHiveConsumers()
    return {"ok": True, "message": "Hive target removed."}


class HiveTelemetryPayload(BaseModel):
    target_id: str
    fields: Dict[str, bool] = {}
    reset: bool = False


@router.post("/api/settings/hive/telemetry")
def save_hive_telemetry(payload: HiveTelemetryPayload) -> Dict[str, Any]:
    try:
        if payload.reset:
            settings = resetTargetTelemetrySettings(payload.target_id)
        else:
            settings = setTargetTelemetrySettings(payload.target_id, payload.fields)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "target_id": payload.target_id, "telemetry": settings}


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
    _save_hive_targets(targets)
    _reloadHiveConsumers()
    start_first_default_profile_if_none()
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
    _save_hive_targets(targets)
    _reloadHiveConsumers()
    start_first_default_profile_if_none()
    return {
        "ok": True,
        "target_id": target_id,
        "target_name": target_name,
        "machine_id": str(payload.machine_id),
        "machine_name": payload.machine_name,
        "token_prefix": payload.token_prefix or api_token[:8],
    }


@router.get("/api/settings/hive/suggested-machine-name")
def hive_suggested_machine_name(roll: bool = False) -> Dict[str, Any]:
    """The name to hand Hive when the user has not typed one on the link page.

    A sorter usually already has an identity: the nickname from setup, or the
    words in the Tailscale device name it picked at firstboot. Reuse that so the
    same machine reads the same everywhere, and only roll a fresh name when
    there is nothing to reuse — anything is better than every machine in every
    fleet arriving as "Lego Sorter".

    ``roll=1`` skips straight to a fresh name: that is someone pressing the
    shuffle button because they want a different one, and handing back the name
    they are trying to get away from would make the button look broken.
    """
    if roll:
        return {"ok": True, "name": random_display_name(), "source": "generated"}

    nickname = (getMachineNickname() or "").strip()
    if nickname:
        return {"ok": True, "name": nickname, "source": "nickname"}

    from_hostname = display_name_from_hostname(current_hostname())
    if from_hostname:
        return {"ok": True, "name": from_hostname, "source": "tailscale"}

    return {"ok": True, "name": random_display_name(), "source": "generated"}


@router.post("/api/settings/hive/backfill")
def hive_backfill(payload: HiveBackfillPayload = HiveBackfillPayload()) -> Dict[str, Any]:
    return getClassificationTrainingManager().backfillToHive(
        session_ids=payload.session_ids,
        target_ids=payload.target_ids,
    )


@router.post("/api/settings/hive/purge")
def hive_purge(payload: HivePurgePayload = HivePurgePayload()) -> Dict[str, Any]:
    return getClassificationTrainingManager().purgeHiveQueue(target_ids=payload.target_ids)


# Feeder detection config


@router.get("/api/feeder/detection-config")
def get_feeder_detection_config(role: str | None = Query(default=None)) -> Dict[str, Any]:
    role = _normalize_feeder_role(role)
    saved = getDetectionConfig("feeder") or {}
    algorithm_by_role = _feeder_algorithm_by_role_from_config(saved)
    algorithm = (
        algorithm_by_role[role]
        if role is not None
        else _normalize_feeder_detection_algorithm(saved.get("algorithm"))
    )
    return {
        "ok": True,
        "role": role,
        "algorithm": algorithm,
        "algorithm_by_role": algorithm_by_role,
        "available_algorithms": detection_algorithm_options("feeder"),
    }


@router.post("/api/feeder/detection-config")
def save_feeder_detection_config(
    payload: DetectionConfigPayload,
    role: str | None = Query(default=None),
) -> Dict[str, Any]:
    role = _normalize_feeder_role(role)
    if not scope_supports_detection_algorithm("feeder", payload.algorithm):
        raise HTTPException(status_code=400, detail="Unsupported feeder detection algorithm.")
    saved = getDetectionConfig("feeder") or {}
    current = saved.get("algorithm_by_role")
    algorithm_by_role = dict(current) if isinstance(current, dict) else {}
    if role is not None:
        algorithm_by_role[role] = payload.algorithm
    else:
        algorithm_by_role = {channel_role: payload.algorithm for channel_role in FEEDER_DETECTION_ROLES}
        saved["algorithm"] = payload.algorithm
    saved["algorithm_by_role"] = algorithm_by_role
    setDetectionConfig("feeder", saved)
    _reconcilePerception()
    return get_feeder_detection_config(role)


# Carousel detection config


@router.get("/api/carousel/detection-config")
def get_carousel_detection_config() -> Dict[str, Any]:
    saved = getDetectionConfig("carousel") or {}
    return {
        "ok": True,
        "algorithm": _normalize_carousel_detection_algorithm(saved.get("algorithm")),
        "available_algorithms": detection_algorithm_options("carousel"),
    }


@router.post("/api/carousel/detection-config")
def save_carousel_detection_config(payload: DetectionConfigPayload) -> Dict[str, Any]:
    if not scope_supports_detection_algorithm("carousel", payload.algorithm):
        raise HTTPException(status_code=400, detail="Unsupported carousel detection algorithm.")
    saved = getDetectionConfig("carousel") or {}
    saved["algorithm"] = payload.algorithm
    setDetectionConfig("carousel", saved)
    _reconcilePerception()
    return get_carousel_detection_config()


def _reconcilePerception() -> None:
    perception = getattr(shared_state.gc_ref, "perception_service", None)
    if perception is not None:
        perception.request_reconcile()


# Detection debug/test endpoints


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


@router.post("/api/classification-channel/sector-occupancy")
def classification_channel_sector_occupancy(
    include_lines: bool = False,
) -> Dict[str, Any]:
    perception = getattr(shared_state.gc_ref, "perception_service", None)
    if perception is None:
        raise HTTPException(status_code=503, detail="Perception service not available.")
    completed = perception.read_bboxes_and_frame(4)
    if completed is None:
        raise HTTPException(status_code=503, detail="No completed classification-channel inference available.")
    candidate_bboxes, frame = completed

    from vision.c4_wall_phase import detect_c4_wall_phase
    from subsystems.classification_channel.five_sector_platter import (
        C4FiveSectorPlatter,
        C4SectorDetection,
    )

    phase = detect_c4_wall_phase(frame.bgr)
    irl_config = _active_irl_config()
    platter = C4FiveSectorPlatter.from_irl_config(irl_config)
    phase_offset = phase.sector_offset_deg if phase.sector_offset_deg is not None else 0.0

    if phase.center_x is None or phase.center_y is None:
        return {
            "ok": False,
            "message": phase.message,
            "frame_luma": _frame_luma_payload(frame.bgr),
            "wall_phase": phase.as_dict(include_lines=include_lines),
            "sectors": [],
            "candidate_bboxes": [],
            "detections": [],
        }

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
        "frame_resolution": [int(frame.bgr.shape[1]), int(frame.bgr.shape[0])],
        "frame_luma": _frame_luma_payload(frame.bgr),
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


# Sample storage management


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
