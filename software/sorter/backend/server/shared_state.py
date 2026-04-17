"""Shared mutable state and setter functions for the Sorter API.

All module-level globals live here so that ``api.py`` and every router can
import this single module without circular dependencies.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from aruco_config_manager import ArucoConfigManager
from global_config import GlobalConfig
from irl.config import ArucoTagConfig, CarouselArucoTagConfig
from runtime_variables import RuntimeVariables

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

active_connections: List[WebSocket] = []
server_loop: Optional[asyncio.AbstractEventLoop] = None
runtime_vars: Optional[RuntimeVariables] = None
command_queue: Optional[queue.Queue] = None
controller_ref: Optional[Any] = None
gc_ref: Optional[GlobalConfig] = None
aruco_manager: Optional[ArucoConfigManager] = None
vision_manager: Optional[Any] = None
camera_service: Optional[Any] = None
pulse_locks: Dict[str, threading.Lock] = {}
camera_device_preview_overrides: Dict[str, Dict[str, int | float | bool]] = {}
camera_calibration_tasks: Dict[str, Dict[str, Any]] = {}
camera_calibration_tasks_lock = threading.Lock()
runtime_stats_snapshot: Optional[dict[str, Any]] = None
system_status_snapshot: Optional[dict[str, Any]] = None
sorter_state_snapshot: Optional[dict[str, Any]] = None
cameras_config_snapshot: Optional[dict[str, Any]] = None
sorting_profile_status_snapshot: Optional[dict[str, Any]] = None

# Hardware lifecycle state: "standby" | "initializing" | "initialized" | "homing" | "ready" | "error"
hardware_state: str = "standby"
hardware_error: Optional[str] = None
hardware_homing_step: Optional[str] = None  # Current homing phase description
_hardware_start_fn: Optional[Any] = None  # Callable set by main.py
_hardware_initialize_fn: Optional[Any] = None  # Callable set by main.py
_hardware_reset_fn: Optional[Any] = None  # Callable set by main.py
hardware_runtime_irl: Optional[Any] = None  # Active IRL during homing before controller exists
hardware_worker_thread: Optional[threading.Thread] = None
hardware_lifecycle_lock = threading.RLock()

CLASSIFICATION_BASELINE_SAMPLES = 12
CLASSIFICATION_BASELINE_CAPTURE_TIMEOUT_S = 4.0
CLASSIFICATION_BASELINE_CAPTURE_INTERVAL_S = 0.1

# ---------------------------------------------------------------------------
# Setter functions (called from main.py at startup)
# ---------------------------------------------------------------------------


def setGlobalConfig(gc: GlobalConfig) -> None:
    global gc_ref
    gc_ref = gc


def setRuntimeVariables(rv: RuntimeVariables) -> None:
    global runtime_vars
    runtime_vars = rv


def _getRuntimeVariables() -> RuntimeVariables:
    global runtime_vars
    if runtime_vars is None:
        runtime_vars = RuntimeVariables()
    return runtime_vars


def setCommandQueue(q: queue.Queue) -> None:
    global command_queue
    command_queue = q


def setController(c: Any) -> None:
    global controller_ref
    controller_ref = c


def setHardwareStartFn(fn: Any) -> None:
    global _hardware_start_fn
    _hardware_start_fn = fn


def setHardwareInitializeFn(fn: Any) -> None:
    global _hardware_initialize_fn
    _hardware_initialize_fn = fn


def setHardwareResetFn(fn: Any) -> None:
    global _hardware_reset_fn
    _hardware_reset_fn = fn


def setHardwareRuntimeIRL(irl: Any | None) -> None:
    global hardware_runtime_irl
    hardware_runtime_irl = irl


def getActiveIRL() -> Any | None:
    if controller_ref is not None and hasattr(controller_ref, "irl"):
        return controller_ref.irl
    return hardware_runtime_irl


def setArucoManager(mgr: ArucoConfigManager) -> None:
    global aruco_manager
    aruco_manager = mgr
    auto_calibrate()


def setCameraService(svc: Any) -> None:
    global camera_service
    camera_service = svc


def setVisionManager(mgr: Any) -> None:
    global vision_manager
    vision_manager = mgr
    from server.classification_training import getClassificationTrainingManager
    getClassificationTrainingManager().setVisionManager(mgr)
    auto_calibrate()


# ---------------------------------------------------------------------------
# WebSocket broadcasting
# ---------------------------------------------------------------------------


async def broadcastEvent(event: dict) -> None:
    global runtime_stats_snapshot, system_status_snapshot, sorter_state_snapshot, cameras_config_snapshot, sorting_profile_status_snapshot
    tag = event.get("tag")
    data = event.get("data") if isinstance(event.get("data"), dict) else None
    if tag == "runtime_stats" and data is not None:
        payload = data.get("payload")
        if isinstance(payload, dict):
            runtime_stats_snapshot = payload
    elif tag == "system_status" and data is not None:
        system_status_snapshot = dict(data)
    elif tag == "sorter_state" and data is not None:
        sorter_state_snapshot = dict(data)
    elif tag == "cameras_config" and data is not None:
        cameras_config_snapshot = dict(data)
    elif tag == "sorting_profile_status" and data is not None:
        sorting_profile_status_snapshot = dict(data)
    dead_connections = []
    for connection in active_connections[:]:
        try:
            await connection.send_json(event)
        except Exception:
            dead_connections.append(connection)
    for conn in dead_connections:
        if conn in active_connections:
            active_connections.remove(conn)


def _update_snapshot(event: dict) -> None:
    """Update in-memory snapshot globals so WS-connect replay is accurate."""
    global runtime_stats_snapshot, system_status_snapshot, sorter_state_snapshot, cameras_config_snapshot, sorting_profile_status_snapshot
    tag = event.get("tag")
    data = event.get("data") if isinstance(event.get("data"), dict) else None
    if tag == "system_status" and data is not None:
        system_status_snapshot = dict(data)
    elif tag == "sorter_state" and data is not None:
        sorter_state_snapshot = dict(data)
    elif tag == "cameras_config" and data is not None:
        cameras_config_snapshot = dict(data)
    elif tag == "sorting_profile_status" and data is not None:
        sorting_profile_status_snapshot = dict(data)
    elif tag == "runtime_stats" and data is not None:
        payload = data.get("payload")
        if isinstance(payload, dict):
            runtime_stats_snapshot = payload


def broadcast_from_thread(event: dict) -> None:
    """Thread-safe broadcast helper — schedules a broadcast on the server loop.

    Safe to call from any thread, including synchronous request handlers.
    Always updates the snapshot first; the live broadcast is best-effort and
    silently no-ops if the server loop is not running.
    """
    _update_snapshot(event)
    loop = server_loop
    if loop is None or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(broadcastEvent(event), loop)
    except Exception:
        # Loop closed / not running — best-effort only.
        pass


def publishSystemStatus() -> None:
    """Broadcast the current hardware status snapshot over WS."""
    broadcast_from_thread(
        {
            "tag": "system_status",
            "data": {
                "hardware_state": hardware_state,
                "hardware_error": hardware_error,
                "homing_step": hardware_homing_step,
            },
        }
    )


def setHardwareStatus(
    *,
    state: Optional[str] = None,
    error: Optional[str] = None,
    homing_step: Optional[str] = None,
    clear_error: bool = False,
    clear_homing_step: bool = False,
) -> None:
    """Update hardware lifecycle fields and broadcast the change over WS.

    Pass ``clear_error`` or ``clear_homing_step`` to explicitly null those fields
    (since ``None`` means "don't change" for the update args).
    Caller is responsible for holding ``hardware_lifecycle_lock`` when needed.
    """
    global hardware_state, hardware_error, hardware_homing_step
    changed = False
    if state is not None and state != hardware_state:
        hardware_state = state
        changed = True
    if error is not None and error != hardware_error:
        hardware_error = error
        changed = True
    elif clear_error and hardware_error is not None:
        hardware_error = None
        changed = True
    if homing_step is not None and homing_step != hardware_homing_step:
        hardware_homing_step = homing_step
        changed = True
    elif clear_homing_step and hardware_homing_step is not None:
        hardware_homing_step = None
        changed = True
    if changed:
        publishSystemStatus()


def publishSorterState(state: str, camera_layout: Optional[str] = None) -> None:
    """Broadcast the sorter-controller FSM state over WS."""
    broadcast_from_thread(
        {
            "tag": "sorter_state",
            "data": {
                "state": state,
                "camera_layout": camera_layout,
            },
        }
    )


def publishCamerasConfig(cameras: Dict[str, Any]) -> None:
    """Broadcast the camera role → source map over WS."""
    broadcast_from_thread(
        {
            "tag": "cameras_config",
            "data": {"cameras": dict(cameras)},
        }
    )


def publishSortingProfileStatus(status: Dict[str, Any]) -> None:
    """Broadcast the sorting profile sync status + local profile metadata over WS."""
    sync_state = status.get("sync_state") if isinstance(status.get("sync_state"), dict) else {}
    local_profile = status.get("local_profile") if isinstance(status.get("local_profile"), dict) else {}
    broadcast_from_thread(
        {
            "tag": "sorting_profile_status",
            "data": {
                "sync_state": dict(sync_state),
                "local_profile": dict(local_profile),
            },
        }
    )


# ---------------------------------------------------------------------------
# ArUco helpers (used by setters and aruco router)
# ---------------------------------------------------------------------------


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
