"""Shared mutable state and setter functions for the Sorter API.

All module-level globals live here so that ``api.py`` and every router can
import this single module without circular dependencies.
"""

from __future__ import annotations

import asyncio
import math
import queue
import threading
import time
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from global_config import GlobalConfig
from runtime_variables import RuntimeVariables
import server.perf_history as perf_history

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

active_connections: List[WebSocket] = []
server_loop: Optional[asyncio.AbstractEventLoop] = None
runtime_vars: Optional[RuntimeVariables] = None
command_queue: Optional[queue.Queue] = None
controller_ref: Optional[Any] = None
gc_ref: Optional[GlobalConfig] = None
vision_manager: Optional[Any] = None

# Per-client send budget for a single broadcast. Bounds how long one slow or
# half-dead websocket client can hold up a broadcast before it's pruned. On a
# healthy LAN a send is sub-millisecond, so this only ever fires for genuinely
# stuck clients.
_BROADCAST_SEND_TIMEOUT_S = 0.25
camera_service: Optional[Any] = None
pulse_locks: Dict[str, threading.Lock] = {}
distribution_no_bin_passthrough_approvals: set[str] = set()
distribution_no_bin_passthrough_lock = threading.RLock()
camera_device_preview_overrides: Dict[str, Dict[str, int | float | bool]] = {}
camera_legacy_mjpeg_clients: Dict[str, Dict[str, Any]] = {}
camera_legacy_mjpeg_clients_lock = threading.Lock()
runtime_stats_snapshot: Optional[dict[str, Any]] = None
system_status_snapshot: Optional[dict[str, Any]] = None
sorter_state_snapshot: Optional[dict[str, Any]] = None
cameras_config_snapshot: Optional[dict[str, Any]] = None
sorting_profile_status_snapshot: Optional[dict[str, Any]] = None

# Hardware lifecycle state:
# "standby" | "initializing" | "initialized" | "homing" | "ready" | "error"
#
# While state is "initializing" or "homing" the hardware worker owns every
# motor. Manual jogs and runtime resume must stay blocked until the worker
# reaches "initialized" or "ready".
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

SAMPLE_COLLECTION_SPEED_ROLES = (
    "c_channel_1",
    "c_channel_2",
    "c_channel_3",
    "classification_channel",
)
SAMPLE_COLLECTION_SPEED_ROLE_ALIASES = {
    "c1": "c_channel_1",
    "bulk": "c_channel_1",
    "carousel": "classification_channel",
    "c_channel_4": "classification_channel",
    "c4": "classification_channel",
}
SAMPLE_COLLECTION_SPEED_MIN_RPM = 0.01
SAMPLE_COLLECTION_SPEED_MAX_RPM = 25.0
SAMPLE_COLLECTION_SPEED_MAX_RPM_BY_ROLE = {
    role: SAMPLE_COLLECTION_SPEED_MAX_RPM for role in SAMPLE_COLLECTION_SPEED_ROLES
}
SAMPLE_COLLECTION_SPEED_MAX_RPM_BY_ROLE["classification_channel"] = 50.0
sample_collection_speed_rpm_by_role: Dict[str, Optional[float]] = {
    role: None for role in SAMPLE_COLLECTION_SPEED_ROLES
}
sample_collection_speed_lock = threading.RLock()

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


def setCameraService(svc: Any) -> None:
    global camera_service
    camera_service = svc


def setVisionManager(mgr: Any) -> None:
    global vision_manager
    vision_manager = mgr
    from server.classification_training import getClassificationTrainingManager
    getClassificationTrainingManager().setVisionManager(mgr)


def approveDistributionNoBinPassthrough(piece_uuid: str | None) -> bool:
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return False
    with distribution_no_bin_passthrough_lock:
        distribution_no_bin_passthrough_approvals.add(piece_uuid.strip())
    return True


def consumeDistributionNoBinPassthrough(piece_uuid: str | None) -> bool:
    if not isinstance(piece_uuid, str) or not piece_uuid.strip():
        return False
    key = piece_uuid.strip()
    with distribution_no_bin_passthrough_lock:
        if key not in distribution_no_bin_passthrough_approvals:
            return False
        distribution_no_bin_passthrough_approvals.discard(key)
    return True


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
            perf_history.record(payload, time.time())
    elif tag == "system_status" and data is not None:
        system_status_snapshot = dict(data)
    elif tag == "sorter_state" and data is not None:
        sorter_state_snapshot = dict(data)
    elif tag == "cameras_config" and data is not None:
        cameras_config_snapshot = dict(data)
    elif tag == "sorting_profile_status" and data is not None:
        sorting_profile_status_snapshot = dict(data)
    connections = active_connections[:]
    if not connections:
        return

    # Fan out to every client CONCURRENTLY with a per-client timeout. The old
    # code awaited send_json sequentially with no timeout, so a single slow or
    # half-dead client (closed laptop, sleeping phone, congested wifi) blocked
    # every other client AND the broadcaster thread behind it — making piece
    # state arrive seconds late regardless of payload size. Now a stuck client
    # costs at most SEND_TIMEOUT_S once, then gets pruned.
    async def _send(connection) -> object | None:
        try:
            await asyncio.wait_for(
                connection.send_json(event), timeout=_BROADCAST_SEND_TIMEOUT_S
            )
            return None
        except Exception:
            return connection

    _fanout_started = time.perf_counter()
    results = await asyncio.gather(*[_send(conn) for conn in connections])
    for conn in results:
        if conn is not None and conn in active_connections:
            active_connections.remove(conn)
    # Pure client-send fanout time (concurrent across clients). Compared against
    # socket.broadcast_event_ms (which also includes loop-scheduling delay) and
    # socket.loop_lag_ms, this splits "slow client" from "loop is blocked".
    if gc_ref is not None and getattr(gc_ref, "runtime_stats", None) is not None:
        gc_ref.runtime_stats.observePerfMs(
            "socket.client_send_ms", (time.perf_counter() - _fanout_started) * 1000.0
        )


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
            perf_history.record(payload, time.time())


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
    no_power_development_mode = bool(
        getattr(gc_ref, "no_power_development_mode", False)
    )
    broadcast_from_thread(
        {
            "tag": "system_status",
            "data": {
                "hardware_state": hardware_state,
                "hardware_error": hardware_error,
                "homing_step": hardware_homing_step,
                "no_power_development_mode": no_power_development_mode,
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


def normalizeSampleCollectionSpeedRole(role: object) -> str | None:
    normalized = str(role or "").strip().lower()
    if not normalized:
        return None
    normalized = SAMPLE_COLLECTION_SPEED_ROLE_ALIASES.get(normalized, normalized)
    if normalized in SAMPLE_COLLECTION_SPEED_ROLES:
        return normalized
    return None


def getSampleCollectionSpeedRpm(role: object) -> Optional[float]:
    normalized = normalizeSampleCollectionSpeedRole(role)
    if normalized is None:
        return None
    with sample_collection_speed_lock:
        return sample_collection_speed_rpm_by_role.get(normalized)


def getSampleCollectionSpeedsRpmByRole() -> Dict[str, Optional[float]]:
    with sample_collection_speed_lock:
        return {
            role: sample_collection_speed_rpm_by_role.get(role)
            for role in SAMPLE_COLLECTION_SPEED_ROLES
        }


def getSampleCollectionSpeedMaxRpm(role: object) -> float:
    normalized = normalizeSampleCollectionSpeedRole(role)
    if normalized is None:
        return SAMPLE_COLLECTION_SPEED_MAX_RPM
    return float(
        SAMPLE_COLLECTION_SPEED_MAX_RPM_BY_ROLE.get(
            normalized,
            SAMPLE_COLLECTION_SPEED_MAX_RPM,
        )
    )


def getSampleCollectionSpeedMaxRpmByRole() -> Dict[str, float]:
    return {
        role: getSampleCollectionSpeedMaxRpm(role)
        for role in SAMPLE_COLLECTION_SPEED_ROLES
    }


def setSampleCollectionSpeedRpm(role: object, rpm: object) -> Optional[float]:
    normalized = normalizeSampleCollectionSpeedRole(role)
    if normalized is None:
        raise ValueError(f"invalid sample collection speed role: {role!r}")

    if rpm is None or rpm == "":
        value = None
    else:
        try:
            value = float(rpm)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid rpm for {normalized}: {rpm!r}") from exc
        if not math.isfinite(value):
            raise ValueError(f"invalid rpm for {normalized}: {rpm!r}")
        max_rpm = getSampleCollectionSpeedMaxRpm(normalized)
        if value < SAMPLE_COLLECTION_SPEED_MIN_RPM or value > max_rpm:
            raise ValueError(
                f"rpm for {normalized} must be between "
                f"{SAMPLE_COLLECTION_SPEED_MIN_RPM:g} and {max_rpm:g}"
            )
        value = round(value, 3)

    with sample_collection_speed_lock:
        sample_collection_speed_rpm_by_role[normalized] = value
    return value


def setSampleCollectionSpeedsRpm(values: Dict[str, Any]) -> Dict[str, Optional[float]]:
    if not isinstance(values, dict):
        raise ValueError("speeds must be an object keyed by channel role")
    for role, rpm in values.items():
        setSampleCollectionSpeedRpm(role, rpm)
    return getSampleCollectionSpeedsRpmByRole()


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
