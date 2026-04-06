"""System lifecycle endpoints — home hardware, check status."""

from __future__ import annotations

import threading
from typing import Dict, Any

from fastapi import APIRouter

import server.shared_state as shared_state

router = APIRouter()


@router.get("/api/system/status")
def get_system_status() -> Dict[str, Any]:
    return {
        "hardware_state": shared_state.hardware_state,
        "hardware_error": shared_state.hardware_error,
        "homing_step": shared_state.hardware_homing_step,
    }


@router.post("/api/system/reset")
def reset_system() -> Dict[str, Any]:
    """Return hardware to standby state."""
    if shared_state.hardware_state == "homing":
        return {"ok": False, "hardware_state": "homing", "message": "Cannot reset while homing."}
    shared_state.hardware_state = "standby"
    shared_state.hardware_error = None
    shared_state.hardware_homing_step = None
    return {"ok": True, "hardware_state": "standby", "message": "Hardware reset to standby."}


@router.post("/api/system/home")
def home_system() -> Dict[str, Any]:
    if shared_state.hardware_state == "homing":
        return {"ok": True, "hardware_state": "homing", "message": "Already homing."}

    fn = shared_state._hardware_start_fn
    if fn is None:
        return {"ok": False, "hardware_state": shared_state.hardware_state, "message": "No hardware start function registered."}

    shared_state.hardware_state = "homing"
    shared_state.hardware_error = None
    shared_state.hardware_homing_step = "Starting..."

    def _run() -> None:
        try:
            fn()
            shared_state.hardware_state = "ready"
        except Exception as exc:
            shared_state.hardware_state = "error"
            shared_state.hardware_error = str(exc)
            shared_state.hardware_homing_step = None

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"ok": True, "hardware_state": "homing", "message": "Hardware homing started."}


# Keep the old endpoint as alias for backwards compatibility
@router.post("/api/system/start")
def start_system() -> Dict[str, Any]:
    return home_system()
