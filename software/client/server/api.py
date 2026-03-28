from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any, Callable
import asyncio
import json
import queue
import time
import threading
from uuid import uuid4
import cv2
import numpy as np
from pathlib import Path
import platform
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

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
    cameraColorProfileToDict,
    cameraDeviceSettingsToDict,
    parseCameraPictureSettings,
    parseCameraColorProfile,
    parseCameraDeviceSettings,
    cameraPictureSettingsToDict,
)
from irl.parse_user_toml import (
    DEFAULT_CHUTE_FIRST_BIN_CENTER,
    DEFAULT_CHUTE_PILLAR_WIDTH_DEG,
    DEFAULT_SERVO_CLOSED_ANGLE,
    DEFAULT_SERVO_OPEN_ANGLE,
)
from hardware.macos_camera_registry import refresh_macos_cameras
from server.camera_calibration import analyze_calibration_target, generate_color_profile_from_analysis
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
camera_device_preview_overrides: Dict[str, Dict[str, int | float | bool]] = {}
camera_calibration_tasks: Dict[str, Dict[str, Any]] = {}
camera_calibration_tasks_lock = threading.Lock()


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
    endstop_active_high: bool = True


class CarouselHardwareSettingsPayload(BaseModel):
    endstop_active_high: bool = False
    stepper_direction_inverted: bool = False


class ServoLayerPreviewPayload(BaseModel):
    invert: bool = False
    is_open: bool = False


class StorageLayerSettingsPayload(BaseModel):
    layer_bin_counts: List[int] = []


ALLOWED_STORAGE_LAYER_BIN_COUNTS = [12, 18, 30]
DEFAULT_STORAGE_LAYER_SECTION_COUNT = 6
CAROUSEL_HOME_PIN_CHANNEL = 2
DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH = False
CAROUSEL_HOME_SPEED_MICROSTEPS_PER_SEC = 400
CAROUSEL_HOME_SPEED_SLOW_MICROSTEPS_PER_SEC = 100
CAROUSEL_BACKOFF_STEPS = 200
CAROUSEL_HOME_PASSES = 3
CAROUSEL_HOME_TIMEOUT_MS = 30000
CAROUSEL_CALIBRATE_TIMEOUT_MS = 60000


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
        "carousel": _carousel_settings_from_config(config),
    }


@app.get("/api/hardware-config/servo/live")
def get_live_servo_feedback() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    servo_settings = _servo_settings_from_config(config)
    layer_count = int(servo_settings.get("layer_count", 0))

    if controller_ref is None or not hasattr(controller_ref, "irl"):
        return {
            "ok": True,
            "backend": servo_settings["backend"],
            "live_available": False,
            "layers": [],
        }

    servos = list(getattr(controller_ref.irl, "servos", []))
    return {
        "ok": True,
        "backend": servo_settings["backend"],
        "live_available": len(servos) > 0,
        "layers": [
            _live_servo_feedback_for_layer(index, servos[index] if index < len(servos) else None)
            for index in range(layer_count)
        ],
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
        feedback = _live_servo_feedback_for_layer(layer_index, servo)
        is_open = bool(feedback.get("is_open")) if feedback.get("available") else False
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to toggle layer {layer_index + 1} servo: {e}")

    return {
        "ok": True,
        "layer_index": layer_index,
        "is_open": is_open,
        "feedback": feedback,
        "message": (
            f"Layer {layer_index + 1} servo opened."
            if is_open
            else f"Layer {layer_index + 1} servo closed."
        ),
    }


@app.post("/api/hardware-config/servo/layers/{layer_index}/preview")
def preview_layer_servo(
    layer_index: int,
    payload: ServoLayerPreviewPayload,
) -> Dict[str, Any]:
    servo = _live_servo_for_layer(layer_index)
    _, config = _read_machine_params_config()
    servo_settings = _servo_settings_from_config(config)
    backend = servo_settings["backend"]
    open_angle = int(servo_settings["open_angle"])
    closed_angle = int(servo_settings["closed_angle"])
    desired_open = bool(payload.is_open)
    invert = bool(payload.invert)

    try:
        if backend == "waveshare":
            if hasattr(servo, "set_invert"):
                servo.set_invert(invert)
        elif hasattr(servo, "set_preset_angles"):
            if invert:
                servo.set_preset_angles(closed_angle, open_angle)
            else:
                servo.set_preset_angles(open_angle, closed_angle)

        if desired_open:
            if hasattr(servo, "open"):
                servo.open()
        else:
            if hasattr(servo, "close"):
                servo.close()
        feedback = _live_servo_feedback_for_layer(layer_index, servo)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to preview invert on layer {layer_index + 1}: {e}",
        )

    return {
        "ok": True,
        "layer_index": layer_index,
        "is_open": desired_open,
        "invert": invert,
        "feedback": feedback,
        "message": (
            f"Layer {layer_index + 1} preview updated to {'open' if desired_open else 'closed'} "
            f"with invert {'on' if invert else 'off'}."
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
        feedback = _live_servo_feedback_for_layer(layer_index, servo)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calibrate layer {layer_index + 1} servo: {e}")

    return {
        "ok": True,
        "layer_index": layer_index,
        "limits": {"min": min_limit, "max": max_limit},
        "feedback": feedback,
        "message": f"Layer {layer_index + 1} servo calibrated.",
    }


@app.post("/api/hardware-config/chute")
def save_chute_hardware_config(
    payload: ChuteHardwareSettingsPayload,
) -> Dict[str, Any]:
    first_bin_center = float(payload.first_bin_center)
    pillar_width_deg = float(payload.pillar_width_deg)
    endstop_active_high = bool(payload.endstop_active_high)
    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        raise HTTPException(
            status_code=400,
            detail="pillar_width_deg must be between 0 and less than 60 degrees",
        )

    params_path, config = _read_machine_params_config()
    config["chute"] = {
        "first_bin_center": first_bin_center,
        "pillar_width_deg": pillar_width_deg,
        "endstop_active_high": endstop_active_high,
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
                chute.setCalibration(first_bin_center, pillar_width_deg, endstop_active_high)
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


@app.get("/api/hardware-config/chute/live")
def get_live_chute_status() -> Dict[str, Any]:
    return _live_chute_status()


@app.post("/api/hardware-config/chute/calibrate/find-endstop")
def calibrate_chute_find_endstop() -> Dict[str, Any]:
    if controller_ref is None or not hasattr(controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Chute controller not initialized.")

    chute = getattr(controller_ref.irl, "chute", None)
    if chute is None or not hasattr(chute, "home"):
        raise HTTPException(status_code=503, detail="Chute subsystem unavailable.")

    try:
        homed = bool(chute.home())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find chute endstop: {e}")
    if not homed:
        raise HTTPException(
            status_code=409,
            detail="Chute homing stopped before the endstop triggered.",
        )

    return {
        "ok": True,
        "status": _live_chute_status(),
        "message": "Step 1 complete. Chute moved slowly until the endstop was found and re-homed.",
    }


@app.post("/api/hardware-config/chute/calibrate/cancel")
def cancel_chute_find_endstop() -> Dict[str, Any]:
    try:
        stop_all_steppers()
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return {
        "ok": True,
        "status": _live_chute_status(),
        "message": "Chute homing canceled. All steppers were stopped for safety.",
    }


@app.get("/api/hardware-config/carousel/live")
def get_live_carousel_status() -> Dict[str, Any]:
    return _live_carousel_status()


@app.get("/api/hardware-config/carousel")
def get_carousel_hardware_config() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    return _carousel_settings_from_config(config)


@app.post("/api/hardware-config/carousel")
def save_carousel_hardware_config(
    payload: CarouselHardwareSettingsPayload,
) -> Dict[str, Any]:
    endstop_active_high = bool(payload.endstop_active_high)
    stepper_direction_inverted = bool(payload.stepper_direction_inverted)

    params_path, config = _read_machine_params_config()
    carousel_config = config.get("carousel", {})
    if not isinstance(carousel_config, dict):
        carousel_config = {}
    carousel_config = {**carousel_config, "endstop_active_high": endstop_active_high}
    config["carousel"] = carousel_config

    stepper_direction_inverts = config.get("stepper_direction_inverts", {})
    if not isinstance(stepper_direction_inverts, dict):
        stepper_direction_inverts = {}
    stepper_direction_inverts = {
        **stepper_direction_inverts,
        "carousel": stepper_direction_inverted,
    }
    config["stepper_direction_inverts"] = stepper_direction_inverts

    try:
        _write_machine_params_config(params_path, config)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {e}")

    if controller_ref is not None and hasattr(controller_ref, "irl"):
        stepper = getattr(controller_ref.irl, "carousel_stepper", None)
        if stepper is not None and hasattr(stepper, "set_direction_inverted"):
            try:
                stepper.set_direction_inverted(stepper_direction_inverted)
            except Exception as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Settings were saved, but live direction inversion could not be applied: {e}",
                )

    return {
        "ok": True,
        "settings": _carousel_settings_from_config(config),
        "status": _live_carousel_status(),
        "message": "Carousel settings saved.",
    }


@app.post("/api/hardware-config/carousel/home")
def home_carousel_to_endstop() -> Dict[str, Any]:
    if controller_ref is None or not hasattr(controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Carousel controller not initialized.")

    irl = controller_ref.irl
    interfaces = getattr(irl, "interfaces", {})
    feeder_board = interfaces.get("FEEDER MB") if isinstance(interfaces, dict) else None
    if feeder_board is None:
        raise HTTPException(status_code=503, detail="Feeder board not initialized.")

    digital_inputs = list(getattr(feeder_board, "digital_inputs", []))
    if CAROUSEL_HOME_PIN_CHANNEL < 0 or CAROUSEL_HOME_PIN_CHANNEL >= len(digital_inputs):
        raise HTTPException(
            status_code=503,
            detail=f"Carousel home input channel {CAROUSEL_HOME_PIN_CHANNEL} is unavailable.",
        )

    _, config = _read_machine_params_config()
    endstop_active_high = bool(
        _carousel_settings_from_config(config).get("endstop_active_high", DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH)
    )

    stepper = getattr(irl, "carousel_stepper", None)
    if stepper is None:
        raise HTTPException(status_code=503, detail="Carousel stepper unavailable.")

    home_pin = digital_inputs[CAROUSEL_HOME_PIN_CHANNEL]

    def _read_endstop() -> bool:
        raw = bool(home_pin.value)
        return raw if endstop_active_high else not raw

    def _home_and_wait(speed: int, timeout_ms: int) -> None:
        """Issue firmware home command, wait for stop, verify endstop."""
        stepper.home(speed, home_pin, home_pin_active_high=endstop_active_high)
        start = time.monotonic()
        while not stepper.stopped:
            if (time.monotonic() - start) * 1000 > timeout_ms:
                stepper.move_at_speed(0)
                raise TimeoutError("Carousel homing timed out.")
            time.sleep(0.01)
        if not _read_endstop():
            raise HTTPException(
                status_code=409,
                detail="Carousel homing stopped before the endstop triggered.",
            )

    try:
        stepper.enabled = True

        # Pass 1: fast approach
        _home_and_wait(CAROUSEL_HOME_SPEED_MICROSTEPS_PER_SEC, CAROUSEL_HOME_TIMEOUT_MS)

        # Passes 2..N: back off then slow approach for precision
        for _ in range(CAROUSEL_HOME_PASSES - 1):
            stepper.move_steps_blocking(-CAROUSEL_BACKOFF_STEPS, timeout_ms=5000)
            _home_and_wait(CAROUSEL_HOME_SPEED_SLOW_MICROSTEPS_PER_SEC, CAROUSEL_HOME_TIMEOUT_MS)

        stepper.position_degrees = 0.0
        # Keep stepper enabled to hold position
    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to home carousel to endstop: {e}")

    return {
        "ok": True,
        "status": _live_carousel_status(),
        "message": f"Carousel homed ({CAROUSEL_HOME_PASSES}-pass) and zeroed.",
    }


@app.post("/api/hardware-config/carousel/calibrate")
def calibrate_carousel() -> Dict[str, Any]:
    """Calibrate carousel by measuring steps for one full revolution."""
    if controller_ref is None or not hasattr(controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Carousel controller not initialized.")

    irl = controller_ref.irl
    interfaces = getattr(irl, "interfaces", {})
    feeder_board = interfaces.get("FEEDER MB") if isinstance(interfaces, dict) else None
    if feeder_board is None:
        raise HTTPException(status_code=503, detail="Feeder board not initialized.")

    digital_inputs = list(getattr(feeder_board, "digital_inputs", []))
    if CAROUSEL_HOME_PIN_CHANNEL < 0 or CAROUSEL_HOME_PIN_CHANNEL >= len(digital_inputs):
        raise HTTPException(
            status_code=503,
            detail=f"Carousel home input channel {CAROUSEL_HOME_PIN_CHANNEL} is unavailable.",
        )

    _, config = _read_machine_params_config()
    endstop_active_high = bool(
        _carousel_settings_from_config(config).get("endstop_active_high", DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH)
    )

    stepper = getattr(irl, "carousel_stepper", None)
    if stepper is None:
        raise HTTPException(status_code=503, detail="Carousel stepper unavailable.")

    home_pin_obj = digital_inputs[CAROUSEL_HOME_PIN_CHANNEL]

    def _read_endstop() -> bool:
        raw = bool(home_pin_obj.value)
        return raw if endstop_active_high else not raw

    if not _read_endstop():
        raise HTTPException(
            status_code=409,
            detail="Carousel must be homed first (endstop not currently triggered).",
        )

    try:
        stepper.enabled = True

        # Back off the endstop
        stepper.move_steps_blocking(-CAROUSEL_BACKOFF_STEPS, timeout_ms=5000)

        # Zero position counter at this point
        stepper.position = 0

        # Move CW until endstop triggers again (full rotation) using firmware home
        stepper.home(
            CAROUSEL_HOME_SPEED_MICROSTEPS_PER_SEC,
            home_pin_obj,
            home_pin_active_high=endstop_active_high,
        )
        start = time.monotonic()
        while not stepper.stopped:
            if (time.monotonic() - start) * 1000 > CAROUSEL_CALIBRATE_TIMEOUT_MS:
                stepper.move_at_speed(0)
                raise TimeoutError("Carousel calibration timed out.")
            time.sleep(0.01)

        if not _read_endstop():
            raise HTTPException(
                status_code=409,
                detail="Calibration failed: endstop did not trigger after full rotation.",
            )

        measured_steps = abs(stepper.position)

        # Save to config
        params_path, config = _read_machine_params_config()
        carousel_config = config.get("carousel", {})
        if not isinstance(carousel_config, dict):
            carousel_config = {}
        carousel_config["steps_per_revolution"] = measured_steps
        config["carousel"] = carousel_config
        _write_machine_params_config(params_path, config)

        # Update stepper in-memory
        stepper.steps_per_revolution = measured_steps

        # Re-zero position at the endstop
        stepper.position_degrees = 0.0

    except HTTPException:
        raise
    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Calibration failed: {e}")

    return {
        "ok": True,
        "steps_per_revolution": measured_steps,
        "degrees": 360,
        "status": _live_carousel_status(),
        "message": f"Calibrated: {measured_steps} steps/revolution.",
    }


@app.post("/api/hardware-config/carousel/home/cancel")
def cancel_carousel_home_to_endstop() -> Dict[str, Any]:
    try:
        stop_all_steppers()
    except HTTPException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    return {
        "ok": True,
        "status": _live_carousel_status(),
        "message": "Carousel homing canceled. All steppers were stopped for safety.",
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


class StepperMoveDegreesResponse(BaseModel):
    success: bool
    stepper: str
    degrees: float
    speed: int


class StepperStopResponse(BaseModel):
    success: bool
    stepper: str


class StepperStopAllResponse(BaseModel):
    success: bool
    steppers: List[str]


def _stepper_mapping() -> Dict[str, Any]:
    if controller_ref is None or not hasattr(controller_ref, "irl"):
        raise HTTPException(status_code=500, detail="Controller not initialized")

    irl = controller_ref.irl
    return {
        "c_channel_1": getattr(irl, "c_channel_1_rotor_stepper", None),
        "c_channel_2": getattr(irl, "c_channel_2_rotor_stepper", None),
        "c_channel_3": getattr(irl, "c_channel_3_rotor_stepper", None),
        "carousel": getattr(irl, "carousel_stepper", None),
        "chute": getattr(irl, "chute_stepper", None),
    }


def _resolve_stepper(stepper_name: str) -> Any:
    mapping = _stepper_mapping()

    if stepper_name not in mapping:
        raise HTTPException(status_code=400, detail=f"Unknown stepper '{stepper_name}'")

    stepper = mapping[stepper_name]
    if stepper is None:
        raise HTTPException(status_code=500, detail=f"Stepper '{stepper_name}' unavailable")
    return stepper


def _halt_stepper(stepper: Any) -> None:
    errors: list[str] = []
    stopped = False

    if hasattr(stepper, "move_at_speed"):
        try:
            result = stepper.move_at_speed(0)
            stopped = stopped or bool(result)
            if result is False:
                errors.append("move_at_speed(0) was not acknowledged")
        except Exception as e:
            errors.append(f"move_at_speed(0) failed: {e}")

    if hasattr(stepper, "stop"):
        try:
            stepper.stop()
            stopped = True
        except Exception as e:
            errors.append(f"stop() failed: {e}")

    if hasattr(stepper, "enabled"):
        try:
            stepper.enabled = False
            stopped = True
        except Exception as e:
            errors.append(f"disable failed: {e}")

    if not stopped:
        detail = "; ".join(errors) if errors else "No supported stop method found"
        raise RuntimeError(detail)


def _stop_stepper_after_delay(stepper: Any, delay_s: float, lock: threading.Lock) -> None:
    try:
        time.sleep(delay_s)
        _halt_stepper(stepper)
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


@app.post("/stepper/move-degrees", response_model=StepperMoveDegreesResponse)
def move_stepper_degrees(
    stepper: str,
    degrees: float,
    speed: int = 800,
) -> StepperMoveDegreesResponse:
    if degrees == 0:
        raise HTTPException(status_code=400, detail="degrees must be non-zero")
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")

    target = _resolve_stepper(stepper)

    lock = pulse_locks.setdefault(stepper, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is already moving")

    try:
        target.enabled = True
        target.set_speed_limits(min_speed=speed, max_speed=speed)
        target.move_degrees(degrees)
    except Exception as e:
        lock.release()
        raise HTTPException(status_code=500, detail=f"Move failed: {e}")

    def _release_after_move():
        try:
            start = time.monotonic()
            while not target.stopped and (time.monotonic() - start) < 30:
                time.sleep(0.02)
        finally:
            lock.release()

    threading.Thread(target=_release_after_move, daemon=True).start()

    return StepperMoveDegreesResponse(
        success=True,
        stepper=stepper,
        degrees=degrees,
        speed=speed,
    )


@app.post("/stepper/stop", response_model=StepperStopResponse)
def stop_stepper(stepper: str) -> StepperStopResponse:
    target = _resolve_stepper(stepper)

    try:
        _halt_stepper(target)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stop failed: {e}")

    return StepperStopResponse(success=True, stepper=stepper)


@app.post("/stepper/stop-all", response_model=StepperStopAllResponse)
def stop_all_steppers() -> StepperStopAllResponse:
    halted: list[str] = []
    errors: Dict[str, str] = {}

    for name, stepper in _stepper_mapping().items():
        if stepper is None:
            continue
        try:
            _halt_stepper(stepper)
            halted.append(name)
        except Exception as e:
            errors[name] = str(e)

    if errors:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "One or more steppers failed to stop.",
                "errors": errors,
                "stopped": halted,
            },
        )

    return StepperStopAllResponse(success=True, steppers=halted)


# --- TMC2209 Driver Settings ---

TMC_REG_GCONF = 0x00
TMC_REG_IHOLD_IRUN = 0x10
TMC_REG_TCOOLTHRS = 0x14
TMC_REG_COOLCONF = 0x42
TMC_REG_CHOPCONF = 0x6C
TMC_REG_DRV_STATUS = 0x6F

MRES_TO_MICROSTEPS = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1}
MICROSTEPS_TO_MRES = {v: k for k, v in MRES_TO_MICROSTEPS.items()}


def _parse_drv_status(raw: int) -> Dict[str, Any]:
    return {
        "ot": bool(raw & (1 << 1)),
        "otpw": bool(raw & (1 << 0)),
        "s2ga": bool(raw & (1 << 2)),
        "s2gb": bool(raw & (1 << 3)),
        "ola": bool(raw & (1 << 4)),
        "olb": bool(raw & (1 << 5)),
        "stst": bool(raw & (1 << 31)),
        "stealth": bool(raw & (1 << 30)),
        "cs_actual": (raw >> 16) & 0x1F,
        "sg_result": (raw >> 10) & 0x3FF,
    }


def _parse_ihold_irun(raw: int) -> Dict[str, int]:
    return {
        "ihold": raw & 0x1F,
        "irun": (raw >> 8) & 0x1F,
        "ihold_delay": (raw >> 16) & 0x0F,
    }


def _parse_chopconf_mres(raw: int) -> int:
    mres = (raw >> 24) & 0x0F
    return MRES_TO_MICROSTEPS.get(mres, 256)


def _safe_read_register(stepper: Any, addr: int) -> Optional[int]:
    try:
        return stepper.read_driver_register(addr)
    except Exception:
        return None


@app.get("/api/stepper/{name}/tmc")
def get_tmc_settings(name: str) -> Dict[str, Any]:
    stepper = _resolve_stepper(name)

    gconf_raw = _safe_read_register(stepper, TMC_REG_GCONF)
    ihold_irun_raw = _safe_read_register(stepper, TMC_REG_IHOLD_IRUN)
    chopconf_raw = _safe_read_register(stepper, TMC_REG_CHOPCONF)
    coolconf_raw = _safe_read_register(stepper, TMC_REG_COOLCONF)
    drv_status_raw = _safe_read_register(stepper, TMC_REG_DRV_STATUS)

    result: Dict[str, Any] = {}

    if ihold_irun_raw is not None:
        parsed = _parse_ihold_irun(ihold_irun_raw)
        result["irun"] = parsed["irun"]
        result["ihold"] = parsed["ihold"]
    else:
        result["irun"] = None
        result["ihold"] = None

    if chopconf_raw is not None:
        result["microsteps"] = _parse_chopconf_mres(chopconf_raw)
    else:
        result["microsteps"] = None

    if gconf_raw is not None:
        result["stealthchop"] = not bool(gconf_raw & (1 << 2))
    else:
        result["stealthchop"] = None

    if coolconf_raw is not None:
        result["coolstep"] = (coolconf_raw & 0x0F) > 0  # semin > 0
    else:
        result["coolstep"] = None

    if drv_status_raw is not None:
        result["drv_status"] = _parse_drv_status(drv_status_raw)
    else:
        result["drv_status"] = None

    return result


class TmcSettingsRequest(BaseModel):
    irun: Optional[int] = None
    ihold: Optional[int] = None
    microsteps: Optional[int] = None
    stealthchop: Optional[bool] = None
    coolstep: Optional[bool] = None


@app.post("/api/stepper/{name}/tmc")
def set_tmc_settings(name: str, body: TmcSettingsRequest) -> Dict[str, Any]:
    stepper = _resolve_stepper(name)

    if body.irun is not None or body.ihold is not None:
        ihold_irun_raw = _safe_read_register(stepper, TMC_REG_IHOLD_IRUN)
        if ihold_irun_raw is not None:
            current = _parse_ihold_irun(ihold_irun_raw)
        else:
            current = {"irun": 16, "ihold": 8, "ihold_delay": 1}
        irun = body.irun if body.irun is not None else current["irun"]
        ihold = body.ihold if body.ihold is not None else current["ihold"]
        if not (0 <= irun <= 31):
            raise HTTPException(status_code=400, detail="irun must be 0-31")
        if not (0 <= ihold <= 31):
            raise HTTPException(status_code=400, detail="ihold must be 0-31")
        stepper.set_current(irun, ihold, current["ihold_delay"])

    if body.microsteps is not None:
        if body.microsteps not in MICROSTEPS_TO_MRES:
            raise HTTPException(status_code=400, detail=f"microsteps must be one of {sorted(MICROSTEPS_TO_MRES.keys())}")
        stepper.set_microsteps(body.microsteps)

    if body.stealthchop is not None:
        gconf_raw = _safe_read_register(stepper, TMC_REG_GCONF)
        if gconf_raw is not None:
            if body.stealthchop:
                gconf_raw &= ~(1 << 2)  # clear EN_SPREADCYCLE
            else:
                gconf_raw |= (1 << 2)   # set EN_SPREADCYCLE
            stepper.write_driver_register(TMC_REG_GCONF, gconf_raw)

    if body.coolstep is not None:
        if body.coolstep:
            # semin=5, semax=2, seup=1(=2 increments), sedn=0(=32 steps)
            coolconf = (5 & 0x0F) | ((2 & 0x0F) << 8) | ((1 & 0x03) << 5) | ((0 & 0x03) << 13)
            stepper.write_driver_register(TMC_REG_COOLCONF, coolconf)
            stepper.write_driver_register(TMC_REG_TCOOLTHRS, 0xFFFFF)
        else:
            stepper.write_driver_register(TMC_REG_COOLCONF, 0)
            stepper.write_driver_register(TMC_REG_TCOOLTHRS, 0)

    return get_tmc_settings(name)


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


def _get_camera_device_settings_table(config: Dict[str, Any]) -> Dict[str, Any]:
    device_settings = config.get("camera_device_settings", {})
    return device_settings if isinstance(device_settings, dict) else {}


def _get_camera_color_profile_table(config: Dict[str, Any]) -> Dict[str, Any]:
    profiles = config.get("camera_color_profiles", {})
    return profiles if isinstance(profiles, dict) else {}


def _camera_source_for_role(config: Dict[str, Any], role: str) -> int | str | None:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")

    cameras = config.get("cameras", {})
    if isinstance(cameras, dict):
        source = cameras.get(role)
        if isinstance(source, (int, str)):
            return source

    if role in {"feeder", "classification_top", "classification_bottom"}:
        camera_setup = getCameraSetup()
        if isinstance(camera_setup, dict):
            fallback_source = camera_setup.get(role)
            if isinstance(fallback_source, int):
                return fallback_source
    return None


def _android_camera_base_url(source: int | str | None) -> str | None:
    if not isinstance(source, str):
        return None
    try:
        parsed = urllib_parse.urlparse(source)
    except Exception:
        return None
    if not parsed.scheme or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _android_camera_request(
    source: int | str | None,
    path: str,
    *,
    method: str = "GET",
    payload: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    base_url = _android_camera_base_url(source)
    if base_url is None:
        raise HTTPException(status_code=400, detail="Camera source is not an Android camera app URL.")

    url = f"{base_url}{path}"
    data = None
    headers: Dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib_request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib_request.urlopen(request, timeout=4) as response:
            body = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=detail or f"Android camera app returned HTTP {exc.code}.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Android camera app: {exc}")

    try:
        parsed = json.loads(body)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Android camera app returned invalid JSON: {exc}")

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Android camera app returned an unexpected response.")

    return parsed


def _android_camera_bytes_request(source: int | str | None, path: str) -> bytes:
    base_url = _android_camera_base_url(source)
    if base_url is None:
        raise HTTPException(status_code=400, detail="Camera source is not an Android camera app URL.")

    url = f"{base_url}{path}"
    request = urllib_request.Request(url, method="GET")
    try:
        with urllib_request.urlopen(request, timeout=4) as response:
            return response.read()
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise HTTPException(status_code=502, detail=detail or f"Android camera app returned HTTP {exc.code}.")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach Android camera app: {exc}")


def _live_usb_device_controls(
    role: str,
    source: int,
    saved_settings: Dict[str, int | float | bool],
) -> tuple[List[Dict[str, Any]], Dict[str, int | float | bool]]:
    from vision.camera import probe_camera_device_controls

    if vision_manager is not None and hasattr(vision_manager, "getCaptureThreadForRole"):
        try:
            capture = vision_manager.getCaptureThreadForRole(role)
        except Exception:
            capture = None
        if capture is not None and hasattr(capture, "describeDeviceControls"):
            try:
                controls, live_settings = capture.describeDeviceControls()
                if controls:
                    return controls, cameraDeviceSettingsToDict(live_settings)
            except Exception:
                pass

    controls, current_settings = probe_camera_device_controls(source, saved_settings)
    return controls, cameraDeviceSettingsToDict(current_settings)


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _quantize_numeric_value(value: float, min_value: float, step: float | None) -> float:
    if not isinstance(step, (int, float)) or step <= 0:
        return float(value)
    return float(min_value + round((value - min_value) / float(step)) * float(step))


def _numeric_control_candidates(
    control: Dict[str, Any],
    current: Any,
    *,
    count: int,
    prefer_log: bool = False,
    preferred_values: List[float] | None = None,
) -> List[float]:
    min_value = _as_number(control.get("min"))
    max_value = _as_number(control.get("max"))
    if min_value is None or max_value is None:
        current_value = _as_number(current)
        return [current_value] if current_value is not None else []

    step = _as_number(control.get("step"))
    values: List[float] = []
    current_value = _as_number(current)
    default_value = _as_number(control.get("default"))

    if prefer_log and min_value > 0 and max_value / max(min_value, 1e-6) >= 16:
        generated = np.geomspace(min_value, max_value, num=max(count, 2))
    else:
        generated = np.linspace(min_value, max_value, num=max(count, 2))

    values.extend(float(v) for v in generated.tolist())
    if preferred_values:
        values.extend(float(v) for v in preferred_values)
    if current_value is not None:
        values.append(current_value)
    if default_value is not None:
        values.append(default_value)
    values.extend([min_value, max_value])

    normalized: List[float] = []
    seen: set[float] = set()
    for raw in values:
        clipped = max(min_value, min(max_value, float(raw)))
        quantized = _quantize_numeric_value(clipped, min_value, step)
        rounded = round(quantized, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        normalized.append(int(round(quantized)) if step is not None and step >= 1 else float(quantized))

    normalized.sort(key=float)
    return normalized


def _focused_numeric_control_candidates(
    control: Dict[str, Any],
    current: Any,
    *,
    count: int,
    prefer_log: bool = False,
    relative_span: float = 0.35,
    linear_span_fraction: float = 0.12,
) -> List[float]:
    min_value = _as_number(control.get("min"))
    max_value = _as_number(control.get("max"))
    current_value = _as_number(current)
    if min_value is None or max_value is None or current_value is None:
        return _numeric_control_candidates(control, current, count=count, prefer_log=prefer_log)

    step = _as_number(control.get("step"))
    if prefer_log and current_value > 0:
        low = max(min_value, current_value * (1.0 - relative_span))
        high = min(max_value, current_value * (1.0 + relative_span))
        if high <= low:
            values = [current_value]
        else:
            values = np.geomspace(low, high, num=max(count, 3)).tolist()
    else:
        span = max(
            float(step) if step is not None else 0.0,
            (max_value - min_value) * linear_span_fraction,
        )
        low = max(min_value, current_value - span)
        high = min(max_value, current_value + span)
        if high <= low:
            values = [current_value]
        else:
            values = np.linspace(low, high, num=max(count, 3)).tolist()

    values.append(current_value)
    normalized: List[float] = []
    seen: set[float] = set()
    for raw in values:
        clipped = max(min_value, min(max_value, float(raw)))
        quantized = _quantize_numeric_value(clipped, min_value, step)
        rounded = round(quantized, 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        normalized.append(int(round(quantized)) if step is not None and step >= 1 else float(quantized))
    normalized.sort(key=float)
    return normalized


def _usb_control_defaults(
    controls: List[Dict[str, Any]],
    current_settings: Dict[str, int | float | bool],
) -> Dict[str, int | float | bool]:
    defaults: Dict[str, int | float | bool] = {}
    for control in controls:
        key = control.get("key")
        if not isinstance(key, str):
            continue
        default = control.get("default")
        if isinstance(default, (int, float, bool)) and not isinstance(default, bool):
            defaults[key] = float(default) if isinstance(default, float) or isinstance(default, int) else default
            continue
        if isinstance(default, bool):
            defaults[key] = default
            continue
        if key in {"auto_exposure", "auto_white_balance", "autofocus"} and isinstance(control.get("kind"), str):
            defaults[key] = True
            continue
        if key in current_settings:
            defaults[key] = current_settings[key]
            continue
        value = control.get("value")
        if isinstance(value, bool):
            defaults[key] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            defaults[key] = float(value)
    return defaults


def _capture_frame_for_calibration(
    role: str,
    source: int | str | None,
    *,
    after_timestamp: float | None = None,
    fallback_settings: Dict[str, int | float | bool] | None = None,
    picture_settings: Dict[str, Any] | None = None,
    color_profile: Dict[str, Any] | None = None,
) -> np.ndarray | None:
    from vision.camera import (
        apply_camera_color_profile,
        apply_camera_device_settings,
        apply_picture_settings,
    )

    parsed_picture_settings = parseCameraPictureSettings(picture_settings)
    parsed_color_profile = parseCameraColorProfile(color_profile)

    if isinstance(source, str):
        try:
            jpg = _android_camera_bytes_request(source, "/snapshot.jpg")
            buffer = np.frombuffer(jpg, dtype=np.uint8)
            frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            if frame is not None and frame.size > 0:
                frame = apply_camera_color_profile(frame, parsed_color_profile)
                frame = apply_picture_settings(frame, parsed_picture_settings)
                return frame
        except HTTPException:
            return None
        return None

    if not isinstance(source, int):
        return None

    cap = cv2.VideoCapture(source, cv2.CAP_AVFOUNDATION) if platform.system() == "Darwin" else cv2.VideoCapture(source)
    if not cap.isOpened():
        cap.release()
        return None

    try:
        if fallback_settings:
            apply_camera_device_settings(cap, fallback_settings, source=source)
            time.sleep(0.2)
        frame: np.ndarray | None = None
        for _ in range(4):
            ret, current = cap.read()
            if ret and current is not None:
                frame = current
        if frame is None:
            return None
        frame = apply_camera_color_profile(frame, parsed_color_profile)
        frame = apply_picture_settings(frame, parsed_picture_settings)
        return frame.copy()
    finally:
        cap.release()


def _analyze_candidate_settings(
    role: str,
    source: int | str | None,
    settings: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
    preview_started_at = time.time()
    preview = preview_camera_device_settings(role, settings)
    preview_settings = preview.get("settings", settings)
    if isinstance(source, str):
        applied_settings = dict(preview_settings) if isinstance(preview_settings, dict) else dict(settings)
    else:
        applied_settings = cameraDeviceSettingsToDict(
            parseCameraDeviceSettings(preview_settings)
        )
    time.sleep(0.35)
    frame = _capture_frame_for_calibration(
        role,
        source,
        after_timestamp=preview_started_at,
        fallback_settings=applied_settings,
    )
    if frame is None:
        return applied_settings, None
    analysis = analyze_calibration_target(frame)
    return applied_settings, analysis.to_dict() if analysis is not None else None


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


def _waveshare_available_servo_ids(config: Dict[str, Any]) -> List[int]:
    found_ids: set[int] = set()

    servo = config.get("servo", {})
    if isinstance(servo, dict):
        channels_raw = servo.get("channels", [])
        if isinstance(channels_raw, list):
            for item in channels_raw:
                if not isinstance(item, dict):
                    continue
                channel_id = item.get("id")
                if isinstance(channel_id, int) and not isinstance(channel_id, bool) and channel_id > 0:
                    found_ids.add(channel_id)

    live_servos = []
    if controller_ref is not None and hasattr(controller_ref, "irl"):
        live_servos = list(getattr(controller_ref.irl, "servos", []))
        for servo_obj in live_servos:
            channel = getattr(servo_obj, "channel", None)
            if isinstance(channel, int) and not isinstance(channel, bool) and channel > 0:
                found_ids.add(channel)

    scan_bus = None
    if live_servos:
        candidate_bus = getattr(live_servos[0], "_bus", None)
        if candidate_bus is not None and hasattr(candidate_bus, "scan"):
            scan_bus = candidate_bus

    if scan_bus is not None:
        try:
            found_ids.update(int(servo_id) for servo_id in scan_bus.scan(1, 32))
        except Exception:
            pass
        return sorted(found_ids)

    port = servo.get("port")
    if isinstance(port, str) and port.strip():
        try:
            from hardware.waveshare_servo import ScServoBus

            bus = ScServoBus(port.strip(), timeout=0.01)
            try:
                found_ids.update(int(servo_id) for servo_id in bus.scan(1, 32))
            finally:
                bus.close()
        except Exception:
            pass

    return sorted(found_ids)


def _live_servo_for_layer(layer_index: int) -> Any:
    if controller_ref is None or not hasattr(controller_ref, "irl"):
        raise HTTPException(status_code=503, detail="Servo controller not initialized.")

    servos = list(getattr(controller_ref.irl, "servos", []))
    if layer_index < 0 or layer_index >= len(servos):
        raise HTTPException(status_code=404, detail=f"Unknown storage layer {layer_index + 1}.")
    return servos[layer_index]


def _live_servo_feedback_for_layer(layer_index: int, servo: Any | None = None) -> Dict[str, Any]:
    servo = servo if servo is not None else _live_servo_for_layer(layer_index)
    channel = getattr(servo, "channel", None)
    base: Dict[str, Any] = {
        "layer_index": layer_index,
        "channel": channel,
        "available": False,
    }

    if hasattr(servo, "feedback"):
        try:
            feedback = servo.feedback()
            if isinstance(feedback, dict):
                return {
                    "layer_index": layer_index,
                    "available": True,
                    **feedback,
                }
        except Exception as e:
            return {**base, "error": str(e)}

    if not hasattr(servo, "position"):
        return base

    try:
        position = int(servo.position)
        return {
            **base,
            "available": True,
            "position": position,
            "is_open": bool(servo.isOpen()) if hasattr(servo, "isOpen") else None,
        }
    except Exception as e:
        return {**base, "error": str(e)}


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


def _live_chute_status() -> Dict[str, Any]:
    if controller_ref is None or not hasattr(controller_ref, "irl"):
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": None,
            "current_angle": None,
            "stepper_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "digital_inputs": [],
        }

    irl = controller_ref.irl
    chute = getattr(irl, "chute", None)
    stepper = getattr(irl, "chute_stepper", None)
    interfaces = getattr(irl, "interfaces", {})
    distribution_board = interfaces.get("DISTRIBUTION MB") if isinstance(interfaces, dict) else None
    if chute is None or stepper is None:
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": None,
            "current_angle": None,
            "stepper_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "digital_inputs": [],
        }

    status: Dict[str, Any] = {
        "live_available": True,
        "endstop_triggered": None,
        "raw_endstop_high": None,
        "endstop_active_high": getattr(chute, "endstop_active_high", True),
        "current_angle": None,
        "stepper_position_degrees": None,
        "stepper_microsteps": None,
        "stepper_stopped": None,
        "digital_inputs": [],
    }

    try:
        status["raw_endstop_high"] = bool(chute.home_pin.value)
        if hasattr(chute, "endstop_triggered"):
            status["endstop_triggered"] = bool(chute.endstop_triggered)
        elif status["raw_endstop_high"] is not None:
            active_high = bool(status["endstop_active_high"])
            status["endstop_triggered"] = (
                bool(status["raw_endstop_high"])
                if active_high
                else not bool(status["raw_endstop_high"])
            )
        status["home_pin_channel"] = getattr(chute.home_pin, "channel", None)
    except Exception as e:
        status["endstop_error"] = str(e)

    try:
        status["current_angle"] = float(chute.current_angle)
    except Exception as e:
        status["current_angle_error"] = str(e)

    try:
        status["stepper_position_degrees"] = float(stepper.position_degrees)
        status["stepper_microsteps"] = int(stepper.position)
    except Exception as e:
        status["stepper_position_error"] = str(e)

    try:
        status["stepper_stopped"] = bool(stepper.stopped)
    except Exception as e:
        status["stepper_stopped_error"] = str(e)

    if distribution_board is not None:
        try:
            status["digital_inputs"] = [
                {
                    "channel": index,
                    "raw_high": bool(pin.value),
                }
                for index, pin in enumerate(getattr(distribution_board, "digital_inputs", []))
            ]
        except Exception as e:
            status["digital_inputs_error"] = str(e)

    return status


def _live_carousel_status() -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    carousel_settings = _carousel_settings_from_config(config)
    endstop_active_high = bool(
        carousel_settings.get("endstop_active_high", DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH)
    )
    stepper_direction_inverted = bool(
        carousel_settings.get("stepper_direction_inverted", False)
    )

    if controller_ref is None or not hasattr(controller_ref, "irl"):
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": endstop_active_high,
            "stepper_direction_inverted": stepper_direction_inverted,
            "current_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "bound_stepper_name": None,
            "bound_stepper_channel": None,
            "digital_inputs": [],
            "home_pin_channel": CAROUSEL_HOME_PIN_CHANNEL,
        }

    irl = controller_ref.irl
    stepper = getattr(irl, "carousel_stepper", None)
    interfaces = getattr(irl, "interfaces", {})
    feeder_board = interfaces.get("FEEDER MB") if isinstance(interfaces, dict) else None

    if stepper is None or feeder_board is None:
        return {
            "live_available": False,
            "endstop_triggered": None,
            "raw_endstop_high": None,
            "endstop_active_high": endstop_active_high,
            "stepper_direction_inverted": stepper_direction_inverted,
            "current_position_degrees": None,
            "stepper_microsteps": None,
            "stepper_stopped": None,
            "bound_stepper_name": getattr(stepper, "hardware_name", None) if stepper is not None else None,
            "bound_stepper_channel": getattr(stepper, "channel", None) if stepper is not None else None,
            "digital_inputs": [],
            "home_pin_channel": CAROUSEL_HOME_PIN_CHANNEL,
        }

    status: Dict[str, Any] = {
        "live_available": True,
        "endstop_triggered": None,
        "raw_endstop_high": None,
        "endstop_active_high": endstop_active_high,
        "stepper_direction_inverted": stepper_direction_inverted,
        "current_position_degrees": None,
        "stepper_microsteps": None,
        "stepper_stopped": None,
        "bound_stepper_name": getattr(stepper, "hardware_name", None),
        "bound_stepper_channel": getattr(stepper, "channel", None),
        "digital_inputs": [],
        "home_pin_channel": CAROUSEL_HOME_PIN_CHANNEL,
    }

    digital_inputs = list(getattr(feeder_board, "digital_inputs", []))
    if 0 <= CAROUSEL_HOME_PIN_CHANNEL < len(digital_inputs):
        try:
            raw_high = bool(digital_inputs[CAROUSEL_HOME_PIN_CHANNEL].value)
            status["raw_endstop_high"] = raw_high
            status["endstop_triggered"] = raw_high if endstop_active_high else not raw_high
        except Exception as e:
            status["endstop_error"] = str(e)

    try:
        status["current_position_degrees"] = float(stepper.position_degrees)
        status["stepper_microsteps"] = int(stepper.position)
    except Exception as e:
        status["stepper_position_error"] = str(e)

    try:
        status["stepper_stopped"] = bool(stepper.stopped)
    except Exception as e:
        status["stepper_stopped_error"] = str(e)

    try:
        status["digital_inputs"] = [
            {
                "channel": index,
                "raw_high": bool(pin.value),
            }
            for index, pin in enumerate(digital_inputs)
        ]
    except Exception as e:
        status["digital_inputs_error"] = str(e)

    return status


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
        "available_channel_ids": (
            _pca_available_servo_channels()
            if backend == "pca9685"
            else _waveshare_available_servo_ids(config)
        ),
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
    endstop_active_high = chute.get("endstop_active_high", True)
    if not isinstance(endstop_active_high, bool):
        endstop_active_high = True

    if pillar_width_deg < 0 or pillar_width_deg >= 60:
        pillar_width_deg = DEFAULT_CHUTE_PILLAR_WIDTH_DEG

    return {
        "first_bin_center": first_bin_center,
        "pillar_width_deg": pillar_width_deg,
        "endstop_active_high": endstop_active_high,
    }


def _carousel_settings_from_config(config: Dict[str, Any]) -> Dict[str, Any]:
    carousel = config.get("carousel", {})
    if not isinstance(carousel, dict):
        carousel = {}

    endstop_active_high = carousel.get(
        "endstop_active_high",
        DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH,
    )
    if not isinstance(endstop_active_high, bool):
        endstop_active_high = DEFAULT_CAROUSEL_ENDSTOP_ACTIVE_HIGH

    stepper_direction_inverts = config.get("stepper_direction_inverts", {})
    if not isinstance(stepper_direction_inverts, dict):
        stepper_direction_inverts = {}
    stepper_direction_inverted = stepper_direction_inverts.get("carousel", False)
    if not isinstance(stepper_direction_inverted, bool):
        stepper_direction_inverted = False

    return {
        "endstop_active_high": endstop_active_high,
        "stepper_direction_inverted": stepper_direction_inverted,
        "home_pin_channel": CAROUSEL_HOME_PIN_CHANNEL,
    }


def _picture_settings_for_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    picture_settings = _get_picture_settings_table(config)
    return cameraPictureSettingsToDict(parseCameraPictureSettings(picture_settings.get(role)))


def _camera_color_profile_for_role(config: Dict[str, Any], role: str) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")
    profiles = _get_camera_color_profile_table(config)
    return cameraColorProfileToDict(parseCameraColorProfile(profiles.get(role)))


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


def _list_usb_cameras() -> List[Dict[str, Any]]:
    if platform.system() == "Darwin":
        enumerated = list(refresh_macos_cameras())
        if enumerated:
            cameras: List[Dict[str, Any]] = []
            for camera in enumerated:
                probed = _probe_camera_index(int(camera.index))
                cameras.append(
                    {
                        "kind": "usb",
                        "index": int(camera.index),
                        "name": str(camera.name),
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
    from vision.camera import (
        apply_camera_color_profile,
        apply_camera_device_settings,
        apply_picture_settings,
    )

    _, raw = _read_machine_params_config(require_exists=True)
    cameras_section = raw.get("cameras", {})
    picture_settings = parseCameraPictureSettings(_get_picture_settings_table(raw).get(role))
    color_profile = parseCameraColorProfile(_get_camera_color_profile_table(raw).get(role))
    saved_device_settings = parseCameraDeviceSettings(
        _get_camera_device_settings_table(raw).get(role)
    )
    preview_device_settings = camera_device_preview_overrides.get(role)
    device_settings = cameraDeviceSettingsToDict(
        preview_device_settings if preview_device_settings is not None else saved_device_settings
    )
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
            if isinstance(source, int) and device_settings:
                apply_camera_device_settings(cap, device_settings, source=source)
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                frame = apply_camera_color_profile(frame, color_profile)
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
        "message": "Feed orientation saved.",
    }


@app.get("/api/cameras/device-settings/{role}")
def get_camera_device_settings(role: str) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        return {
            "ok": True,
            "role": role,
            "source": None,
            "provider": "none",
            "settings": {},
            "controls": [],
            "supported": False,
            "message": "No camera is assigned to this role.",
        }

    if isinstance(source, str):
        try:
            android_data = _android_camera_request(source, "/camera-settings")
        except HTTPException as exc:
            return {
                "ok": True,
                "role": role,
                "source": source,
                "provider": "network-stream",
                "settings": {},
                "controls": [],
                "supported": False,
                "message": str(exc.detail),
            }

        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": android_data.get("provider", "android-camera-app"),
            "settings": android_data.get("settings", {}),
            "capabilities": android_data.get("capabilities", {}),
            "controls": [],
            "supported": True,
        }

    saved_settings = cameraDeviceSettingsToDict(
        parseCameraDeviceSettings(_get_camera_device_settings_table(config).get(role))
    )
    controls, live_settings = _live_usb_device_controls(role, source, saved_settings)
    current_settings = live_settings or saved_settings
    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": current_settings,
        "controls": controls,
        "supported": bool(controls),
        "message": (
            "Real USB camera controls are available for this camera."
            if controls
            else (
                "This USB camera does not expose adjustable UVC controls on this macOS setup."
                if platform.system() == "Darwin"
                else "This USB camera does not expose adjustable controls through the current capture backend."
            )
        ),
    }


@app.post("/api/cameras/device-settings/{role}/preview")
def preview_camera_device_settings(role: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    _, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")

    if isinstance(source, str):
        proxied = _android_camera_request(
            source,
            "/camera-settings/preview",
            method="POST",
            payload=payload,
        )
        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": proxied.get("provider", "android-camera-app"),
            "settings": proxied.get("settings", payload),
            "persisted": False,
            "applied_live": True,
        }

    parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(payload))
    camera_device_preview_overrides[role] = dict(parsed)
    applied_live = False
    applied_settings = dict(parsed)

    if vision_manager is not None and hasattr(vision_manager, "setDeviceSettingsForRole"):
        try:
            live_result = vision_manager.setDeviceSettingsForRole(role, parsed, persist=False)
            if live_result is not None:
                applied_settings = cameraDeviceSettingsToDict(live_result)
                camera_device_preview_overrides[role] = dict(applied_settings)
                applied_live = True
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": applied_settings,
        "persisted": False,
        "applied_live": applied_live,
    }


@app.post("/api/cameras/device-settings/{role}")
def save_camera_device_settings(role: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    params_path, config = _read_machine_params_config()
    source = _camera_source_for_role(config, role)
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")

    if isinstance(source, str):
        proxied = _android_camera_request(
            source,
            "/camera-settings",
            method="POST",
            payload=payload,
        )
        return {
            "ok": True,
            "role": role,
            "source": source,
            "provider": proxied.get("provider", "android-camera-app"),
            "settings": proxied.get("settings", payload),
            "persisted": True,
            "applied_live": True,
        }

    parsed = cameraDeviceSettingsToDict(parseCameraDeviceSettings(payload))
    device_settings = _get_camera_device_settings_table(config)
    if parsed:
        device_settings[role] = dict(parsed)
    else:
        device_settings.pop(role, None)
    config["camera_device_settings"] = device_settings

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    camera_device_preview_overrides[role] = dict(parsed)
    applied_live = False
    applied_settings = dict(parsed)
    if vision_manager is not None and hasattr(vision_manager, "setDeviceSettingsForRole"):
        try:
            live_result = vision_manager.setDeviceSettingsForRole(role, parsed, persist=True)
            if live_result is not None:
                applied_settings = cameraDeviceSettingsToDict(live_result)
                camera_device_preview_overrides[role] = dict(applied_settings)
                applied_live = True
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "source": source,
        "provider": "usb-opencv",
        "settings": applied_settings,
        "persisted": True,
        "applied_live": applied_live,
        "message": "Camera device settings saved.",
    }


def _save_camera_color_profile(
    role: str,
    payload: Dict[str, Any] | None,
) -> Dict[str, Any]:
    if role not in CAMERA_SETUP_ROLES:
        raise HTTPException(status_code=404, detail=f"Unknown camera role '{role}'")

    params_path, config = _read_machine_params_config()
    parsed = parseCameraColorProfile(payload)
    profile_dict = cameraColorProfileToDict(parsed)
    profiles = _get_camera_color_profile_table(config)
    if parsed.enabled:
        profiles[role] = profile_dict
    else:
        profiles.pop(role, None)
    config["camera_color_profiles"] = profiles

    try:
        _write_machine_params_config(params_path, config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write config: {exc}")

    applied_live = False
    if vision_manager is not None and hasattr(vision_manager, "setColorProfileForRole"):
        try:
            applied_live = bool(vision_manager.setColorProfileForRole(role, parsed))
        except Exception:
            applied_live = False

    return {
        "ok": True,
        "role": role,
        "profile": profile_dict,
        "applied_live": applied_live,
    }


def _restore_preview_settings(role: str, settings: Dict[str, int | float | bool]) -> None:
    try:
        preview_camera_device_settings(role, settings)
    except Exception:
        pass


def _restore_camera_color_profile(role: str, profile: Dict[str, Any]) -> None:
    try:
        _save_camera_color_profile(role, profile)
    except Exception:
        pass


def _analysis_number(analysis: Dict[str, Any] | None, key: str, default: float = 0.0) -> float:
    if not isinstance(analysis, dict):
        return default
    value = analysis.get(key)
    return float(value) if isinstance(value, (int, float)) else default


def _analysis_neutral_mean_bgr(analysis: Dict[str, Any] | None) -> tuple[float, float, float] | None:
    if not isinstance(analysis, dict):
        return None
    value = analysis.get("neutral_mean_bgr")
    if not isinstance(value, list) or len(value) != 3:
        return None
    if not all(isinstance(channel, (int, float)) for channel in value):
        return None
    return float(value[0]), float(value[1]), float(value[2])


def _exposure_direction(analysis: Dict[str, Any] | None) -> int:
    white_luma = _analysis_number(analysis, "white_luma_mean")
    black_luma = _analysis_number(analysis, "black_luma_mean")
    clipped = _analysis_number(analysis, "clipped_white_fraction")
    if clipped >= 0.03 or white_luma >= 210.0:
        return 1
    if white_luma <= 165.0 and black_luma <= 28.0:
        return -1
    if white_luma <= 180.0:
        return -1
    return 0


def _white_balance_direction(analysis: Dict[str, Any] | None) -> int:
    neutral_bgr = _analysis_neutral_mean_bgr(analysis)
    if neutral_bgr is None:
        return 0
    blue, green, red = neutral_bgr
    if green <= 1e-6:
        return 0
    bias = (red - blue) / green
    if abs(bias) <= 0.035:
        return 0
    return -1 if bias > 0 else 1


def _camera_analysis_score(analysis: Dict[str, Any] | None) -> float:
    if not isinstance(analysis, dict):
        return float("-inf")
    value = analysis.get("score")
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def _calibration_selection_value(analysis: Dict[str, Any] | None) -> float:
    score = _camera_analysis_score(analysis)
    if not isinstance(analysis, dict):
        return score
    tile_samples = analysis.get("tile_samples")
    if not isinstance(tile_samples, dict) or not tile_samples:
        return score

    important_keys = ("white_top", "white_bottom", "red", "yellow")
    important_matches: List[float] = []
    all_matches: List[float] = []
    for key, raw in tile_samples.items():
        if not isinstance(raw, dict):
            continue
        match_value = raw.get("reference_match_percent")
        if not isinstance(match_value, (int, float)):
            continue
        match = float(match_value)
        all_matches.append(match)
        if key in important_keys:
            important_matches.append(match)

    if not important_matches:
        return score

    min_match = min(important_matches)
    avg_match = float(sum(important_matches) / len(important_matches))
    overall_match = float(sum(all_matches) / len(all_matches)) if all_matches else avg_match
    return score * 0.15 + avg_match + min_match * 1.3 + overall_match * 0.25


def _create_camera_calibration_task(
    role: str,
    provider: str,
    source: int | str | None,
) -> str:
    task_id = uuid4().hex
    task = {
        "task_id": task_id,
        "role": role,
        "provider": provider,
        "source": source,
        "status": "queued",
        "stage": "queued",
        "message": "Queued camera calibration.",
        "progress": 0.0,
        "result": None,
        "analysis_preview": None,
        "error": None,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with camera_calibration_tasks_lock:
        camera_calibration_tasks[task_id] = task
    return task_id


def _update_camera_calibration_task(task_id: str, **updates: Any) -> None:
    with camera_calibration_tasks_lock:
        task = camera_calibration_tasks.get(task_id)
        if task is None:
            return
        task.update(updates)
        task["updated_at"] = time.time()


def _get_camera_calibration_task(task_id: str) -> Dict[str, Any] | None:
    with camera_calibration_tasks_lock:
        task = camera_calibration_tasks.get(task_id)
        return dict(task) if task is not None else None


def _calibrate_usb_camera_device_settings(
    role: str,
    source: int,
    controls: List[Dict[str, Any]],
    current_settings: Dict[str, int | float | bool],
    *,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
) -> tuple[Dict[str, int | float | bool], Dict[str, Any]]:
    control_by_key = {
        str(control.get("key")): control
        for control in controls
        if isinstance(control, dict) and isinstance(control.get("key"), str)
    }

    exposure_control = control_by_key.get("exposure")
    gain_control = control_by_key.get("gain")
    wb_control = control_by_key.get("white_balance_temperature")
    auto_exposure_control = control_by_key.get("auto_exposure")
    auto_wb_control = control_by_key.get("auto_white_balance")
    defaults = _usb_control_defaults(controls, current_settings)
    primary_keys = {
        "auto_exposure",
        "exposure",
        "gain",
        "auto_white_balance",
        "white_balance_temperature",
        "power_line_frequency",
        "backlight_compensation",
        "sharpness",
    }
    baseline_candidate = dict(defaults or current_settings)
    for key in primary_keys:
        if key in current_settings:
            baseline_candidate[key] = current_settings[key]
    if auto_exposure_control is not None:
        baseline_candidate["auto_exposure"] = False
    if auto_wb_control is not None:
        baseline_candidate["auto_white_balance"] = False
    initial_candidates: List[Dict[str, int | float | bool]] = [baseline_candidate]

    best_settings: Dict[str, int | float | bool] | None = None
    best_analysis: Dict[str, Any] | None = None

    total_steps = max(
        1,
        len(initial_candidates)
        + (8 if exposure_control is not None else 0)
        + (5 if gain_control is not None and exposure_control is None else 0)
        + (8 if wb_control is not None else 0),
    )
    completed_steps = 0

    def consider(
        candidate: Dict[str, int | float | bool],
        *,
        stage: str,
        message: str,
    ) -> tuple[Dict[str, Any], Dict[str, Any] | None]:
        nonlocal best_settings, best_analysis, completed_steps
        completed_steps += 1
        applied_settings, analysis = _analyze_candidate_settings(role, source, candidate)
        progress = min(0.9, completed_steps / total_steps)
        if report_progress is not None:
            report_progress(stage, progress, message, analysis)
        if analysis is None:
            return applied_settings, None
        if best_analysis is None or _calibration_selection_value(analysis) > _calibration_selection_value(best_analysis):
            best_settings = dict(applied_settings)
            best_analysis = analysis
            if report_progress is not None:
                report_progress(stage, progress, message, analysis)
        return applied_settings, analysis

    for index, candidate in enumerate(initial_candidates, start=1):
        consider(
            candidate,
            stage="baseline",
            message=f"Analyzing baseline candidate {index} of {len(initial_candidates)}.",
        )

    if best_settings is None or best_analysis is None:
        raise HTTPException(
            status_code=400,
            detail="Calibration target not found. Make sure the 6-color calibration plate is fully visible and not clipped.",
        )

    if exposure_control is not None:
        exposure_min = _as_number(exposure_control.get("min"))
        exposure_max = _as_number(exposure_control.get("max"))
        current_exposure = _as_number(best_settings.get("exposure"))
        if exposure_min is not None and exposure_max is not None and current_exposure is not None:
            low = exposure_min
            high = exposure_max
            trial = float(
                _quantize_numeric_value(
                    max(exposure_min, min(exposure_max, current_exposure)),
                    exposure_min,
                    _as_number(exposure_control.get("step")),
                )
            )
            last_trial: float | None = None
            for index in range(8):
                candidate = dict(best_settings)
                candidate["exposure"] = trial
                if auto_exposure_control is not None:
                    candidate["auto_exposure"] = False
                _, analysis = consider(
                    candidate,
                    stage="exposure_search",
                    message=f"Evaluating exposure candidate {index + 1} of 8.",
                )
                if analysis is None:
                    break
                direction = _exposure_direction(analysis)
                if direction > 0:
                    high = min(high, trial)
                elif direction < 0:
                    low = max(low, trial)
                else:
                    break
                if high <= low:
                    break
                next_trial = float(np.sqrt(low * high)) if low > 0 else float((low + high) / 2.0)
                next_trial = float(
                    _quantize_numeric_value(
                        max(exposure_min, min(exposure_max, next_trial)),
                        exposure_min,
                        _as_number(exposure_control.get("step")),
                    )
                )
                if last_trial is not None and abs(next_trial - last_trial) < 1e-6:
                    break
                last_trial = trial
                trial = next_trial
    elif gain_control is not None:
        gain_values = _focused_numeric_control_candidates(
            gain_control,
            best_settings.get("gain"),
            count=5,
            linear_span_fraction=0.12,
        )
        for index, gain_value in enumerate(gain_values, start=1):
            candidate = dict(best_settings)
            candidate["gain"] = gain_value
            consider(
                candidate,
                stage="exposure_search",
                message=f"Evaluating gain candidate {index} of {len(gain_values)}.",
            )

    if wb_control is not None:
        wb_min = _as_number(wb_control.get("min"))
        wb_max = _as_number(wb_control.get("max"))
        current_wb = _as_number(best_settings.get("white_balance_temperature"))
        if wb_min is not None and wb_max is not None and current_wb is not None:
            low = wb_min
            high = wb_max
            trial = float(
                _quantize_numeric_value(
                    max(wb_min, min(wb_max, current_wb)),
                    wb_min,
                    _as_number(wb_control.get("step")),
                )
            )
            last_trial: float | None = None
            for index in range(8):
                candidate = dict(best_settings)
                candidate["white_balance_temperature"] = trial
                if auto_wb_control is not None:
                    candidate["auto_white_balance"] = False
                _, analysis = consider(
                    candidate,
                    stage="white_balance_search",
                    message=f"Evaluating white balance candidate {index + 1} of 8.",
                )
                if analysis is None:
                    break
                direction = _white_balance_direction(analysis)
                if direction > 0:
                    low = max(low, trial)
                elif direction < 0:
                    high = min(high, trial)
                else:
                    break
                if high <= low:
                    break
                next_trial = float((low + high) / 2.0)
                next_trial = float(
                    _quantize_numeric_value(
                        max(wb_min, min(wb_max, next_trial)),
                        wb_min,
                        _as_number(wb_control.get("step")),
                    )
                )
                if last_trial is not None and abs(next_trial - last_trial) < 1e-6:
                    break
                last_trial = trial
                trial = next_trial

    if best_settings is None or best_analysis is None:
        raise HTTPException(status_code=400, detail="Calibration failed to find usable settings.")

    return best_settings, best_analysis


def _calibrate_android_camera_device_settings(
    role: str,
    source: str,
    current_settings: Dict[str, Any],
    capabilities: Dict[str, Any],
    *,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    base_settings = {
        "exposure_compensation": int(current_settings.get("exposure_compensation", 0)),
        "ae_lock": False,
        "awb_lock": False,
        "white_balance_mode": str(current_settings.get("white_balance_mode", "auto")),
        "processing_mode": str(current_settings.get("processing_mode", "standard")),
    }

    exposure_min = int(capabilities.get("exposure_compensation_min", 0))
    exposure_max = int(capabilities.get("exposure_compensation_max", 0))
    white_balance_modes = [
        str(mode)
        for mode in capabilities.get("white_balance_modes", ["auto"])
        if isinstance(mode, str) and mode
    ] or ["auto"]

    best_settings: Dict[str, int | float | bool] | None = None
    best_analysis: Dict[str, Any] | None = None
    total_steps = 1

    def tick(stage: str, progress: float, message: str, analysis: Dict[str, Any] | None = None) -> None:
        if report_progress is not None:
            report_progress(stage, min(0.9, progress), message, analysis)

    steps_done = 0

    def consider(candidate: Dict[str, Any], *, stage: str, message: str) -> None:
        nonlocal best_settings, best_analysis
        nonlocal steps_done
        steps_done += 1
        tick(stage, steps_done / total_steps, message)
        applied_settings, analysis = _analyze_candidate_settings(role, source, candidate)
        if analysis is None:
            return
        if best_analysis is None or _calibration_selection_value(analysis) > _calibration_selection_value(best_analysis):
            best_settings = dict(applied_settings)
            best_analysis = analysis
            tick(stage, steps_done / total_steps, message, analysis)

    exposure_values = sorted(
        {
            exposure_min,
            exposure_max,
            int(base_settings["exposure_compensation"]),
            *[
                int(round(value))
                for value in np.linspace(exposure_min, exposure_max, num=max(3, min(7, exposure_max - exposure_min + 1))).tolist()
            ],
        }
    )
    total_steps = max(1, 1 + len(exposure_values) + len(white_balance_modes))

    consider(
        base_settings,
        stage="baseline",
        message="Analyzing baseline candidate 1 of 1.",
    )

    for index, exposure_value in enumerate(exposure_values, start=1):
        candidate = dict(base_settings)
        candidate["exposure_compensation"] = int(exposure_value)
        consider(
            candidate,
            stage="exposure_search",
            message=f"Evaluating exposure candidate {index} of {len(exposure_values)}.",
        )

    if best_settings is None or best_analysis is None:
        raise HTTPException(
            status_code=400,
            detail="Calibration target not found. Make sure the 6-color calibration plate is fully visible and not clipped.",
        )

    wb_base = dict(best_settings)
    wb_base["ae_lock"] = False
    wb_base["awb_lock"] = False
    for index, mode in enumerate(white_balance_modes, start=1):
        candidate = dict(wb_base)
        candidate["white_balance_mode"] = mode
        consider(
            candidate,
            stage="white_balance_search",
            message=f"Evaluating white balance candidate {index} of {len(white_balance_modes)}.",
        )

    if best_settings is None or best_analysis is None:
        raise HTTPException(status_code=400, detail="Calibration failed to find usable settings.")

    if bool(capabilities.get("supports_ae_lock")):
        best_settings["ae_lock"] = True
    if bool(capabilities.get("supports_awb_lock")):
        best_settings["awb_lock"] = True

    return best_settings, best_analysis


def _run_camera_calibration_sync(
    role: str,
    *,
    report_progress: Callable[[str, float, str, Dict[str, Any] | None], None] | None = None,
) -> Dict[str, Any]:
    current_response = get_camera_device_settings(role)
    source = current_response.get("source")
    provider = current_response.get("provider")
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")
    if not bool(current_response.get("supported")):
        raise HTTPException(status_code=400, detail=current_response.get("message") or "This camera cannot be calibrated through the current control backend.")

    _, raw_config = _read_machine_params_config()
    original_picture_settings = _picture_settings_for_role(raw_config, role)
    original_color_profile = _camera_color_profile_for_role(raw_config, role)

    if provider == "android-camera-app":
        original_settings = (
            dict(current_response.get("settings"))
            if isinstance(current_response.get("settings"), dict)
            else {}
        )
    else:
        original_settings = cameraDeviceSettingsToDict(
            parseCameraDeviceSettings(current_response.get("settings"))
        )

    try:
        if provider == "usb-opencv":
            controls = current_response.get("controls")
            if not isinstance(controls, list) or not isinstance(source, int):
                raise HTTPException(status_code=400, detail="USB camera controls are not available for calibration.")
            if report_progress is not None:
                report_progress("preparing", 0.05, "Preparing USB camera calibration.", None)
            best_settings, analysis = _calibrate_usb_camera_device_settings(
                role,
                source,
                controls,
                original_settings,
                report_progress=report_progress,
            )
        elif provider == "android-camera-app":
            capabilities = current_response.get("capabilities")
            if not isinstance(capabilities, dict) or not isinstance(source, str):
                raise HTTPException(status_code=400, detail="Android camera capabilities are not available for calibration.")
            if report_progress is not None:
                report_progress("preparing", 0.05, "Preparing Android camera calibration.", None)
            best_settings, analysis = _calibrate_android_camera_device_settings(
                role,
                source,
                current_response.get("settings") if isinstance(current_response.get("settings"), dict) else {},
                capabilities,
                report_progress=report_progress,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="This camera provider does not support target-based calibration yet.",
            )

        if report_progress is not None:
            report_progress("saving", 0.91, "Saving calibrated exposure and white balance.", analysis)
        saved = save_camera_device_settings(role, best_settings)
        time.sleep(0.2)

        if report_progress is not None:
            report_progress("profile_generation", 0.95, "Generating a color correction profile from the target plate.", analysis)
        raw_frame = _capture_frame_for_calibration(
            role,
            source,
            fallback_settings=best_settings,
        )
        raw_analysis_obj = analyze_calibration_target(raw_frame) if raw_frame is not None else None
        raw_analysis = raw_analysis_obj.to_dict() if raw_analysis_obj is not None else analysis
        profile_payload = generate_color_profile_from_analysis(raw_analysis)
        if profile_payload is None:
            raise HTTPException(
                status_code=400,
                detail="Calibration found the target, but could not generate a color profile from it.",
            )

        profile_saved = _save_camera_color_profile(role, profile_payload)

        if report_progress is not None:
            report_progress("verifying", 0.98, "Verifying the calibrated profile on the live feed.", raw_analysis)

        final_frame = raw_frame
        if final_frame is None:
            final_frame = _capture_frame_for_calibration(
                role,
                source,
                fallback_settings=best_settings,
            )
        if final_frame is not None:
            from vision.camera import apply_camera_color_profile, apply_picture_settings

            final_frame = apply_camera_color_profile(
                final_frame,
                parseCameraColorProfile(profile_saved.get("profile")),
            )
            final_frame = apply_picture_settings(
                final_frame,
                parseCameraPictureSettings(original_picture_settings),
            )

        final_analysis = analyze_calibration_target(final_frame) if final_frame is not None else None
        chosen_analysis = final_analysis.to_dict() if final_analysis is not None else raw_analysis
        result = {
            **saved,
            "color_profile": profile_saved.get("profile"),
            "analysis": chosen_analysis,
            "message": "Camera calibrated from the 6-color target plate, and a color profile was generated.",
        }
        if report_progress is not None:
            report_progress("completed", 1.0, "Camera calibration finished.", result.get("analysis"))
        return result
    except HTTPException:
        _restore_preview_settings(role, original_settings)
        _restore_camera_color_profile(role, original_color_profile)
        raise
    except Exception as exc:
        _restore_preview_settings(role, original_settings)
        _restore_camera_color_profile(role, original_color_profile)
        raise HTTPException(status_code=500, detail=f"Camera calibration failed: {exc}")


def _run_camera_calibration_task(task_id: str, role: str) -> None:
    def report_progress(stage: str, progress: float, message: str, analysis: Dict[str, Any] | None = None) -> None:
        _update_camera_calibration_task(
            task_id,
            status="running" if stage != "completed" else "completed",
            stage=stage,
            progress=max(0.0, min(1.0, float(progress))),
            message=message,
            analysis_preview=analysis,
        )

    try:
        _update_camera_calibration_task(
            task_id,
            status="running",
            stage="starting",
            progress=0.01,
            message="Starting camera calibration.",
        )
        result = _run_camera_calibration_sync(role, report_progress=report_progress)
        _update_camera_calibration_task(
            task_id,
            status="completed",
            stage="completed",
            progress=1.0,
            message=str(result.get("message") or "Camera calibration finished."),
            result=result,
            error=None,
        )
    except HTTPException as exc:
        _update_camera_calibration_task(
            task_id,
            status="failed",
            stage="failed",
            progress=1.0,
            message="Camera calibration failed.",
            error=str(exc.detail),
        )
    except Exception as exc:
        _update_camera_calibration_task(
            task_id,
            status="failed",
            stage="failed",
            progress=1.0,
            message="Camera calibration failed.",
            error=str(exc),
        )


@app.post("/api/cameras/device-settings/{role}/calibrate-target")
def start_camera_device_settings_calibration_from_target(role: str) -> Dict[str, Any]:
    current_response = get_camera_device_settings(role)
    source = current_response.get("source")
    provider = str(current_response.get("provider") or "unknown")
    if source is None:
        raise HTTPException(status_code=404, detail="No camera is assigned to this role.")
    if not bool(current_response.get("supported")):
        raise HTTPException(status_code=400, detail=current_response.get("message") or "This camera cannot be calibrated through the current control backend.")

    task_id = _create_camera_calibration_task(role, provider, source)
    thread = threading.Thread(
        target=_run_camera_calibration_task,
        args=(task_id, role),
        daemon=True,
    )
    thread.start()
    task = _get_camera_calibration_task(task_id)
    assert task is not None
    return {
        "ok": True,
        "started": True,
        "task_id": task_id,
        "role": role,
        "provider": provider,
        "source": source,
        "status": task.get("status"),
        "stage": task.get("stage"),
        "progress": task.get("progress"),
        "message": task.get("message"),
    }


@app.get("/api/cameras/device-settings/{role}/calibrate-target/{task_id}")
def get_camera_device_settings_calibration_task(role: str, task_id: str) -> Dict[str, Any]:
    task = _get_camera_calibration_task(task_id)
    if task is None or task.get("role") != role:
        raise HTTPException(status_code=404, detail="Calibration task not found.")
    return {
        "ok": True,
        "task_id": task_id,
        "role": role,
        "provider": task.get("provider"),
        "source": task.get("source"),
        "status": task.get("status"),
        "stage": task.get("stage"),
        "progress": task.get("progress"),
        "message": task.get("message"),
        "result": task.get("result"),
        "analysis_preview": task.get("analysis_preview"),
        "error": task.get("error"),
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
