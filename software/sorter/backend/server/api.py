from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import json
import os
import time
from pathlib import Path

from defs.events import (
    IdentityEvent,
    MachineIdentityData,
)
from blob_manager import (
    getApiKeys,
    getMachineId,
    getMachineNickname,
    getSortingProfileSyncState,
    setMachineNickname,
)
from runtime_variables import VARIABLE_DEFS
from server.camera_discovery import shutdownCameraDiscovery
from server.set_progress_sync import getSetProgressSyncWorker
from server.waveshare_inventory import get_waveshare_inventory_manager
from server.security import (
    is_ui_origin_allowed,
    websocket_connection_allowed,
)

from server.shared_state import (
    active_connections,
    broadcastEvent,
    setGlobalConfig,
    setRuntimeVariables,
    setCommandQueue,
    setController,
    setVisionManager,
    _getRuntimeVariables,
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
# Decide per-request, so the allowlist tracks this device's current IPs /
# hostname / Tailscale name without a restart. is_ui_origin_allowed accepts only
# this machine's own addresses (plus any SORTER_API_ALLOWED_ORIGINS override).
class _DeviceCORSMiddleware(CORSMiddleware):
    def is_allowed_origin(self, origin: str) -> bool:
        allowed = is_ui_origin_allowed(origin)
        if not allowed and shared_state.gc_ref is not None:
            from server.security import describe_origin_decision

            shared_state.gc_ref.logger.info(f"[CORS reject] {describe_origin_decision(origin)}")
        return allowed


app.add_middleware(
    _DeviceCORSMiddleware,
    allow_methods=["*"],
    allow_headers=["*"],
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Set SORTER_LOG_REQUESTS=1 to log EVERY request (including GETs, which are
# otherwise silent) with its Origin header and client address — needed to see
# whether a remote browser's calls are even reaching the backend.
_LOG_ALL_REQUESTS = os.environ.get("SORTER_LOG_REQUESTS", "").lower() in ("1", "true", "yes")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        gc = shared_state.gc_ref
        if _LOG_ALL_REQUESTS and gc is not None:
            client = request.client.host if request.client is not None else None
            gc.logger.info(
                f"[req] {request.method} {request.url.path} "
                f"origin={request.headers.get('origin')!r} client={client!r}"
            )
            response: Response = await call_next(request)
            gc.logger.info(f"[req] <- {response.status_code} {request.method} {request.url.path}")
            return response
        if request.method != "GET" and gc is not None:
            gc.logger.info(f"[API] {request.method} {request.url.path}")
        return await call_next(request)

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
from server.routers.sorting_profiles import router as sorting_profiles_router
from server.routers.bsx import router as bsx_router
from server.routers.bin_layouts import router as bin_layouts_router
from server.routers.system import router as system_router
from server.routers.setup import router as setup_router
from server.routers.logs import router as logs_router
from server.routers.hive_models import router as hive_models_router
from server.routers.pieces import router as pieces_router
from server.routers.runtimes import router as runtimes_router
from server.routers.chute_stress import router as chute_stress_router
from server.routers.tuning import router as tuning_router
from server.routers.telemetry import router as telemetry_router
from server.routers.tailscale import router as tailscale_router
from server.routers.wifi import router as wifi_router
from server.routers.firmware import router as firmware_router
from server.routers.versions import router as versions_router

app.include_router(hardware_router)
app.include_router(steppers_router)
app.include_router(cameras_router)
app.include_router(detection_router)
app.include_router(sorting_profiles_router)
app.include_router(bsx_router)
app.include_router(bin_layouts_router)
app.include_router(system_router)
app.include_router(setup_router)
app.include_router(logs_router)
app.include_router(hive_models_router)
app.include_router(pieces_router)
app.include_router(runtimes_router)
app.include_router(chute_stress_router)
app.include_router(tuning_router)
app.include_router(telemetry_router)
app.include_router(tailscale_router)
app.include_router(wifi_router)
app.include_router(firmware_router)
app.include_router(versions_router)

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


async def _loop_lag_probe() -> None:
    """Measure how late the uvicorn asyncio loop wakes a fixed-interval sleep.

    A high socket.loop_lag_ms means the event loop is blocked/starved (a sync
    call on the loop, GIL contention, MJPEG streaming) and CAN'T promptly run
    the websocket broadcast coroutines — which is the real frontend-latency
    lever. Near-zero lag with high client_send_ms instead means a slow client.
    """
    interval = 0.1
    while True:
        started = time.perf_counter()
        await asyncio.sleep(interval)
        lag_ms = (time.perf_counter() - started - interval) * 1000.0
        gc = shared_state.gc_ref
        if gc is not None and getattr(gc, "runtime_stats", None) is not None:
            gc.runtime_stats.observePerfMs("socket.loop_lag_ms", max(0.0, lag_ms))


@app.on_event("startup")
async def onStartup() -> None:
    _load_saved_api_keys_into_environment()
    shared_state.server_loop = asyncio.get_running_loop()
    asyncio.create_task(_loop_lag_probe())
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


def _loadSortingProfileRaw() -> dict | None:
    if shared_state.gc_ref is None:
        return None
    gc = shared_state.gc_ref
    path = gc.sorting_profile_path
    try:
        with open(path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        gc.logger.warn(f"sorting profile file not found: {path}")
        return None
    if not content.strip():
        gc.logger.warn(f"sorting profile file is empty: {path}")
        return None
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        gc.logger.warn(f"sorting profile file is corrupt ({e}): {path}")
        return None
    if not isinstance(data, dict):
        gc.logger.warn(f"sorting profile file is not a JSON object: {path}")
        return None
    return data


@app.get("/sorting-profile/metadata", response_model=SortingProfileMetadataResponse)
def getSortingProfileMetadata() -> SortingProfileMetadataResponse:
    if shared_state.gc_ref is None:
        raise HTTPException(status_code=500, detail="Global config not initialized")
    data = _loadSortingProfileRaw() or {}
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

    raw_profile = _loadSortingProfileRaw()
    if raw_profile is None:
        raise HTTPException(status_code=404, detail="No sorting profile loaded")
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

    raw_profile = _loadSortingProfileRaw()
    if raw_profile is None:
        raise HTTPException(status_code=404, detail="No sorting profile loaded")
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


# Durable piece-image index (piece_image_store): unlike the in-memory
# known-object lookup behind /api/pieces/{uuid}, these survive restarts and LRU eviction. Rows
# whose local file was evicted by retention report available_locally=False;
# once hive sync exists those will be re-fetchable from the Hive instead.
@app.get("/api/pieces/{uuid}/images")
def list_piece_images(uuid: str) -> Dict[str, Any]:
    import piece_image_store

    return {"piece_uuid": uuid, "images": piece_image_store.listPieceImages(uuid)}


@app.get("/api/pieces/{uuid}/images/{image_id}")
def get_piece_image(uuid: str, image_id: int) -> Any:
    from fastapi.responses import FileResponse

    import piece_image_store

    path = piece_image_store.getImageFile(uuid, image_id)
    if path is None:
        raise HTTPException(status_code=404, detail="image not available locally")
    # The bytes behind a given image id never change, so let the browser cache
    # them forever — repeat visits to /records render straight from its cache.
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.get("/api/piece-images/stats")
def get_piece_image_stats() -> Dict[str, Any]:
    import piece_image_store

    return piece_image_store.getStats()


class ClassifyRetryRequest(BaseModel):
    # base64 JPEGs (with or without a data: URI prefix). Order is preserved.
    images: List[str]


# Scratch / ephemeral re-classification. Runs a hand-picked subset of a piece's
# crops back through Brickognize for testing — it records NOTHING (no piece
# record, no run recorder, no dump), takes no piece_uuid, and has no effect on
# sorting. Purely for eyeballing how different image subsets classify.
@app.post("/api/classify/retry")
def classify_retry(req: ClassifyRetryRequest) -> Dict[str, Any]:
    import base64 as _b64
    import numpy as _np
    import cv2 as _cv2
    from classification.brickognize import MAX_QUERY_IMAGES, _classifyImages

    decoded: List[Any] = []
    for raw in req.images:
        if not isinstance(raw, str) or not raw:
            continue
        b64 = raw.split(",", 1)[1] if raw.startswith("data:") else raw
        try:
            buf = _np.frombuffer(_b64.b64decode(b64), dtype=_np.uint8)
            img = _cv2.imdecode(buf, _cv2.IMREAD_COLOR)
        except Exception:
            img = None
        if img is not None and img.size > 0:
            decoded.append(img)

    if not decoded:
        raise HTTPException(status_code=400, detail="no decodable images")
    if len(decoded) > MAX_QUERY_IMAGES:
        decoded = decoded[:MAX_QUERY_IMAGES]

    gc = shared_state.gc_ref
    try:
        # piece_uuid=None → no dump-to-disk; this call is intentionally untracked.
        result = _classifyImages(gc, decoded, piece_uuid=None)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"brickognize failed: {exc}")

    items = result.get("items", []) if isinstance(result, dict) else []
    colors = result.get("colors", []) if isinstance(result, dict) else []
    best_item = max(items, key=lambda i: i.get("score", 0)) if items else None
    best_color = max(colors, key=lambda c: c.get("score", 0)) if colors else None
    return {
        "n_images": len(decoded),
        "items": items,
        "colors": colors,
        "best_item": best_item,
        "best_color": best_color,
    }


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    client_host = websocket.client.host if websocket.client is not None else None
    if not websocket_connection_allowed(
        websocket.headers.get("Origin"),
        client_host,
    ):
        if shared_state.gc_ref is not None:
            from server.security import describe_origin_decision

            shared_state.gc_ref.logger.info(
                f"[WS reject] client_host={client_host!r} {describe_origin_decision(websocket.headers.get('Origin'))}"
            )
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="WebSocket origin not allowed.",
        )
        return

    await websocket.accept()
    active_connections.append(websocket)

    identity_event = IdentityEvent(tag="identity", data=_getMachineIdentityData())
    await websocket.send_json(identity_event.model_dump())
    # No known_object replay on connect — clients hydrate recent pieces via
    # GET /api/pieces instead of a sqlite-backed ring of past events.
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
                "no_power_development_mode": bool(
                    getattr(shared_state.gc_ref, "no_power_development_mode", False)
                ),
            },
        }
    )
    # Populate sorter_state snapshot on-demand if missing — broadcasts are only
    # fired at FSM transitions, so a freshly-connected client would otherwise
    # default to 'default' camera_layout even when the config says split_feeder.
    if shared_state.sorter_state_snapshot is None:
        layout = None
        if shared_state.vision_manager is not None:
            layout = getattr(shared_state.vision_manager, "_camera_layout", None)
        if layout is None:
            # No live vision manager (e.g. api_only / no-power dev): fall back to
            # the configured camera layout so the dashboard renders the right
            # variant rather than always assuming "default".
            try:
                from server.routers.cameras import get_camera_config

                layout = get_camera_config().get("layout")
            except Exception:
                layout = None
        fsm_state = "initializing"
        if shared_state.controller_ref is not None:
            fsm_state = getattr(shared_state.controller_ref.state, "value", "initializing")
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


class PerfHistoryResponse(BaseModel):
    window_s: float
    now: float
    rows: List[Dict[str, Any]]
    rates: Dict[str, Any]


@app.get("/runtime-stats/perf-history", response_model=PerfHistoryResponse)
def getPerfHistory(window_s: float = 300.0) -> PerfHistoryResponse:
    import time as _time
    from server import perf_history

    now = _time.time()
    window_s = max(1.0, min(float(window_s), 3900.0))
    rows = perf_history.window(window_s, now)
    return PerfHistoryResponse(
        window_s=window_s,
        now=now,
        rows=rows,
        rates=perf_history.computeRates(rows),
    )


@app.get("/runtime-stats/records", response_model=RuntimeStatsRecordsResponse)
def listRuntimeStatsRecords() -> RuntimeStatsRecordsResponse:
    import runtime_stat_records

    return RuntimeStatsRecordsResponse(
        records=[RuntimeStatsRecordItem(**r) for r in runtime_stat_records.listRuns()]
    )


@app.get("/runtime-stats/record/{record_id}", response_model=RuntimeStatsResponse)
def getRuntimeStatsRecord(record_id: str) -> RuntimeStatsResponse:
    import runtime_stat_records

    snapshot = runtime_stat_records.getSnapshot(record_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return RuntimeStatsResponse(payload=snapshot)


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
# Runtime variables
# ---------------------------------------------------------------------------


class RuntimeVariableDef(BaseModel):
    type: str
    min: float
    max: float
    unit: str


class RuntimeVariablesResponse(BaseModel):
    definitions: Dict[str, RuntimeVariableDef]
    values: Dict[str, Any]


class RuntimeVariablesUpdateRequest(BaseModel):
    values: Dict[str, Any]


@app.get("/runtime-variables", response_model=RuntimeVariablesResponse)
def getRuntimeVariables() -> RuntimeVariablesResponse:
    defs = {k: RuntimeVariableDef(**v) for k, v in VARIABLE_DEFS.items()}
    return RuntimeVariablesResponse(definitions=defs, values=_getRuntimeVariables().getAll())


@app.post("/runtime-variables", response_model=RuntimeVariablesResponse)
def updateRuntimeVariables(
    req: RuntimeVariablesUpdateRequest,
) -> RuntimeVariablesResponse:
    rv = _getRuntimeVariables()
    rv.setAll(req.values)
    defs = {k: RuntimeVariableDef(**v) for k, v in VARIABLE_DEFS.items()}
    return RuntimeVariablesResponse(definitions=defs, values=rv.getAll())


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


@app.post("/api/polygons")
def save_polygons(body: Dict[str, Any]) -> Dict[str, Any]:
    """Save channel and classification polygons."""
    from blob_manager import setChannelPolygons, setClassificationPolygons
    if "channel" in body:
        setChannelPolygons(body["channel"])
    if "classification" in body:
        setClassificationPolygons(body["classification"])
    if "channel" in body and shared_state.vision_manager is not None:
        shared_state.vision_manager.reloadPolygons()
    # Perception (rev04 mode pair) is driven by these same zones but owns its
    # own immutable per-channel stacks; poke its reconciler so a zone edit is
    # picked up within a fraction of a second instead of waiting a restart.
    _ps = getattr(shared_state.gc_ref, "perception_service", None)
    if _ps is not None:
        try:
            _ps.request_reconcile()
        except Exception:
            pass
    return {"ok": True}
