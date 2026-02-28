from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import asyncio
import queue
import os
import io
import time
import threading
import cv2
import numpy as np
from pathlib import Path

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
from global_config import GlobalConfig
from runtime_variables import RuntimeVariables, VARIABLE_DEFS
from irl.config import ArucoTagConfig, CarouselArucoTagConfig

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
        second_tags.get("radius1"),
        second_tags.get("radius2"),
        second_tags.get("radius3"),
        second_tags.get("radius4"),
        second_tags.get("radius5"),
    ]
    runtime_config.second_c_channel_radius_ids = [
        int(tag) for tag in runtime_config.second_c_channel_radius_ids if tag is not None
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
        third_tags.get("radius1"),
        third_tags.get("radius2"),
        third_tags.get("radius3"),
        third_tags.get("radius4"),
        third_tags.get("radius5"),
    ]
    runtime_config.third_c_channel_radius_ids = [
        int(tag) for tag in runtime_config.third_c_channel_radius_ids if tag is not None
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
    """Sync live ArUco config into vision and trigger geometry recalculation."""
    sync_result = _sync_aruco_config_to_vision()
    if not sync_result.get("synced"):
        return {
            "ok": False,
            "calibrated": False,
            "sync": sync_result,
        }

    try:
        vision_manager.updateFeedingPlatformCache()
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


class HealthResponse(BaseModel):
    status: str


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    active_connections.append(websocket)

    machine_id = gc_ref.machine_id if gc_ref is not None else "unknown"
    identity_event = IdentityEvent(
        tag="identity",
        data=MachineIdentityData(machine_id=machine_id, nickname=None),
    )
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


@app.get("/runtime-variables", response_model=RuntimeVariablesResponse)
def getRuntimeVariables() -> RuntimeVariablesResponse:
    if runtime_vars is None:
        raise HTTPException(status_code=500, detail="Runtime variables not initialized")
    defs = {k: RuntimeVariableDef(**v) for k, v in VARIABLE_DEFS.items()}
    return RuntimeVariablesResponse(definitions=defs, values=runtime_vars.getAll())


@app.post("/runtime-variables", response_model=RuntimeVariablesResponse)
def updateRuntimeVariables(
    req: RuntimeVariablesUpdateRequest,
) -> RuntimeVariablesResponse:
    if runtime_vars is None:
        raise HTTPException(status_code=500, detail="Runtime variables not initialized")
    runtime_vars.setAll(req.values)
    defs = {k: RuntimeVariableDef(**v) for k, v in VARIABLE_DEFS.items()}
    return RuntimeVariablesResponse(definitions=defs, values=runtime_vars.getAll())


class StateResponse(BaseModel):
    state: str


@app.get("/state", response_model=StateResponse)
def getState() -> StateResponse:
    if controller_ref is None:
        return StateResponse(state=SorterLifecycle.INITIALIZING.value)
    return StateResponse(state=controller_ref.state.value)


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
        "c_channel_1": getattr(irl, "first_c_channel_rotor_stepper", None),
        "c_channel_2": getattr(irl, "second_c_channel_rotor_stepper", None),
        "c_channel_3": getattr(irl, "third_c_channel_rotor_stepper", None),
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

    lock = pulse_locks.get(stepper)
    if lock is not None and lock.locked():
        try:
            lock.release()
        except RuntimeError:
            pass

    return StepperStopResponse(success=True, stepper=stepper)


# Video Streaming Routes
@app.get("/video_feed/{camera_name}")
def video_feed(camera_name: str, show_live_aruco_values: bool = False) -> StreamingResponse:
    """Stream MJPEG video from the specified camera"""
    if vision_manager is None:
        raise HTTPException(status_code=500, detail="Vision manager not initialized")
    
    def generate_frames():
        """Generator function that yields JPEG frames"""
        import time
        buffer_size = 65536
        quality = 80  # JPEG quality (0-100)
        
        while True:
            frame_obj = vision_manager.getFrame(camera_name)
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
                    raw_tags = vision_manager.getFeederArucoTagsRaw()
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
