from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import json
import queue
import time
import threading
import cv2
import numpy as np
from pathlib import Path
import platform
import re
import shutil
import subprocess

from defs.sorter_controller import SorterLifecycle
from aruco_config_manager import ArucoConfigManager

from defs.events import (
    IdentityEvent,
    MachineIdentityData,
    PauseCommandEvent,
    PauseCommandData,
    ResumeCommandEvent,
    ResumeCommandData,
)
from bricklink.api import getPartInfo
from blob_manager import getMachineId, getMachineNickname, setMachineNickname
from global_config import GlobalConfig
from runtime_variables import RuntimeVariables, VARIABLE_DEFS
from irl.bin_layout import getBinLayout
from irl.config import (
    ArucoTagConfig,
    CarouselArucoTagConfig,
    parseCameraPictureSettings,
    cameraPictureSettingsToDict,
)
from irl.parse_user_toml import (
    DEFAULT_CHUTE_FIRST_BIN_CENTER,
    DEFAULT_CHUTE_PILLAR_WIDTH_DEG,
    DEFAULT_SERVO_CLOSED_ANGLE,
    DEFAULT_SERVO_OPEN_ANGLE,
)
from server.camera_discovery import getDiscoveredCameraStreams, shutdownCameraDiscovery

app = FastAPI(title="Sorter API", version="0.0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

active_connections: List[WebSocket] = []
server_loop: Optional[asyncio.AbstractEventLoop] = None
runtime_vars: Optional[RuntimeVariables] = None
command_queue: Optional[queue.Queue] = None
controller_ref: Optional[Any] = None
gc_ref: Optional[GlobalConfig] = None
aruco_manager: Optional[ArucoConfigManager] = None
vision_manager: Optional[Any] = None
pulse_locks: Dict[str, threading.Lock] = {}


def setGlobalConfig(gc: GlobalConfig) -> None:
    global gc_ref
    gc_ref = gc


def setRuntimeVariables(rv: RuntimeVariables) -> None:
    global runtime_vars
    runtime_vars = rv


def _getRuntimeVariables() -> RuntimeVariables:
    global runtime_vars
    if runtime_vars is None:
        # The standalone API used in local UI dev does not boot the full machine
        # process, so lazily provide an empty runtime variable set instead of 500s.
        runtime_vars = RuntimeVariables()
    return runtime_vars


def setCommandQueue(q: queue.Queue) -> None:
    global command_queue
    command_queue = q


def setController(c: Any) -> None:
    global controller_ref
    controller_ref = c


def setArucoManager(mgr: ArucoConfigManager) -> None:
    global aruco_manager
    aruco_manager = mgr
    auto_calibrate()


def setVisionManager(mgr: Any) -> None:
    global vision_manager
    vision_manager = mgr
    auto_calibrate()


def _build_runtime_aruco_config(config_dict: Dict[str, Any]) -> ArucoTagConfig:
    categories = config_dict.get("categories", {})

    def _tags(category_name: str) -> Dict[str, Any]:
        category = categories.get(category_name, {})
        return category.get("tags", {}) if isinstance(category, dict) else {}

    def _platform(category_name: str) -> CarouselArucoTagConfig:
        platform_tags = _tags(category_name)
        platform = CarouselArucoTagConfig()
        platform.corner1_id = platform_tags.get("corner1")
        platform.corner2_id = platform_tags.get("corner2")
        platform.corner3_id = platform_tags.get("corner3")
        platform.corner4_id = platform_tags.get("corner4")
        return platform

    second_tags = _tags("second_c_channel")
    third_tags = _tags("third_c_channel")

    runtime_config = ArucoTagConfig()
    runtime_config.second_c_channel_center_id = second_tags.get("center")
    runtime_config.second_c_channel_output_guide_id = second_tags.get("output_guide")
    runtime_config.second_c_channel_radius1_id = second_tags.get("radius1")
    runtime_config.second_c_channel_radius2_id = second_tags.get("radius2")
    runtime_config.second_c_channel_radius3_id = second_tags.get("radius3")
    runtime_config.second_c_channel_radius4_id = second_tags.get("radius4")
    runtime_config.second_c_channel_radius5_id = second_tags.get("radius5")
    runtime_config.second_c_channel_radius_ids = [
        int(tag)
        for tag in [
            second_tags.get("radius1"),
            second_tags.get("radius2"),
            second_tags.get("radius3"),
            second_tags.get("radius4"),
            second_tags.get("radius5"),
        ]
        if tag is not None
    ]
    runtime_config.second_c_channel_radius_multiplier = float(
        categories.get("second_c_channel", {}).get("radius_multiplier", 1.0)
    )
    runtime_config.third_c_channel_center_id = third_tags.get("center")
    runtime_config.third_c_channel_output_guide_id = third_tags.get("output_guide")
    runtime_config.third_c_channel_radius1_id = third_tags.get("radius1")
    runtime_config.third_c_channel_radius2_id = third_tags.get("radius2")
    runtime_config.third_c_channel_radius3_id = third_tags.get("radius3")
    runtime_config.third_c_channel_radius4_id = third_tags.get("radius4")
    runtime_config.third_c_channel_radius5_id = third_tags.get("radius5")
    runtime_config.third_c_channel_radius_ids = [
        int(tag)
        for tag in [
            third_tags.get("radius1"),
            third_tags.get("radius2"),
            third_tags.get("radius3"),
            third_tags.get("radius4"),
            third_tags.get("radius5"),
        ]
        if tag is not None
    ]
    runtime_config.third_c_channel_radius_multiplier = float(
        categories.get("third_c_channel", {}).get("radius_multiplier", 1.0)
    )
    runtime_config.carousel_platform1 = _platform("carousel_platform_1")
    runtime_config.carousel_platform2 = _platform("carousel_platform_2")
    runtime_config.carousel_platform3 = _platform("carousel_platform_3")
    runtime_config.carousel_platform4 = _platform("carousel_platform_4")
    return runtime_config


def _sync_aruco_config_to_vision() -> Dict[str, Any]:
    if aruco_manager is None:
        return {"synced": False, "reason": "aruco_manager_not_initialized"}
    if vision_manager is None:
        return {"synced": False, "reason": "vision_manager_not_initialized"}

    config_dict = aruco_manager.get_config_dict()
    runtime_config = _build_runtime_aruco_config(config_dict)
    vision_manager._irl_config.aruco_tags = runtime_config
    smoothing_time_s = aruco_manager.get_aruco_smoothing_time_s()
    if hasattr(vision_manager, "setArucoSmoothingTimeSeconds"):
        vision_manager.setArucoSmoothingTimeSeconds(smoothing_time_s)

    return {
        "synced": True,
        "aruco_smoothing_time_s": smoothing_time_s,
        "second_c_channel": {
            "center": runtime_config.second_c_channel_center_id,
            "output_guide": runtime_config.second_c_channel_output_guide_id,
            "radius_ids": runtime_config.second_c_channel_radius_ids,
            "radius_multiplier": runtime_config.second_c_channel_radius_multiplier,
        },
        "third_c_channel": {
            "center": runtime_config.third_c_channel_center_id,
            "output_guide": runtime_config.third_c_channel_output_guide_id,
            "radius_ids": runtime_config.third_c_channel_radius_ids,
            "radius_multiplier": runtime_config.third_c_channel_radius_multiplier,
        },
    }


def auto_calibrate() -> Dict[str, Any]:
    """Sync live ArUco config into vision and trigger region recomputation."""
    sync_result = _sync_aruco_config_to_vision()
    if not sync_result.get("synced"):
        return {
            "ok": False,
            "calibrated": False,
            "sync": sync_result,
        }

    assert vision_manager is not None
    try:
        # force region recomputation by fetching current regions
        vision_manager.getRegions()
        return {
            "ok": True,
            "calibrated": True,
            "sync": sync_result,
        }
    except Exception as e:
        return {
            "ok": False,
            "calibrated": False,
            "sync": sync_result,
            "error": str(e),
        }


@app.on_event("startup")
async def onStartup() -> None:
    global server_loop
    server_loop = asyncio.get_running_loop()


@app.on_event("shutdown")
async def onShutdown() -> None:
    shutdownCameraDiscovery()


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


class MachineIdentityUpdateRequest(BaseModel):
    nickname: Optional[str] = None


def _getMachineIdentityData() -> MachineIdentityData:
    machine_id = gc_ref.machine_id if gc_ref is not None else getMachineId()
    return MachineIdentityData(
        machine_id=machine_id,
        nickname=getMachineNickname(),
    )


def _broadcastIdentityUpdate() -> None:
    if server_loop is None:
        return

    identity_event = IdentityEvent(tag="identity", data=_getMachineIdentityData())
    future = asyncio.run_coroutine_threadsafe(
        broadcastEvent(identity_event.model_dump()),
        server_loop,
    )
    try:
        future.result(timeout=1.0)
    except Exception:
        pass


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    active_connections.append(websocket)

    identity_event = IdentityEvent(tag="identity", data=_getMachineIdentityData())
    await websocket.send_json(identity_event.model_dump())

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)


async def broadcastEvent(event: dict) -> None:
    dead_connections = []
    for connection in active_connections[:]:
        try:
            await connection.send_json(event)
        except Exception:
            dead_connections.append(connection)
    for conn in dead_connections:
        if conn in active_connections:
            active_connections.remove(conn)


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


@app.get("/api/machine-identity", response_model=MachineIdentityData)
def get_machine_identity() -> MachineIdentityData:
    return _getMachineIdentityData()


@app.post("/api/machine-identity", response_model=MachineIdentityData)
def save_machine_identity(payload: MachineIdentityUpdateRequest) -> MachineIdentityData:
    setMachineNickname(payload.nickname)
    identity = _getMachineIdentityData()
    _broadcastIdentityUpdate()
    return identity


@app.get("/bricklink/part/{part_id}", response_model=BricklinkPartResponse)
def getBricklinkPart(part_id: str) -> BricklinkPartResponse:
    data = getPartInfo(part_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Part not found")
    return BricklinkPartResponse(**data)


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


class ServoChannelConfigPayload(BaseModel):
    id: int
    invert: bool = False


class ServoHardwareSettingsPayload(BaseModel):
    backend: str = "pca9685"
    open_angle: int = DEFAULT_SERVO_OPEN_ANGLE
    closed_angle: int = DEFAULT_SERVO_CLOSED_ANGLE
    port: Optional[str] = None
    channels: List[ServoChannelConfigPayload] = []


class ChuteHardwareSettingsPayload(BaseModel):
    first_bin_center: float = DEFAULT_CHUTE_FIRST_BIN_CENTER
    pillar_width_deg: float = DEFAULT_CHUTE_PILLAR_WIDTH_DEG


class StorageLayerSettingsPayload(BaseModel):
    layer_bin_counts: List[int] = []


ALLOWED_STORAGE_LAYER_BIN_COUNTS = [12, 18, 30]
DEFAULT_STORAGE_LAYER_SECTION_COUNT = 6


@app.get("/runtime-variables", response_model=RuntimeVariablesResponse)
def getRuntimeVariables() -> RuntimeVariablesResponse:
    defs = {k: RuntimeVariableDef(**v) for k, v in VARIABLE_DEFS.items()}
    return RuntimeVariablesResponse(definitions=defs, values=_getRuntimeVariables().getAll())


@app.post("/runtime-variables", response_model=RuntimeVariablesResponse)
def updateRuntimeVariables(
    req: RuntimeVariablesUpdateRequest,
) -> RuntimeVariablesResponse:
    runtime_vars = _getRuntimeVariables()
    runtime_vars.setAll(req.values)
    defs = {k: RuntimeVariableDef(**v) for k, v in VARIABLE_DEFS.items()}
    return RuntimeVariablesResponse(definitions=defs, values=runtime_vars.getAll())


@app.get("/api/hardware-config")
def get_hardware_config() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    _, layout = _read_bin_layout_config()
    return {
        "storage_layers": _storage_layer_settings_from_layout(layout),
        "servo": _servo_settings_from_config(config),
        "chute": _chute_settings_from_config(config),
    }


@app.post("/api/hardware-config/servo")
def save_servo_hardware_config(
    payload: ServoHardwareSettingsPayload,
) -> Dict[str, Any]:
    backend = payload.backend if payload.backend in {"pca9685", "waveshare"} else "pca9685"
    open_angle = max(0, min(180, int(payload.open_angle)))
    closed_angle = max(0, min(180, int(payload.closed_angle)))
    port = payload.port.strip() if isinstance(payload.port, str) and payload.port.strip() else None
    layer_count = _distribution_layer_count()
    available_pca_channels = _pca_available_servo_channels()

    if len(payload.channels) != layer_count:
        raise HTTPException(
            status_code=400,
            detail=f"Expected {layer_count} layer servo assignments, got {len(payload.channels)}.",
        )

    channels: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()
    for index, channel in enumerate(payload.channels):
        channel_id = int(channel.id)
        if backend == "waveshare":
            valid = 1 <= channel_id <= 253
            help_text = "an SC servo ID between 1 and 253"
        else:
            valid = channel_id >= 0 and (
                not available_pca_channels or channel_id in available_pca_channels
            )
            help_text = "a valid PCA servo channel"

        if not valid:
            raise HTTPException(
                status_code=400,
                detail=f"Layer {index + 1} needs {help_text}.",
            )
        if channel_id in seen_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Servo assignment {channel_id} is used more than once.",
            )
        seen_ids.add(channel_id)
        channels.append({"id": channel_id, "invert": bool(channel.invert)})

    params_path, config = _read_machine_params_config()
    previous = _servo_settings_from_config(config)

    servo_table: Dict[str, Any] = {"backend": backend, "channels": channels}
    if backend == "pca9685":
        servo_table["open_angle"] = open_angle
        servo_table["closed_angle"] = closed_angle
    if backend == "waveshare":
        if port is not None:
            servo_table["port"] = port

    config["servo"] = servo_table

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    previous_ids = [int(channel["id"]) for channel in previous["channels"]]
    previous_inverts = [bool(channel["invert"]) for channel in previous["channels"]]
    channel_ids = [int(channel["id"]) for channel in channels]
    channel_inverts = [bool(channel["invert"]) for channel in channels]

    restart_required = (
        backend != previous["backend"]
        or channel_ids != previous_ids
        or (backend == "waveshare" and port != previous["port"])
    )

    applied_live = False
    if not restart_required and controller_ref is not None and hasattr(controller_ref, "irl"):
        try:
            live_servos = list(getattr(controller_ref.irl, "servos", []))
            if len(live_servos) == len(channels):
                for index, servo in enumerate(live_servos):
                    invert = channel_inverts[index]
                    if backend == "waveshare":
                        if hasattr(servo, "set_invert"):
                            servo.set_invert(invert)
                    elif hasattr(servo, "set_preset_angles"):
                        if invert:
                            servo.set_preset_angles(closed_angle, open_angle)
                        else:
                            servo.set_preset_angles(open_angle, closed_angle)
                applied_live = True
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "settings": _servo_settings_from_config(config),
        "applied_live": applied_live,
        "restart_required": restart_required,
        "message": (
            "Servo settings saved and applied live."
            if applied_live
            else "Servo settings saved. Restart backend to apply backend or bus changes."
        ),
    }


@app.post("/api/hardware-config/servo/layers/{layer_index}/toggle")
def toggle_layer_servo(layer_index: int) -> Dict[str, Any]:
    servo = _live_servo_for_layer(layer_index)
    if not hasattr(servo, "toggle"):
        raise HTTPException(status_code=500, detail="Selected servo does not support test toggling.")

    try:
        servo.toggle()
        is_open = bool(servo.isOpen()) if hasattr(servo, "isOpen") else False
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle layer {layer_index + 1} servo: {e}")

    return {
        "ok": True,
        "layer_index": layer_index,
        "is_open": is_open,
        "message": (
            f"Layer {layer_index + 1} servo opened."
            if is_open
            else f"Layer {layer_index + 1} servo closed."
        ),
    }


@app.post("/api/hardware-config/servo/layers/{layer_index}/calibrate")
def calibrate_layer_servo(layer_index: int) -> Dict[str, Any]:
    servo = _live_servo_for_layer(layer_index)
    if not hasattr(servo, "recalibrate"):
        raise HTTPException(
            status_code=400,
            detail="Calibration is only supported for Waveshare storage-layer servos.",
        )

    try:
        min_limit, max_limit = servo.recalibrate()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calibrate layer {layer_index + 1} servo: {e}")

    return {
        "ok": True,
        "layer_index": layer_index,
        "limits": {"min": min_limit, "max": max_limit},
        "message": f"Layer {layer_index + 1} servo calibrated.",
    }


@app.post("/api/hardware-config/chute")
def save_chute_hardware_config(
    payload: ChuteHardwareSettingsPayload,
) -> Dict[str, Any]:
    first_bin_center = float(payload.first_bin_center)
    pillar_width_deg = float(payload.pillar_width_deg)
    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        raise HTTPException(
            status_code=400,
            detail="pillar_width_deg must be between 0 and less than 60 degrees",
        )

    params_path, config = _read_machine_params_config()
    config["chute"] = {
        "first_bin_center": first_bin_center,
        "pillar_width_deg": pillar_width_deg,
    }

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live = False
    if controller_ref is not None and hasattr(controller_ref, "irl"):
        chute = getattr(controller_ref.irl, "chute", None)
        if chute is not None and hasattr(chute, "setCalibration"):
            try:
                chute.setCalibration(first_bin_center, pillar_width_deg)
                applied_live = True
            except Exception:
                applied_live = False

    return {
        "ok": True,
        "settings": _chute_settings_from_config(config),
        "applied_live": applied_live,
        "message": (
            "Chute settings saved and applied live."
            if applied_live
            else "Chute settings saved."
        ),
    }


@app.post("/api/hardware-config/storage-layers")
def save_storage_layer_hardware_config(
    payload: StorageLayerSettingsPayload,
) -> Dict[str, Any]:
    layout_path, layout = _read_bin_layout_config()
    current = _storage_layer_settings_from_layout(layout)
    layer_bin_counts = [int(count) for count in payload.layer_bin_counts]

    if len(layer_bin_counts) != len(current["layers"]):
        raise HTTPException(
            status_code=400,
            detail=f"Expected {len(current['layers'])} layer bin counts, got {len(layer_bin_counts)}.",
        )

    updated_layers: List[Dict[str, Any]] = []
    changed = False
    for count, layer in zip(layer_bin_counts, current["layers"]):
        if count not in ALLOWED_STORAGE_LAYER_BIN_COUNTS:
            raise HTTPException(
                status_code=400,
                detail=f"Each layer bin count must be one of {ALLOWED_STORAGE_LAYER_BIN_COUNTS}.",
            )

        section_count = int(layer["section_count"])
        if section_count <= 0 or count % section_count != 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Layer {layer['index']} cannot be configured to {count} bins "
                    f"with its current {section_count} sections."
                ),
            )

        updated_layers.append(
            {
                "section_count": section_count,
                "bin_size": layer["bin_size"],
                "bins_per_section": count // section_count,
            }
        )
        changed = changed or count != int(layer["bin_count"])

    if not changed:
        return {
            "ok": True,
            "settings": current,
            "applied_live": False,
            "restart_required": False,
            "message": "Storage layer layout unchanged.",
        }

    try:
        _write_bin_layout_config(layout_path, updated_layers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write bin layout: {e}")

    _, saved_layout = _read_bin_layout_config()
    return {
        "ok": True,
        "settings": _storage_layer_settings_from_layout(saved_layout),
        "applied_live": False,
        "restart_required": True,
        "message": "Storage layer layout saved. Restart backend to apply layer changes.",
    }


class StateResponse(BaseModel):
    state: str
    camera_layout: str = "default"


def _getCameraLayout() -> str:
    if vision_manager is not None:
        return getattr(vision_manager, "_camera_layout", "default")
    # Fallback: read directly from TOML
    import os, tomllib
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if params_path and os.path.exists(params_path):
        try:
            with open(params_path, "rb") as f:
                raw = tomllib.load(f)
            return raw.get("cameras", {}).get("layout", "default")
        except Exception:
            pass
    return "default"


@app.get("/state", response_model=StateResponse)
def getState() -> StateResponse:
    layout = _getCameraLayout()
    if controller_ref is None:
        return StateResponse(state=SorterLifecycle.INITIALIZING.value, camera_layout=layout)
    return StateResponse(state=controller_ref.state.value, camera_layout=layout)


class CommandResponse(BaseModel):
    success: bool


@app.post("/pause", response_model=CommandResponse)
def pause() -> CommandResponse:
    if command_queue is None:
        raise HTTPException(status_code=500, detail="Command queue not initialized")
    event = PauseCommandEvent(tag="pause", data=PauseCommandData())
    command_queue.put(event)
    return CommandResponse(success=True)


@app.post("/resume", response_model=CommandResponse)
def resume() -> CommandResponse:
    if command_queue is None:
        raise HTTPException(status_code=500, detail="Command queue not initialized")
    event = ResumeCommandEvent(tag="resume", data=ResumeCommandData())
    command_queue.put(event)
    return CommandResponse(success=True)


class StepperPulseResponse(BaseModel):
    success: bool
    stepper: str
    direction: str
    duration_s: float
    speed: int


class StepperStopResponse(BaseModel):
    success: bool
    stepper: str


def _resolve_stepper(stepper_name: str) -> Any:
    if controller_ref is None or not hasattr(controller_ref, "irl"):
        raise HTTPException(status_code=500, detail="Controller not initialized")

    irl = controller_ref.irl
    mapping = {
        "c_channel_1": getattr(irl, "c_channel_1_rotor_stepper", None),
        "c_channel_2": getattr(irl, "c_channel_2_rotor_stepper", None),
        "c_channel_3": getattr(irl, "c_channel_3_rotor_stepper", None),
        "carousel": getattr(irl, "carousel_stepper", None),
        "chute": getattr(irl, "chute_stepper", None),
    }

    if stepper_name not in mapping:
        raise HTTPException(status_code=400, detail=f"Unknown stepper '{stepper_name}'")

    stepper = mapping[stepper_name]
    if stepper is None:
        raise HTTPException(status_code=500, detail=f"Stepper '{stepper_name}' unavailable")
    return stepper


def _stop_stepper_after_delay(stepper: Any, delay_s: float, lock: threading.Lock) -> None:
    try:
        time.sleep(delay_s)
        stepper.move_at_speed(0)
        stepper.enabled = False
    except Exception:
        pass
    finally:
        try:
            lock.release()
        except RuntimeError:
            pass


@app.post("/stepper/pulse", response_model=StepperPulseResponse)
def pulse_stepper(
    stepper: str,
    direction: str,
    duration_s: float = 0.25,
    speed: int = 800,
) -> StepperPulseResponse:
    if duration_s <= 0 or duration_s > 5.0:
        raise HTTPException(status_code=400, detail="duration_s must be in (0, 5]")
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")
    if direction not in ("cw", "ccw"):
        raise HTTPException(status_code=400, detail="direction must be 'cw' or 'ccw'")

    target = _resolve_stepper(stepper)

    lock = pulse_locks.setdefault(stepper, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is already pulsing")

    signed_speed = speed if direction == "cw" else -speed

    try:
        target.enabled = True
        target.move_at_speed(signed_speed)
    except Exception as e:
        lock.release()
        raise HTTPException(status_code=500, detail=f"Pulse start failed: {e}")

    threading.Thread(
        target=_stop_stepper_after_delay,
        args=(target, duration_s, lock),
        daemon=True,
    ).start()

    return StepperPulseResponse(
        success=True,
        stepper=stepper,
        direction=direction,
        duration_s=duration_s,
        speed=speed,
    )


@app.post("/stepper/stop", response_model=StepperStopResponse)
def stop_stepper(stepper: str) -> StepperStopResponse:
    target = _resolve_stepper(stepper)

    try:
        target.enabled = False
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Disable failed: {e}")

    return StepperStopResponse(success=True, stepper=stepper)


# Video Streaming Routes
@app.get("/video_feed/{camera_name}")
def video_feed(camera_name: str, show_live_aruco_values: bool = False) -> StreamingResponse:
    """Stream MJPEG video from the specified camera"""
    if vision_manager is None:
        raise HTTPException(status_code=500, detail="Vision manager not initialized")
    vm = vision_manager

    def generate_frames():
        """Generator function that yields JPEG frames"""
        import time
        quality = 80  # JPEG quality (0-100)
        
        while True:
            frame_obj = vm.getFrame(camera_name)
            if frame_obj is None:
                # Send a placeholder frame if no frame available
                placeholder = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(placeholder, f"Waiting for {camera_name} camera...", 
                           (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (200, 200, 200), 2)
                _, buffer = cv2.imencode('.jpg', placeholder, [cv2.IMWRITE_JPEG_QUALITY, quality])
            else:
                # Use annotated frame if available, otherwise use raw frame
                frame_to_encode = frame_obj.annotated if frame_obj.annotated is not None else frame_obj.raw

                if camera_name == "feeder" and show_live_aruco_values:
                    frame_to_encode = frame_to_encode.copy()
                    raw_tags = vm.getFeederArucoTagsRaw()
                    for tag_id, (center_x_f, center_y_f) in raw_tags.items():
                        center = (int(center_x_f), int(center_y_f))
                        cv2.circle(frame_to_encode, center, 5, (0, 0, 255), -1)
                        cv2.putText(
                            frame_to_encode,
                            f"raw {tag_id}",
                            (center[0] + 8, center[1] - 8),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.45,
                            (0, 0, 255),
                            1,
                        )

                _, buffer = cv2.imencode('.jpg', frame_to_encode, [cv2.IMWRITE_JPEG_QUALITY, quality])
            
            # Yield frame in MJPEG format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n'
                   b'Content-Length: ' + str(len(buffer)).encode() + b'\r\n\r\n' +
                   buffer.tobytes() + b'\r\n')
            
            time.sleep(0.03)  # ~30 FPS
    
    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ArUco Tag Configuration Routes
@app.get("/aruco", response_class=HTMLResponse)
def get_aruco_config_page() -> str:
    """Serve the ArUco tag configuration page"""
    template_path = Path(__file__).parent / "templates" / "aruco_config.html"
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Template not found")
    return template_path.read_text()


@app.get("/feeder-calibration", response_class=HTMLResponse)
def get_feeder_calibration_page() -> str:
    """Serve the feeder calibration page."""
    return get_aruco_config_page()


@app.get("/api/aruco/config")
def get_aruco_config() -> Dict[str, Any]:
    """Get full ArUco configuration"""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return aruco_manager.get_config_dict()


@app.get("/api/aruco/categories")
def get_aruco_categories() -> Dict[str, Any]:
    """Get all categories with their tag assignments"""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    config = aruco_manager.get_config_dict()
    return config["categories"]


@app.get("/api/aruco/tags/unassigned")
def get_unassigned_tags() -> List[int]:
    """Get list of unassigned tag IDs"""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return aruco_manager.get_unassigned_tags()


@app.get("/api/aruco/tags/all")
def get_all_tags() -> List[int]:
    """Get all known tag IDs"""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return aruco_manager.get_all_tags()


@app.post("/api/aruco/assign")
def assign_tag(tag_id: int, category: str, role: str) -> Dict[str, Any]:
    """Assign a tag to a specific category and role"""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    assigned = aruco_manager.assign_tag(tag_id, category, role)
    if not assigned:
        raise HTTPException(status_code=400, detail="Invalid category or role for assignment")
    calibration = auto_calibrate()
    return {
        "status": "success",
        "message": f"Tag {tag_id} assigned to {category}/{role}",
        "calibration": calibration,
    }


@app.post("/api/aruco/unassign")
def unassign_tag(tag_id: int) -> Dict[str, Any]:
    """Unassign a tag and move it back to unassigned"""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    unassigned = aruco_manager.unassign_tag(tag_id)
    if not unassigned:
        raise HTTPException(status_code=400, detail="Unable to unassign tag")
    calibration = auto_calibrate()
    return {
        "status": "success",
        "message": f"Tag {tag_id} moved to unassigned",
        "calibration": calibration,
    }


@app.post("/api/aruco/radius-multiplier")
def set_radius_multiplier(category: str, value: float) -> Dict[str, Any]:
    """Set per-channel radius multiplier for feeder calibration."""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    updated = aruco_manager.set_radius_multiplier(category, value)
    if not updated:
        raise HTTPException(status_code=400, detail="Invalid category or multiplier value")
    calibration = auto_calibrate()
    return {
        "status": "success",
        "message": f"Radius multiplier for {category} set to {value}",
        "calibration": calibration,
    }


@app.get("/api/aruco/smoothing-time")
def get_aruco_smoothing_time() -> Dict[str, Any]:
    """Get ArUco smoothing time in seconds."""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    return {"aruco_smoothing_time_s": aruco_manager.get_aruco_smoothing_time_s()}


@app.post("/api/aruco/smoothing-time")
def set_aruco_smoothing_time(value: float) -> Dict[str, Any]:
    """Set ArUco smoothing time in seconds (0 disables smoothing)."""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    updated = aruco_manager.set_aruco_smoothing_time_s(value)
    if not updated:
        raise HTTPException(status_code=400, detail="Invalid smoothing time")
    calibration = auto_calibrate()
    return {
        "status": "success",
        "message": f"ArUco smoothing time set to {value} seconds",
        "calibration": calibration,
    }


@app.get("/api/aruco/category/{name}")
def get_category(name: str) -> Dict[str, Any]:
    """Get specific category details"""
    if aruco_manager is None:
        raise HTTPException(status_code=500, detail="ArUco manager not initialized")
    try:
        return aruco_manager.get_category(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/aruco/recalibrate")
def recalibrate_aruco() -> Dict[str, Any]:
    """Manually force runtime ArUco sync + geometry recalculation."""
    calibration = auto_calibrate()
    if not calibration.get("ok"):
        raise HTTPException(status_code=500, detail=calibration)
    return calibration


# --- Camera Setup ---

CAMERA_SETUP_ROLES = {
    "feeder",
    "c_channel_2",
    "c_channel_3",
    "carousel",
    "classification_top",
    "classification_bottom",
}


def _camera_params_path() -> str:
    import os

    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if not params_path:
        raise HTTPException(status_code=500, detail="MACHINE_SPECIFIC_PARAMS_PATH not set")
    return params_path


def _bin_layout_path() -> str:
    import os

    layout_path = os.getenv("BIN_LAYOUT_PATH")
    if not layout_path:
        raise HTTPException(status_code=500, detail="BIN_LAYOUT_PATH not set")
    return layout_path


def _read_machine_params_config(
    *,
    require_exists: bool = False,
) -> tuple[str, Dict[str, Any]]:
    import os
    import tomllib

    params_path = _camera_params_path()
    if not os.path.exists(params_path):
        if require_exists:
            raise HTTPException(status_code=404, detail="Machine params file not found")
        return params_path, {}

    try:
        with open(params_path, "rb") as f:
            return params_path, tomllib.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read config: {e}")


def _read_bin_layout_config() -> tuple[str, Any]:
    layout_path = _bin_layout_path()
    try:
        return layout_path, getBinLayout()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read bin layout: {e}")


def _toml_value(v: object) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return str(v)
    if isinstance(v, str):
        return f'"{v}"'
    return str(v)


def _write_machine_params_config(path: str, data: Dict[str, Any]) -> None:
    lines: list[str] = []
    simple_keys: list[str] = []
    table_keys: list[str] = []
    array_table_keys: list[str] = []

    for k, v in data.items():
        if isinstance(v, dict):
            has_array_tables = any(
                isinstance(sv, list) and sv and isinstance(sv[0], dict)
                for sv in v.values()
            )
            if has_array_tables:
                array_table_keys.append(k)
            else:
                table_keys.append(k)
        else:
            simple_keys.append(k)

    for k in simple_keys:
        lines.append(f"{k} = {_toml_value(data[k])}")

    for k in table_keys:
        lines.append(f"\n[{k}]")
        table = data[k]
        sub_tables = []
        for sk, sv in table.items():
            if isinstance(sv, dict):
                sub_tables.append((sk, sv))
            elif isinstance(sv, list) and sv and isinstance(sv[0], dict):
                pass
            else:
                lines.append(f"{sk} = {_toml_value(sv)}")
        for sk, sv in sub_tables:
            lines.append(f"\n[{k}.{sk}]")
            for ssk, ssv in sv.items():
                lines.append(f"{ssk} = {_toml_value(ssv)}")

    for k in array_table_keys:
        table = data[k]
        non_array = {
            sk: sv
            for sk, sv in table.items()
            if not (isinstance(sv, list) and sv and isinstance(sv[0], dict))
        }
        array_items = {
            sk: sv
            for sk, sv in table.items()
            if isinstance(sv, list) and sv and isinstance(sv[0], dict)
        }
        lines.append(f"\n[{k}]")
        for sk, sv in non_array.items():
            lines.append(f"{sk} = {_toml_value(sv)}")
        for sk, sv in array_items.items():
            for item in sv:
                lines.append(f"\n[[{k}.{sk}]]")
                for ik, iv in item.items():
                    lines.append(f"{ik} = {_toml_value(iv)}")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _write_bin_layout_config(path: str, layers: List[Dict[str, Any]]) -> None:
    payload = {
        "layers": [
            {
                "sections": [
                    [layer["bin_size"]] * layer["bins_per_section"]
                    for _ in range(layer["section_count"])
                ]
            }
            for layer in layers
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def _get_picture_settings_table(config: Dict[str, Any]) -> Dict[str, Any]:
    picture_settings = config.get("camera_picture_settings", {})
    return picture_settings if isinstance(picture_settings, dict) else {}


def _distribution_layer_count() -> int:
    if controller_ref is not None and hasattr(controller_ref, "irl"):
        layout = getattr(controller_ref.irl, "distribution_layout", None)
        if layout is not None and hasattr(layout, "layers"):
            return len(layout.layers)
    return len(getBinLayout().layers)


def _pca_available_servo_channels() -> List[int]:
    if controller_ref is not None and hasattr(controller_ref, "irl"):
        interfaces = getattr(controller_ref.irl, "interfaces", {})
        channels: set[int] = set()
        if isinstance(interfaces, dict):
            for interface in interfaces.values():
                for servo in getattr(interface, "servos", []):
                    channel = getattr(servo, "channel", None)
                    if isinstance(channel, int) and not isinstance(channel, bool):
                        channels.add(channel)
        if channels:
            return sorted(channels)
    return list(range(_distribution_layer_count()))


def _live_servo_for_layer(layer_index: int) -> Any:
    if controller_ref is None or not hasattr(controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Servo controller not initialized.")

    servos = list(getattr(controller_ref.irl, "servos", []))
    if layer_index < 0 or layer_index >= len(servos):
        raise HTTPException(status_code=404, detail=f"Unknown storage layer {layer_index + 1}.")
    return servos[layer_index]


def _storage_layer_settings_from_layout(layout: Any) -> Dict[str, Any]:
    layers: List[Dict[str, Any]] = []
    for index, layer in enumerate(getattr(layout, "layers", []), start=1):
        sections = getattr(layer, "sections", [])
        bin_count = sum(len(section) for section in sections)
        section_count = len(sections) or DEFAULT_STORAGE_LAYER_SECTION_COUNT

        bin_size = "medium"
        for section in sections:
            for value in section:
                if isinstance(value, str) and value:
                    bin_size = value
                    break
            if bin_size != "medium":
                break

        layers.append(
            {
                "index": index,
                "bin_count": bin_count,
                "section_count": section_count,
                "bin_size": bin_size,
            }
        )

    return {
        "allowed_bin_counts": ALLOWED_STORAGE_LAYER_BIN_COUNTS,
        "layers": layers,
    }


def _coerce_float(value: object, default: float) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return default


def _servo_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    servo = config.get("servo", {})
    if not isinstance(servo, dict):
        servo = {}

    backend = servo.get("backend", "pca9685")
    if backend not in {"pca9685", "waveshare"}:
        backend = "pca9685"

    open_angle = servo.get("open_angle", DEFAULT_SERVO_OPEN_ANGLE)
    if not isinstance(open_angle, int) or isinstance(open_angle, bool):
        open_angle = DEFAULT_SERVO_OPEN_ANGLE

    closed_angle = servo.get("closed_angle", DEFAULT_SERVO_CLOSED_ANGLE)
    if not isinstance(closed_angle, int) or isinstance(closed_angle, bool):
        closed_angle = DEFAULT_SERVO_CLOSED_ANGLE

    port = servo.get("port")
    if port is not None and not isinstance(port, str):
        port = None

    layer_count = _distribution_layer_count()
    parsed_channels: List[Dict[str, Any]] = []
    channels_raw = servo.get("channels", [])
    if isinstance(channels_raw, list):
        for item in channels_raw:
            if not isinstance(item, dict):
                continue
            channel_id = item.get("id")
            if not isinstance(channel_id, int) or isinstance(channel_id, bool):
                continue
            parsed_channels.append(
                {
                    "id": channel_id,
                    "invert": bool(item.get("invert", False)),
                }
            )

    channels: List[Dict[str, Any]] = []
    for index in range(layer_count):
        existing = parsed_channels[index] if index < len(parsed_channels) else None
        default_id = index + 1 if backend == "waveshare" else index
        channels.append(
            {
                "id": int(existing["id"]) if existing is not None else default_id,
                "invert": bool(existing["invert"]) if existing is not None else False,
            }
        )

    return {
        "backend": backend,
        "open_angle": max(0, min(180, open_angle)),
        "closed_angle": max(0, min(180, closed_angle)),
        "port": port.strip() if isinstance(port, str) and port.strip() else None,
        "channels": channels,
        "layer_count": layer_count,
        "available_channel_ids": _pca_available_servo_channels() if backend == "pca9685" else [],
        "supports_calibration": backend == "waveshare",
    }


def _chute_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    chute = config.get("chute", {})
    if not isinstance(chute, dict):
        chute = {}

    first_bin_center = _coerce_float(
        chute.get("first_bin_center"),
        DEFAULT_CHUTE_FIRST_BIN_CENTER,
    )
    pillar_width_deg = _coerce_float(
        chute.get("pillar_width_deg"),
        DEFAULT_CHUTE_PILLAR_WIDTH_DEG,
    )

    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        pillar_width_deg = DEFAULT_CHUTE_PILLAR_WIDTH_DEG

    return {
        "first_bin_center": first_bin_center,
        "pillar_width_deg": pillar_width_deg,
    }


def _picture_settings_for_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    picture_settings = _get_picture_settings_table(config)
    return cameraPictureSettingsToDict(parseCameraPictureSettings(picture_settings.get(role)))


@app.get("/api/cameras/config")
def get_camera_config() -> Dict[str, Any]:
    """Return current camera assignments from TOML."""
    try:
        _, raw = _read_machine_params_config()
        cameras = raw.get("cameras", {}) if isinstance(raw, dict) else {}
        if not isinstance(cameras, dict):
            cameras = {}
        return {
            "layout": cameras.get("layout", "default"),
            "c_channel_2": cameras.get("c_channel_2"),
            "c_channel_3": cameras.get("c_channel_3"),
            "carousel": cameras.get("carousel"),
            "classification_top": cameras.get("classification_top"),
            "classification_bottom": cameras.get("classification_bottom"),
        }
    except HTTPException:
        return {
            "layout": "default",
            "c_channel_2": None,
            "c_channel_3": None,
            "carousel": None,
            "classification_top": None,
            "classification_bottom": None,
        }


@app.get("/api/cameras/list")
def list_cameras() -> Dict[str, Any]:
    """List local USB cameras plus discovered network camera streams."""
    usb_cameras = _list_usb_cameras()
    return {
        "usb": usb_cameras,
        "network": getDiscoveredCameraStreams(),
    }


def _open_camera(index: int) -> cv2.VideoCapture:
    if platform.system() == "Darwin":
        return cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
    return cv2.VideoCapture(index)


def _open_camera_source(source: int | str) -> cv2.VideoCapture:
    if isinstance(source, int):
        return _open_camera(source)
    return cv2.VideoCapture(source)


def _probe_camera_index(index: int) -> Optional[Dict[str, Any]]:
    cap = _open_camera(index)
    if not cap.isOpened():
        cap.release()
        return None

    try:
        ret, frame = cap.read()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if ret and frame is not None:
            height, width = frame.shape[:2]
        if width <= 0 or height <= 0:
            return None
        return {
            "kind": "usb",
            "index": index,
            "width": width,
            "height": height,
            "preview_available": bool(ret and frame is not None),
        }
    finally:
        cap.release()


def _list_avfoundation_video_devices() -> List[Dict[str, Any]]:
    if platform.system() != "Darwin":
        return []

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        return []

    try:
        result = subprocess.run(
            [ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return []

    output = f"{result.stdout}\n{result.stderr}"
    devices: List[Dict[str, Any]] = []
    in_video_section = False
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if "AVFoundation video devices:" in line:
            in_video_section = True
            continue
        if "AVFoundation audio devices:" in line:
            break
        if not in_video_section:
            continue

        match = re.search(r"\[(\d+)\]\s+(.+)$", line)
        if not match:
            continue

        index = int(match.group(1))
        name = match.group(2).strip()
        if name.lower().startswith("capture screen"):
            continue

        devices.append(
            {
                "kind": "usb",
                "index": index,
                "name": name,
            }
        )

    return devices


def _list_usb_cameras() -> List[Dict[str, Any]]:
    if platform.system() == "Darwin":
        enumerated = _list_avfoundation_video_devices()
        if enumerated:
            cameras: List[Dict[str, Any]] = []
            for camera in enumerated:
                probed = _probe_camera_index(int(camera["index"]))
                cameras.append(
                    {
                        "kind": "usb",
                        "index": int(camera["index"]),
                        "name": str(camera["name"]),
                        "width": int((probed or {}).get("width", 0)),
                        "height": int((probed or {}).get("height", 0)),
                        "preview_available": bool((probed or {}).get("preview_available", False)),
                    }
                )
            return cameras

    usb_cameras: List[Dict[str, Any]] = []
    for i in range(16):
        probed = _probe_camera_index(i)
        if probed is None:
            continue
        usb_cameras.append(probed)
    return usb_cameras


@app.get("/api/cameras/stream/{index}")
def camera_stream(index: int):
    """MJPEG stream for a single camera by index (thumbnail)."""
    def generate():
        cap = _open_camera(index)
        if not cap.isOpened():
            return
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                thumb = cv2.resize(frame, (426, 240))
                _, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 60])
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
                )
        finally:
            cap.release()

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/cameras/feed/{role}")
def camera_feed_by_role(role: str):
    """MJPEG stream for a camera role."""
    from vision.camera import apply_picture_settings

    _, raw = _read_machine_params_config(require_exists=True)
    cameras_section = raw.get("cameras", {})
    picture_settings = parseCameraPictureSettings(_get_picture_settings_table(raw).get(role))
    source = cameras_section.get(role)
    if source is None or not isinstance(source, (int, str)):
        raise HTTPException(404, f"Camera role '{role}' not configured")

    def _encode_chunk(frame: np.ndarray) -> bytes:
        _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        return (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        )

    if vision_manager is not None and hasattr(vision_manager, "getCaptureThreadForRole"):
        try:
            capture = vision_manager.getCaptureThreadForRole(role)
        except Exception:
            capture = None
        if capture is not None and hasattr(vision_manager, "getFrame"):
            def generate_live():
                while True:
                    frame_obj = vision_manager.getFrame(role)
                    if frame_obj is None:
                        time.sleep(0.05)
                        continue
                    frame = frame_obj.annotated if frame_obj.annotated is not None else frame_obj.raw
                    yield _encode_chunk(frame)
                    time.sleep(0.03)

            return StreamingResponse(
                generate_live(),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

    def generate_direct():
        cap = _open_camera_source(source)
        if not cap.isOpened():
            return
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frame = apply_picture_settings(frame, picture_settings)
                yield _encode_chunk(frame)
        finally:
            cap.release()

    return StreamingResponse(
        generate_direct(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


class CameraAssignment(BaseModel):
    c_channel_2: Optional[int] = None
    c_channel_3: Optional[int] = None
    carousel: Optional[int | str] = None
    classification_top: Optional[int | str] = None
    classification_bottom: Optional[int | str] = None


class CameraPictureSettingsPayload(BaseModel):
    brightness: int = 0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    rotation: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False


@app.post("/api/cameras/assign")
def assign_cameras(assignment: CameraAssignment) -> Dict[str, Any]:
    """Save camera role assignments to the machine TOML config."""
    params_path, config = _read_machine_params_config()

    # Update cameras section
    cameras = config.get("cameras", {})
    updates = assignment.model_dump(exclude_unset=True)
    if updates:
        cameras["layout"] = "split_feeder"
    for key, value in updates.items():
        if value is None:
            cameras.pop(key, None)
        else:
            cameras[key] = value
    config["cameras"] = cameras

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live: Dict[str, bool] = {}
    if vision_manager is not None and hasattr(vision_manager, "setCameraSourceForRole"):
        for key, value in updates.items():
            try:
                applied_live[key] = bool(vision_manager.setCameraSourceForRole(key, value))
            except Exception:
                applied_live[key] = False

    return {
        "ok": True,
        "assignment": {
            "c_channel_2": cameras.get("c_channel_2"),
            "c_channel_3": cameras.get("c_channel_3"),
            "carousel": cameras.get("carousel"),
            "classification_top": cameras.get("classification_top"),
            "classification_bottom": cameras.get("classification_bottom"),
        },
        "applied_live": applied_live,
        "message": (
            "Camera assignment updated live."
            if updates and all(applied_live.get(key, False) for key in updates.keys())
            else "Camera assignment saved."
        ),
    }


@app.get("/api/cameras/picture-settings/{role}")
def get_camera_picture_settings(role: str) -> Dict[str, Any]:
    """Return persisted picture settings for a camera role."""
    _, config = _read_machine_params_config()
    return {
        "role": role,
        "settings": _picture_settings_for_role(config, role),
    }


@app.post("/api/cameras/picture-settings/{role}")
def save_camera_picture_settings(
    role: str,
    payload: CameraPictureSettingsPayload,
) -> Dict[str, Any]:
    """Save and live-apply picture settings for a camera role when possible."""
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")

    params_path, config = _read_machine_params_config()
    picture_settings = _get_picture_settings_table(config)
    parsed = parseCameraPictureSettings(payload.model_dump())
    picture_settings[role] = cameraPictureSettingsToDict(parsed)
    config["camera_picture_settings"] = picture_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    applied_live = False
    if vision_manager is not None and hasattr(vision_manager, "setPictureSettingsForRole"):
        try:
            applied_live = bool(vision_manager.setPictureSettingsForRole(role, parsed))
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "settings": cameraPictureSettingsToDict(parsed),
        "applied_live": applied_live,
        "message": "Picture settings saved.",
    }


# --- Polygon editor endpoints ---

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
