"""Shared mutable state and setter functions for the Sorter API.

All module-level globals live here so that ``api.py`` and every router can
import this single module without circular dependencies.
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from typing import Any, Dict, Optional

from fastapi import WebSocket, status

from global_config import GlobalConfig
from hardware.fault import HardwareFault
from server.security import describe_origin_decision, websocket_connection_allowed

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

server_loop: Optional[asyncio.AbstractEventLoop] = None
command_queue: Optional[queue.Queue] = None
controller_ref: Optional[Any] = None
gc_ref: Optional[GlobalConfig] = None
vision_manager: Optional[Any] = None

# Liveness of the websocket pipeline: stamped on the event loop each time a
# message is handed to the clients (a heartbeat goes out every 2 s). A watchdog
# thread (main.py) compares it against wall-clock: if clients are connected but
# nothing has gone out for a while, the loop is wedged and the live feed frozen.
last_broadcast_ok_ts: float = 0.0
camera_service: Optional[Any] = None
pulse_locks: Dict[str, threading.Lock] = {}
distribution_no_bin_passthrough_approvals: set[str] = set()
distribution_no_bin_passthrough_lock = threading.RLock()
# Both set by the broadcaster thread (main.py): the full snapshot behind
# GET /runtime-stats, and the live part last pushed to the dashboard.
runtime_stats_snapshot: Optional[dict[str, Any]] = None
runtime_stats_live: Optional[dict[str, Any]] = None

# Hardware lifecycle state:
# "standby" | "initializing" | "initialized" | "homing" | "ready" | "error"
#
# While state is "initializing" or "homing" the hardware worker owns every
# motor. Manual jogs and runtime resume must stay blocked until the worker
# reaches "initialized" or "ready".
hardware_state: str = "standby"
# What stopped or needs the operator: {"title", "message"} (HardwareFault.data()).
hardware_error: Optional[dict[str, str]] = None
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


# A client that cannot take a message for this long (its socket stays backed
# up) is closed. The heartbeat lets its tab notice silence and reconnect.
WS_SLOW_CLIENT_LIMIT_S = 5.0
WS_HEARTBEAT_INTERVAL_S = 2.0
ws_clients: set["WsClient"] = set()
ws_slow_clients_closed = 0


async def acceptWebsocket(websocket: WebSocket) -> bool:
    """Accept a websocket from the UI; refuse one from any other origin."""
    host = websocket.client.host if websocket.client is not None else None
    origin = websocket.headers.get("Origin")
    if websocket_connection_allowed(origin, host):
        await websocket.accept()
        return True
    if gc_ref is not None:
        gc_ref.logger.info(f"[WS reject] client_host={host!r} {describe_origin_decision(origin)}")
    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="WebSocket origin not allowed.")
    return False


class WsClient:
    """One websocket and what waits for it: the latest message of each kind
    (per tag; per piece for known_object). A slow client skips the versions it
    could not take instead of queueing them, and never holds up the others."""

    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket
        self.pending: dict[str, str] = {}
        self.wake = asyncio.Event()

    def push(self, key: str, text: str) -> None:
        self.pending.pop(key, None)
        self.pending[key] = text
        self.wake.set()

    async def send(self) -> None:
        """Send until the socket fails or stays unwritable past the limit."""
        global ws_slow_clients_closed
        try:
            while True:
                while self.pending:
                    text = self.pending.pop(next(iter(self.pending)))
                    started = time.perf_counter()
                    await asyncio.wait_for(self.websocket.send_text(text), WS_SLOW_CLIENT_LIMIT_S)
                    observePerfMs("socket.client_send_ms", (time.perf_counter() - started) * 1000.0)
                self.wake.clear()
                await self.wake.wait()
        except TimeoutError:
            ws_slow_clients_closed += 1
            observePerfMs("socket.slow_client_closed_ms", WS_SLOW_CLIENT_LIMIT_S * 1000.0)
            if gc_ref is not None:
                host = self.websocket.client.host if self.websocket.client else "?"
                gc_ref.logger.warning(
                    f"[ws] closing {host}: it took no message for {WS_SLOW_CLIENT_LIMIT_S:.0f} s "
                    f"({ws_slow_clients_closed} slow client(s) closed since start)"
                )
        except Exception:
            pass  # the socket is gone; the endpoint's reader sees the disconnect


def observePerfMs(name: str, value_ms: float) -> None:
    if gc_ref is not None and getattr(gc_ref, "runtime_stats", None) is not None:
        gc_ref.runtime_stats.observePerfMs(name, value_ms)


def encodeEvent(event: dict) -> str:
    return json.dumps(event, separators=(",", ":"), ensure_ascii=False, default=str)


def broadcast(event: dict) -> None:
    """Send an event to every websocket client; safe from any thread. It is
    encoded once, here in the caller's thread, and never waits for a client."""
    tag = str(event.get("tag"))
    key = f"{tag}:{event['data'].get('uuid')}" if tag == "known_object" else tag
    text = encodeEvent(event)
    loop = server_loop
    if loop is not None:
        try:
            loop.call_soon_threadsafe(fanOut, key, text)
        except RuntimeError:
            pass  # the loop has shut down


def fanOut(key: str, text: str) -> None:
    """On the event loop: hand an encoded message to every client's sender."""
    global last_broadcast_ok_ts
    last_broadcast_ok_ts = time.time()
    for client in ws_clients:
        client.push(key, text)


def systemStatusData() -> dict[str, Any]:
    return {
        "hardware_state": hardware_state,
        "hardware_error": hardware_error,
        "homing_step": hardware_homing_step,
        "no_power_development_mode": bool(getattr(gc_ref, "no_power_development_mode", False)),
    }


def publishSystemStatus() -> None:
    """Broadcast the current hardware status snapshot over WS."""
    broadcast({"tag": "system_status", "data": systemStatusData()})


def setHardwareStatus(
    *,
    state: Optional[str] = None,
    error: Optional[HardwareFault] = None,
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
    if error is not None and error.data() != hardware_error:
        hardware_error = error.data()
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


def publishSorterState(state: str) -> None:
    """Broadcast the sorter-controller FSM state over WS."""
    broadcast(
        {
            "tag": "sorter_state",
            "data": {
                "state": state,
            },
        }
    )


def publishCamerasConfig(cameras: Dict[str, Any]) -> None:
    """Broadcast the camera role → source map over WS."""
    broadcast(
        {
            "tag": "cameras_config",
            "data": {"cameras": dict(cameras)},
        }
    )


def publishSortingProfileStatus(status: Dict[str, Any]) -> None:
    """Broadcast the sorting profile sync status + local profile metadata over WS."""
    sync_state = status.get("sync_state") if isinstance(status.get("sync_state"), dict) else {}
    local_profile = status.get("local_profile") if isinstance(status.get("local_profile"), dict) else {}
    broadcast(
        {
            "tag": "sorting_profile_status",
            "data": {
                "sync_state": dict(sync_state),
                "local_profile": dict(local_profile),
            },
        }
    )
