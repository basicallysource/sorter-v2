from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
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
)
from bricklink.api import getPartInfo
from blob_manager import (
    getApiKeys,
    getMachineId,
    getMachineNickname,
    getSortingProfileSyncState,
    setMachineNickname,
)
from runtime_variables import VARIABLE_DEFS
from run_recorder import RECORDS_DIR
from server.camera_discovery import shutdownCameraDiscovery

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load persisted API keys into environment at import time (overrides env vars)
_saved_api_keys = getApiKeys()
if _saved_api_keys.get("openrouter"):
    os.environ["OPENROUTER_API_KEY"] = _saved_api_keys["openrouter"]

# ---------------------------------------------------------------------------
# Include routers
# ---------------------------------------------------------------------------

from server.routers.hardware import router as hardware_router
from server.routers.steppers import router as steppers_router
from server.routers.cameras import router as cameras_router
from server.routers.detection import router as detection_router
from server.routers.aruco import router as aruco_router
from server.routers.sorting_profiles import router as sorting_profiles_router

app.include_router(hardware_router)
app.include_router(steppers_router)
app.include_router(cameras_router)
app.include_router(detection_router)
app.include_router(aruco_router)
app.include_router(sorting_profiles_router)

# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def onStartup() -> None:
    shared_state.server_loop = asyncio.get_running_loop()


@app.on_event("shutdown")
async def onShutdown() -> None:
    shutdownCameraDiscovery()


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


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    active_connections.append(websocket)

    identity_event = IdentityEvent(tag="identity", data=_getMachineIdentityData())
    await websocket.send_json(identity_event.model_dump())
    if shared_state.runtime_stats_snapshot is not None:
        await websocket.send_json(
            {
                "tag": "runtime_stats",
                "data": {"payload": shared_state.runtime_stats_snapshot},
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
    return {"ok": True}
