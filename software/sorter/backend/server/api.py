from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import json
import os
from pathlib import Path

from defs.events import (
    IdentityEvent,
    MachineIdentityData,
    KnownObjectData,
    KnownObjectEvent,
)
from bricklink.api import getPartInfo
from blob_manager import (
    getApiKeys,
    getMachineId,
    getMachineNickname,
    getRecentKnownObjects,
    getSortingProfileSyncState,
    setMachineNickname,
)
from runtime_variables import VARIABLE_DEFS
from run_recorder import RECORDS_DIR
from server.camera_discovery import shutdownCameraDiscovery
from server.set_progress_sync import getSetProgressSyncWorker
from server.waveshare_inventory import get_waveshare_inventory_manager
from server.security import compute_allowed_ui_origins, websocket_connection_allowed

from server.shared_state import (
    active_connections,
    broadcastEvent,
    setGlobalConfig,
    setRuntimeVariables,
    setCommandQueue,
    setController,
    setArucoManager,
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
    # Populate sorter_state snapshot on-demand if missing — broadcasts are only
    # fired at FSM transitions, so a freshly-connected client would otherwise
    # default to 'default' camera_layout even when the config says split_feeder.
    if shared_state.sorter_state_snapshot is None:
        layout = None
        if shared_state.vision_manager is not None:
            layout = getattr(shared_state.vision_manager, "_camera_layout", None)
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
# Bricklink
# ---------------------------------------------------------------------------


class BricklinkPartResponse(BaseModel):
    no: str
    name: str
    type: str
    category_id: Optional[int] = None
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    weight: Optional[str] = None
    dim_x: Optional[str] = None
    dim_y: Optional[str] = None
    dim_z: Optional[str] = None
    year_released: Optional[int] = None
    is_obsolete: Optional[bool] = None


@app.get("/bricklink/part/{part_id}", response_model=BricklinkPartResponse)
def getBricklinkPart(part_id: str) -> BricklinkPartResponse:
    data = getPartInfo(part_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return BricklinkPartResponse(**data)


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
    return {"ok": True}
