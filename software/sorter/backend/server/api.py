from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import json
import os
import re
from pathlib import Path

from defs.events import (
    IdentityEvent,
    MachineIdentityData,
    KnownObjectData,
    KnownObjectEvent,
)
from blob_manager import (
    BLOB_DIR,
    PIECE_CROPS_DIR_NAME,
    PIECE_CROP_KINDS,
    getApiKeys,
    getMachineId,
    getMachineNickname,
    getRecentKnownObjects,
    getSortingProfileSyncState,
    setMachineNickname,
)
from local_state import (
    build_piece_detail_payload,
    get_piece_dossier,
    get_piece_dossier_by_tracked_global_id,
    get_piece_segment_counts,
    list_piece_dossiers,
)
from run_recorder import RECORDS_DIR
from server.camera_discovery import shutdownCameraDiscovery
from server.set_progress_sync import getSetProgressSyncWorker
from server.services import runtime_stats as runtime_stats_service
from server.waveshare_inventory import get_waveshare_inventory_manager
from server.security import compute_allowed_ui_origins, websocket_connection_allowed

from server.shared_state import (
    active_connections,
    broadcastEvent,
    setGlobalConfig,
    setCommandQueue,
    setArucoManager,
)
import server.shared_state as shared_state

# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

app = FastAPI(title="Sorter API", version="0.0.1")


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
#
# The Sorter API exposes privileged endpoints (system reset, supervisor
# restart, calibration, camera control). Keep it locked down by default:
# binds only to loopback and only accepts UI origins on loopback.
#
# Override knobs (for LAN exposure; see also SORTER_API_HOST in main.py):
#   SORTER_API_HOST            bind address (used here just to widen CORS)
#   SORTER_UI_PORT             UI dev/preview port (default 5173)
#   SORTER_API_ALLOWED_ORIGINS comma-separated full origins override
#                              (e.g. "https://sorter.lan,http://192.168.1.42:5173")
#
app.add_middleware(
    CORSMiddleware,
    allow_origins=compute_allowed_ui_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method != "GET":
            if shared_state.gc_ref is not None:
                shared_state.gc_ref.logger.info(f"[API] {request.method} {request.url.path}")
        response: Response = await call_next(request)
        return response

app.add_middleware(RequestLoggingMiddleware)

def _load_saved_api_keys_into_environment() -> None:
    saved_api_keys = getApiKeys()
    if saved_api_keys.get("openrouter"):
        os.environ["OPENROUTER_API_KEY"] = saved_api_keys["openrouter"]

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------

from server.routers.hardware import router as hardware_router
from server.routers.steppers import router as steppers_router
from server.routers.cameras import router as cameras_router
from server.routers.detection import router as detection_router
from server.routers.aruco import router as aruco_router
from server.routers.sorting_profiles import router as sorting_profiles_router
from server.routers.system import router as system_router
from server.routers.setup import router as setup_router
from server.routers.logs import router as logs_router
from server.routers.hive_models import router as hive_models_router
from server.routers.runtimes import router as runtimes_router
from server.routers.rt_runtime import router as rt_runtime_router

app.include_router(hardware_router)
app.include_router(steppers_router)
app.include_router(cameras_router)
app.include_router(detection_router)
app.include_router(aruco_router)
app.include_router(sorting_profiles_router)
app.include_router(system_router)
app.include_router(setup_router)
app.include_router(logs_router)
app.include_router(hive_models_router)
app.include_router(runtimes_router)
app.include_router(rt_runtime_router)

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def onStartup() -> None:
    _load_saved_api_keys_into_environment()
    shared_state.server_loop = asyncio.get_running_loop()
    getSetProgressSyncWorker().start()
    get_waveshare_inventory_manager().start()


@app.on_event("shutdown")
async def onShutdown() -> None:
    getSetProgressSyncWorker().stop()
    shutdownCameraDiscovery()
    get_waveshare_inventory_manager().stop()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


# ---------------------------------------------------------------------------
# Machine identity
# ---------------------------------------------------------------------------


class MachineIdentityUpdateRequest(BaseModel):
    nickname: Optional[str] = None


def _getMachineIdentityData() -> MachineIdentityData:
    machine_id = shared_state.gc_ref.machine_id if shared_state.gc_ref is not None else getMachineId()
    return MachineIdentityData(
        machine_id=machine_id,
        nickname=getMachineNickname(),
    )


def _broadcastIdentityUpdate() -> None:
    if shared_state.server_loop is None:
        return

    identity_event = IdentityEvent(tag="identity", data=_getMachineIdentityData())
    future = asyncio.run_coroutine_threadsafe(
        broadcastEvent(identity_event.model_dump()),
        shared_state.server_loop,
    )
    try:
        future.result(timeout=1.0)
    except Exception:
        pass


@app.get("/api/machine-identity", response_model=MachineIdentityData)
def get_machine_identity() -> MachineIdentityData:
    return _getMachineIdentityData()


@app.post("/api/machine-identity", response_model=MachineIdentityData)
def save_machine_identity(payload: MachineIdentityUpdateRequest) -> MachineIdentityData:
    setMachineNickname(payload.nickname)
    identity = _getMachineIdentityData()
    _broadcastIdentityUpdate()
    return identity


# ---------------------------------------------------------------------------
# UI theme color
# ---------------------------------------------------------------------------


_DEFAULT_UI_THEME_COLOR_ID = "blue"


class UiThemeResponse(BaseModel):
    color_id: str


class UiThemeUpdateRequest(BaseModel):
    color_id: str


@app.get("/api/settings/theme", response_model=UiThemeResponse)
def get_ui_theme() -> UiThemeResponse:
    from local_state import get_ui_theme_color_id

    return UiThemeResponse(color_id=get_ui_theme_color_id() or _DEFAULT_UI_THEME_COLOR_ID)


@app.post("/api/settings/theme", response_model=UiThemeResponse)
def save_ui_theme(payload: UiThemeUpdateRequest) -> UiThemeResponse:
    from local_state import set_ui_theme_color_id, get_ui_theme_color_id

    color_id = (payload.color_id or "").strip()
    if not color_id:
        raise HTTPException(status_code=400, detail="color_id must be a non-empty string")
    set_ui_theme_color_id(color_id)
    return UiThemeResponse(color_id=get_ui_theme_color_id() or _DEFAULT_UI_THEME_COLOR_ID)


# ---------------------------------------------------------------------------
# Sorting profile metadata
# ---------------------------------------------------------------------------


class SortingProfileCategoryMeta(BaseModel):
    name: str


class SortingProfileFallbackMode(BaseModel):
    rebrickable_categories: bool
    bricklink_categories: bool = False
    by_color: bool


class SortingProfileMetadataResponse(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    default_category_id: str
    categories: Dict[str, SortingProfileCategoryMeta]
    rules: List[Dict[str, Any]]
    fallback_mode: SortingProfileFallbackMode
    sync_state: Dict[str, Any] | None = None


class SortingProfileSetViewPart(BaseModel):
    part_num: str
    color_id: str
    part_name: str | None = None
    color_name: str | None = None
    quantity_needed: int
    quantity_found: int
    img_url: str | None = None
    manual_override_count: int | None = None
    user_state: str = "auto"


class SortingProfileSetViewResponse(BaseModel):
    category_id: str
    set_num: str
    name: str
    img_url: str | None = None
    year: int | None = None
    num_parts: int | None = None
    total_needed: int
    total_found: int
    pct: float
    parts: List[SortingProfileSetViewPart]


class SortingProfileSetViewPartStateUpdate(BaseModel):
    part_num: str
    color_id: str
    manual_override_count: int | None = None
    user_state: str = "auto"


class SortingProfileSetViewPartStateResponse(BaseModel):
    part_num: str
    color_id: str
    manual_override_count: int | None = None
    user_state: str = "auto"


@app.get("/sorting-profile/metadata", response_model=SortingProfileMetadataResponse)
def getSortingProfileMetadata() -> SortingProfileMetadataResponse:
    if shared_state.gc_ref is None:
        raise HTTPException(status_code=500, detail="Global config not initialized")
    with open(shared_state.gc_ref.sorting_profile_path, "r") as f:
        data = json.load(f)
    return SortingProfileMetadataResponse(
        id=data.get("id", ""),
        name=data.get("name", os.path.basename(shared_state.gc_ref.sorting_profile_path)),
        description=data.get("description", ""),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
        default_category_id=data.get("default_category_id", "misc"),
        categories={
            k: SortingProfileCategoryMeta(**v)
            for k, v in data.get("categories", {}).items()
        },
        rules=data.get("rules", []),
        fallback_mode=SortingProfileFallbackMode(
            **data.get(
                "fallback_mode",
                {"rebrickable_categories": False, "bricklink_categories": False, "by_color": False},
            )
        ),
        sync_state=getSortingProfileSyncState(),
    )


@app.get("/sorting-profile/set-view/{category_id}", response_model=SortingProfileSetViewResponse)
def getSortingProfileSetView(category_id: str) -> SortingProfileSetViewResponse:
    if shared_state.gc_ref is None:
        raise HTTPException(status_code=500, detail="Global config not initialized")

    with open(shared_state.gc_ref.sorting_profile_path, "r") as f:
        raw_profile = json.load(f)
    set_inventories = raw_profile.get("set_inventories") if isinstance(raw_profile, dict) else None
    if not isinstance(set_inventories, dict):
        raise HTTPException(status_code=404, detail="No set inventory data available")

    inventory = set_inventories.get(category_id)
    if not isinstance(inventory, dict):
        raise HTTPException(status_code=404, detail="Set category not found")

    parts = inventory.get("parts") if isinstance(inventory.get("parts"), list) else []
    artifact_hash = str(raw_profile.get("artifact_hash") or "") if isinstance(raw_profile, dict) else ""
    found_lookup: dict[tuple[str, str], int] = {}
    total_found = 0

    if artifact_hash:
        try:
            from set_progress import SetProgressTracker

            tracker = SetProgressTracker(set_inventories, artifact_hash)
            progress = tracker.get_progress()
            for set_info in progress.get("sets", []):
                if str(set_info.get("id")) != category_id:
                    continue
                total_found = int(set_info.get("total_found") or 0)
                for part in set_info.get("parts", []):
                    key = (str(part.get("part_num") or ""), str(part.get("color_id") or ""))
                    found_lookup[key] = int(part.get("quantity_found") or 0)
                break
        except Exception:
            pass

    total_needed = sum(int(part.get("quantity") or 0) for part in parts if isinstance(part, dict))
    pct = (total_found / total_needed * 100) if total_needed > 0 else 0.0

    from local_state import get_checklist_state_for_set

    resolved_set_num = str(inventory.get("set_num") or category_id)
    checklist_state = get_checklist_state_for_set(resolved_set_num)

    response_parts: List[SortingProfileSetViewPart] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        part_num = str(part.get("part_num") or "")
        color_id = str(part.get("color_id") or "")
        state_entry = checklist_state.get((part_num, color_id)) or {}
        response_parts.append(
            SortingProfileSetViewPart(
                part_num=part_num,
                color_id=color_id,
                part_name=part.get("part_name"),
                color_name=part.get("color_name"),
                quantity_needed=int(part.get("quantity") or 0),
                quantity_found=found_lookup.get((part_num, color_id), 0),
                img_url=part.get("img_url"),
                manual_override_count=state_entry.get("manual_override_count"),
                user_state=state_entry.get("user_state") or "auto",
            )
        )

    return SortingProfileSetViewResponse(
        category_id=category_id,
        set_num=resolved_set_num,
        name=str(inventory.get("name") or category_id),
        img_url=inventory.get("img_url"),
        year=inventory.get("year"),
        num_parts=inventory.get("num_parts"),
        total_needed=total_needed,
        total_found=total_found,
        pct=round(pct, 1),
        parts=response_parts,
    )


@app.post(
    "/sorting-profile/set-view/{category_id}/part/state",
    response_model=SortingProfileSetViewPartStateResponse,
)
def updateSortingProfileSetViewPartState(
    category_id: str,
    payload: SortingProfileSetViewPartStateUpdate,
) -> SortingProfileSetViewPartStateResponse:
    if shared_state.gc_ref is None:
        raise HTTPException(status_code=500, detail="Global config not initialized")

    with open(shared_state.gc_ref.sorting_profile_path, "r") as f:
        raw_profile = json.load(f)
    set_inventories = raw_profile.get("set_inventories") if isinstance(raw_profile, dict) else None
    if not isinstance(set_inventories, dict):
        raise HTTPException(status_code=404, detail="No set inventory data available")

    inventory = set_inventories.get(category_id)
    if not isinstance(inventory, dict):
        raise HTTPException(status_code=404, detail="Set category not found")

    set_num = str(inventory.get("set_num") or category_id)

    from local_state import set_checklist_part_state

    try:
        result = set_checklist_part_state(
            set_num,
            payload.part_num,
            payload.color_id,
            manual_override_count=payload.manual_override_count,
            user_state=payload.user_state,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return SortingProfileSetViewPartStateResponse(
        part_num=payload.part_num,
        color_id=payload.color_id,
        manual_override_count=result.get("manual_override_count"),
        user_state=result.get("user_state") or "auto",
    )


# ---------------------------------------------------------------------------
# Known-object lookup by uuid
# ---------------------------------------------------------------------------
#
# The WS recent-objects ring and frontend `recentObjects` buffer are both
# intentionally tiny (10 entries) — they're for the gallery, not for
# persistence. The detail page at ``/tracked/<uuid>`` needs to render a
# piece even after it's aged out of that ring, so this endpoint resolves
# from the persistent local SQLite dossier first and only falls back to the
# in-process runtime-stats LRU if needed.


def _normalize_deg(value: float) -> float:
    normalized = float(value) % 360.0
    if normalized < 0.0:
        normalized += 360.0
    return normalized


def _circular_diff_deg(a: float, b: float) -> float:
    return (_normalize_deg(a) - _normalize_deg(b) + 540.0) % 360.0 - 180.0


def _current_classification_drop_angle_deg() -> float | None:
    # Read the drop angle from the live IRL config (bootstrap plumbs it into
    # hardware_runtime_irl once homing has run). No legacy coordinator needed.
    irl = shared_state.getActiveIRL()
    irl_config = getattr(irl, "irl_config", None) if irl is not None else None
    cc_cfg = getattr(irl_config, "classification_channel_config", None)
    value = getattr(cc_cfg, "drop_angle_deg", None)
    return float(value) if isinstance(value, (int, float)) else None


def _tracked_history_summary_map(limit: int) -> dict[int, dict[str, Any]]:
    # Post-cutover: the legacy VisionManager-based track history is gone.
    # rt/ persists piece dossiers directly via local_state, so the gallery
    # already has what it needs from the DB dossier payload. Return empty
    # to preserve the call shape.
    return {}


def _piece_dossier_with_track_detail(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """DB-first detail enrichment for ``GET /api/tracked/pieces/{uuid}``.

    Post-cutover the "live tracker" layer is gone: rt/ publishes every
    piece_registered/classified/distributed event straight into the local
    dossier table, so the DB payload IS the detail payload. Returning it
    unchanged (with ``track_detail`` left as whatever the caller produced)
    keeps the endpoint shape stable.
    """
    if not isinstance(payload, dict):
        return None
    return dict(payload)


@app.get("/api/tracked/pieces")
def get_tracked_pieces(
    limit: int = 120,
    include_stubs: bool = False,
) -> Dict[str, Any]:
    limit = max(10, min(int(limit), 500))
    load_limit = max(limit * 4, 500)
    dossiers = list_piece_dossiers(limit=load_limit, include_stubs=include_stubs)
    history_by_gid = _tracked_history_summary_map(load_limit)
    drop_angle_deg = _current_classification_drop_angle_deg()

    # Bulk segment-count lookup: one SELECT instead of N+1 calls to
    # list_piece_segments per row. Key'd by piece_uuid, default 0.
    dossier_uuids = [
        str(piece.get("uuid"))
        for piece in dossiers
        if isinstance(piece, dict) and isinstance(piece.get("uuid"), str)
    ]
    segment_counts = get_piece_segment_counts(piece_uuids=dossier_uuids)

    rows: list[dict[str, Any]] = []
    for piece in dossiers:
        if not isinstance(piece, dict):
            continue
        tracked_global_id = piece.get("tracked_global_id")
        if not isinstance(tracked_global_id, int):
            tracked_global_id = None
        history = history_by_gid.get(tracked_global_id) if tracked_global_id is not None else None
        live = bool(history.get("live")) if isinstance(history, dict) else False
        stage = str(piece.get("stage") or "created")
        distributed_at = piece.get("distributed_at")
        is_distributed = stage == "distributed" or isinstance(distributed_at, (int, float))
        is_active = not is_distributed
        zone_center_deg = piece.get("classification_channel_zone_center_deg")
        zone_center_deg = float(zone_center_deg) if isinstance(zone_center_deg, (int, float)) else None
        polar_offset_deg = (
            _circular_diff_deg(zone_center_deg, drop_angle_deg)
            if zone_center_deg is not None and drop_angle_deg is not None
            else None
        )
        sort_ts = piece.get("distributed_at")
        if not isinstance(sort_ts, (int, float)):
            sort_ts = piece.get("updated_at")
        if not isinstance(sort_ts, (int, float)) and isinstance(history, dict):
            sort_ts = history.get("finished_at")
        if not isinstance(sort_ts, (int, float)):
            sort_ts = piece.get("created_at")
        piece_uuid = piece.get("uuid")
        has_track_segments = bool(
            isinstance(piece_uuid, str)
            and segment_counts.get(piece_uuid, 0) > 0
        )
        rows.append(
            {
                "uuid": piece_uuid,
                "piece": piece,
                "tracked_global_id": tracked_global_id,
                "global_id": tracked_global_id,
                "live": live or is_active,
                "active": is_active,
                "polar_angle_deg": zone_center_deg,
                "polar_offset_deg": polar_offset_deg,
                "created_at": piece.get("created_at"),
                "updated_at": piece.get("updated_at"),
                "stage": piece.get("stage"),
                "classification_status": piece.get("classification_status"),
                "track_summary": history,
                "has_track_segments": has_track_segments,
                "sort_ts": float(sort_ts) if isinstance(sort_ts, (int, float)) else 0.0,
                "history_finished_at": history.get("finished_at") if isinstance(history, dict) else None,
            }
        )

    active_rows = [row for row in rows if row["active"]]
    historical_rows = [row for row in rows if not row["active"]]

    active_rows.sort(
        key=lambda row: (
            row["polar_offset_deg"] is None,
            -(float(row["polar_offset_deg"]) if isinstance(row["polar_offset_deg"], (int, float)) else -9999.0),
            -float(row["sort_ts"]),
        )
    )
    historical_rows.sort(key=lambda row: -float(row["sort_ts"]))
    ordered = active_rows + historical_rows
    return {"items": ordered[:limit], "drop_angle_deg": drop_angle_deg}


@app.get("/api/known-objects/{uuid}", response_model=KnownObjectData)
def get_known_object_by_uuid(uuid: str) -> KnownObjectData:
    payload = get_piece_dossier(uuid)
    if payload is None:
        try:
            payload = get_piece_dossier_by_tracked_global_id(int(uuid))
        except Exception:
            payload = None
    if payload is None:
        payload = runtime_stats_service.lookup_known_object(uuid)
    if payload is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        return KnownObjectData.model_validate(payload)
    except Exception:
        raise HTTPException(status_code=404, detail="not found")


@app.get("/api/tracked/pieces/{uuid}")
def get_tracked_piece_detail(uuid: str) -> Dict[str, Any]:
    # Phase 5: DB-first. Build the merged dossier+segments payload from
    # SQLite so detail pages survive restarts, then fold live-tracker detail
    # on top when the piece is still active. 404 is reserved for pieces
    # that are unknown to BOTH the DB and the runtime LRU — otherwise the
    # frontend used to see a spurious "Track Not Found" for pieces that
    # had simply aged out of the live buffer.
    payload = build_piece_detail_payload(uuid)
    if payload is None:
        # Legacy-compat: if ``uuid`` is numeric, it was likely a raw
        # ``tracked_global_id``. Resolve via the DB before giving up.
        try:
            legacy = get_piece_dossier_by_tracked_global_id(int(uuid))
        except Exception:
            legacy = None
        if legacy is not None:
            payload = build_piece_detail_payload(str(legacy.get("uuid") or ""))
            if payload is None:
                payload = legacy
    if payload is None:
        # Last resort: the in-process runtime-stats LRU. No segments here —
        # just the bare dossier dict kept for the gallery ring.
        payload = runtime_stats_service.lookup_known_object(uuid)
    enriched = _piece_dossier_with_track_detail(payload)
    if enriched is None:
        raise HTTPException(status_code=404, detail="not found")
    return enriched


# ---------------------------------------------------------------------------
# Piece crop archive — Phase 3
# ---------------------------------------------------------------------------

# UUIDs (proper + stub) use [-A-Za-z0-9_]; be liberal but reject any path
# separator so ``piece_uuid`` can never escape the blob root.
_PIECE_UUID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


@app.get("/api/piece-crops/{piece_uuid}/seg{sequence}/{kind}/{idx}.jpg")
def get_piece_crop_jpeg(
    piece_uuid: str,
    sequence: int,
    kind: str,
    idx: int,
) -> FileResponse:
    """Serve a piece-segment crop JPEG written by ``blob_manager.write_piece_crop``.

    Path-traversal guard: ``piece_uuid`` must match ``_PIECE_UUID_RE`` and
    ``kind`` must be one of :data:`PIECE_CROP_KINDS`. The resolved path is
    additionally forced to live under ``BLOB_DIR/piece_crops`` — anything
    outside yields 404. Content-addressed, so the long ``immutable``
    cache header is safe.
    """
    if not _PIECE_UUID_RE.match(piece_uuid or ""):
        raise HTTPException(status_code=404, detail="not found")
    if kind not in PIECE_CROP_KINDS:
        raise HTTPException(status_code=404, detail="not found")
    try:
        sequence_int = int(sequence)
        idx_int = int(idx)
    except (TypeError, ValueError):
        raise HTTPException(status_code=404, detail="not found")
    if sequence_int < 0 or idx_int < 0:
        raise HTTPException(status_code=404, detail="not found")

    filename = f"{kind}_{idx_int:03d}.jpg"
    candidate = (
        BLOB_DIR
        / PIECE_CROPS_DIR_NAME
        / piece_uuid
        / f"seg{sequence_int}"
        / filename
    )
    try:
        resolved = candidate.resolve()
        allowed_root = (BLOB_DIR / PIECE_CROPS_DIR_NAME).resolve()
    except Exception:
        raise HTTPException(status_code=404, detail="not found")
    if not str(resolved).startswith(str(allowed_root)):
        raise HTTPException(status_code=404, detail="not found")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(
        path=str(resolved),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    client_host = websocket.client.host if websocket.client is not None else None
    if not websocket_connection_allowed(
        websocket.headers.get("Origin"),
        client_host,
        compute_allowed_ui_origins(),
    ):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="WebSocket origin not allowed.",
        )
        return

    await websocket.accept()
    active_connections.append(websocket)

    identity_event = IdentityEvent(tag="identity", data=_getMachineIdentityData())
    await websocket.send_json(identity_event.model_dump())
    for item in reversed(getRecentKnownObjects()):
        try:
            event = KnownObjectEvent(
                tag="known_object",
                data=KnownObjectData.model_validate(item),
            )
        except Exception:
            continue
        await websocket.send_json(event.model_dump())
    if shared_state.runtime_stats_snapshot is not None:
        await websocket.send_json(
            {
                "tag": "runtime_stats",
                "data": {"payload": shared_state.runtime_stats_snapshot},
            }
        )

    # Always send a fresh system_status snapshot on connect (cheap + always valid).
    await websocket.send_json(
        {
            "tag": "system_status",
            "data": {
                "hardware_state": shared_state.hardware_state,
                "hardware_error": shared_state.hardware_error,
                "homing_step": shared_state.hardware_homing_step,
            },
        }
    )
    # Populate sorter_state snapshot on-demand if missing. Post-cutover the
    # legacy FSM is gone; the rt_handle reports its own lifecycle directly.
    if shared_state.sorter_state_snapshot is None:
        rt = shared_state.rt_handle
        if rt is None:
            fsm_state = "initializing"
        elif getattr(rt, "paused", False):
            fsm_state = "paused"
        elif getattr(rt, "started", False):
            fsm_state = "running"
        else:
            fsm_state = "initializing"
        irl = shared_state.getActiveIRL()
        irl_config = getattr(irl, "irl_config", None) if irl is not None else None
        layout = getattr(irl_config, "camera_layout", None) if irl_config is not None else None
        shared_state.sorter_state_snapshot = {
            "state": fsm_state,
            "camera_layout": layout,
        }
    await websocket.send_json(
        {
            "tag": "sorter_state",
            "data": shared_state.sorter_state_snapshot,
        }
    )

    # Populate cameras_config snapshot on-demand from the live config file.
    if shared_state.cameras_config_snapshot is None:
        try:
            from server.routers.cameras import get_camera_config
            shared_state.cameras_config_snapshot = {"cameras": get_camera_config()}
        except Exception:
            shared_state.cameras_config_snapshot = None
    if shared_state.cameras_config_snapshot is not None:
        await websocket.send_json(
            {
                "tag": "cameras_config",
                "data": shared_state.cameras_config_snapshot,
            }
        )
    # Always compute fresh sorting profile status on connect — cheap file read,
    # keeps frontend in sync without depending on mutation-time broadcasts.
    try:
        from server.routers.sorting_profiles import _current_local_profile_status
        await websocket.send_json(
            {
                "tag": "sorting_profile_status",
                "data": _current_local_profile_status(),
            }
        )
    except Exception:
        pass

    tracker = getattr(shared_state.gc_ref, 'set_progress_tracker', None) if shared_state.gc_ref else None
    if tracker is not None:
        await websocket.send_json(
            {
                "tag": "set_progress",
                "data": tracker.get_snapshot(),
            }
        )

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


# ---------------------------------------------------------------------------
# Camera preview WebSocket
# ---------------------------------------------------------------------------
#
# WebSocket fan-out for the settings-modal camera picker. Each tile in the
# grid opens one WS connection against a single shared broadcaster thread
# per device, and we never open a duplicate ``cv2.VideoCapture`` for devices
# that vision manager already owns.
#
# Not to be confused with the main ``/ws`` control websocket above.


@app.websocket("/ws/camera-preview/{index}")
async def camera_preview_ws(websocket: WebSocket, index: int) -> None:
    client_host = websocket.client.host if websocket.client is not None else None
    if not websocket_connection_allowed(
        websocket.headers.get("Origin"),
        client_host,
        compute_allowed_ui_origins(),
    ):
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="WebSocket origin not allowed.",
        )
        return

    await websocket.accept()

    from server.camera_preview_hub import get_camera_preview_hub

    loop = asyncio.get_running_loop()
    hub = get_camera_preview_hub()
    queue = hub.subscribe(index, loop=loop)

    try:
        while True:
            frame = await queue.get()
            await websocket.send_bytes(frame)
    except WebSocketDisconnect:
        pass
    except Exception:
        # Keep cleanup deterministic even on unexpected errors.
        pass
    finally:
        hub.unsubscribe(index, queue)


# ---------------------------------------------------------------------------
# Runtime stats
# ---------------------------------------------------------------------------


class RuntimeStatsResponse(BaseModel):
    payload: Dict[str, Any]


class RuntimeStatsRecordItem(BaseModel):
    record_id: str
    run_id: str
    started_at: float
    ended_at: float
    total_pieces: int


class RuntimeStatsRecordsResponse(BaseModel):
    records: List[RuntimeStatsRecordItem]


@app.get("/runtime-stats", response_model=RuntimeStatsResponse)
def getRuntimeStats() -> RuntimeStatsResponse:
    if shared_state.runtime_stats_snapshot is None:
        return RuntimeStatsResponse(payload={})
    return RuntimeStatsResponse(payload=shared_state.runtime_stats_snapshot)


@app.get("/runtime-stats/records", response_model=RuntimeStatsRecordsResponse)
def listRuntimeStatsRecords() -> RuntimeStatsRecordsResponse:
    if not RECORDS_DIR.exists():
        return RuntimeStatsRecordsResponse(records=[])

    records: List[RuntimeStatsRecordItem] = []
    for path in sorted(RECORDS_DIR.glob("*.json"), reverse=True):
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception:
            continue
        runtime_stats = data.get("runtime_stats_final")
        if not isinstance(runtime_stats, dict):
            continue
        run_id = data.get("run_id")
        started_at = data.get("started_at")
        ended_at = data.get("ended_at")
        total_pieces = data.get("total_pieces")
        if not isinstance(run_id, str):
            continue
        if not isinstance(started_at, (int, float)):
            continue
        if not isinstance(ended_at, (int, float)):
            continue
        if not isinstance(total_pieces, int):
            continue
        records.append(
            RuntimeStatsRecordItem(
                record_id=path.name,
                run_id=run_id,
                started_at=float(started_at),
                ended_at=float(ended_at),
                total_pieces=total_pieces,
            )
        )
    return RuntimeStatsRecordsResponse(records=records)


@app.get("/runtime-stats/record/{record_id}", response_model=RuntimeStatsResponse)
def getRuntimeStatsRecord(record_id: str) -> RuntimeStatsResponse:
    safe_name = Path(record_id).name
    if safe_name != record_id:
        raise HTTPException(status_code=400, detail="Invalid record id")
    path = RECORDS_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Record not found")
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed reading record: {e}")
    runtime_stats = data.get("runtime_stats_final")
    if not isinstance(runtime_stats, dict):
        raise HTTPException(status_code=404, detail="runtime_stats_final missing")
    return RuntimeStatsResponse(payload=runtime_stats)


# ---------------------------------------------------------------------------
# Set Progress
# ---------------------------------------------------------------------------


class SetProgressResponse(BaseModel):
    is_set_based: bool
    progress: Dict[str, Any] | None = None


@app.get("/api/set-progress", response_model=SetProgressResponse)
def getSetProgress() -> SetProgressResponse:
    tracker = getattr(shared_state.gc_ref, 'set_progress_tracker', None) if shared_state.gc_ref else None
    if tracker is None:
        return SetProgressResponse(is_set_based=False)
    return SetProgressResponse(is_set_based=True, progress=tracker.get_progress())


# ---------------------------------------------------------------------------
# Polygon editor
# ---------------------------------------------------------------------------


@app.get("/api/polygons")
def get_polygons() -> Dict[str, Any]:
    """Load saved channel and classification polygons."""
    from blob_manager import getChannelPolygons, getClassificationPolygons
    result: Dict[str, Any] = {}
    channel = getChannelPolygons()
    if channel:
        result["channel"] = channel
    classification = getClassificationPolygons()
    if classification:
        result["classification"] = classification
    return result


def _rebuild_rt_perception_roles(*roles: str) -> dict[str, list[str]]:
    """Best-effort refresh of live rt perception runners after zone edits."""
    handle = shared_state.rt_handle
    if handle is None or not hasattr(handle, "rebuild_runner_for_role"):
        return {"attempted": [], "rebuilt": [], "failed": []}

    attempted: list[str] = []
    rebuilt: list[str] = []
    failed: list[str] = []
    for role in roles:
        attempted.append(role)
        try:
            runner = handle.rebuild_runner_for_role(role)
        except Exception:
            runner = None
        if runner is None:
            failed.append(role)
        else:
            rebuilt.append(role)
    return {
        "attempted": attempted,
        "rebuilt": rebuilt,
        "failed": failed,
    }


@app.post("/api/polygons")
def save_polygons(body: Dict[str, Any]) -> Dict[str, Any]:
    """Save channel and classification polygons and refresh rt perception."""
    from blob_manager import setChannelPolygons, setClassificationPolygons

    if "channel" in body:
        setChannelPolygons(body["channel"])
    if "classification" in body:
        setClassificationPolygons(body["classification"])

    rebuild = (
        _rebuild_rt_perception_roles("c2", "c3", "c4")
        if "channel" in body
        else {"attempted": [], "rebuilt": [], "failed": []}
    )
    return {
        "ok": True,
        "requires_restart": bool(rebuild["failed"]),
        "rt_rebuild_attempted_roles": rebuild["attempted"],
        "rt_rebuilt_roles": rebuild["rebuilt"],
        "rt_rebuild_failed_roles": rebuild["failed"],
    }
