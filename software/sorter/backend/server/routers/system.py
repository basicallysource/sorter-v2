"""System lifecycle endpoints — home hardware, check status."""

from __future__ import annotations

import os
import signal
import threading
from typing import Dict, Any

from fastapi import APIRouter

import server.shared_state as shared_state

router = APIRouter()


def _system_status_payload() -> Dict[str, Any]:
    return {
        "hardware_state": shared_state.hardware_state,
        "hardware_error": shared_state.hardware_error,
        "homing_step": shared_state.hardware_homing_step,
    }


@router.get("/api/system/status")
def get_system_status() -> Dict[str, Any]:
    with shared_state.hardware_lifecycle_lock:
        return _system_status_payload()


@router.post("/api/system/reset")
def reset_system() -> Dict[str, Any]:
    """Return hardware to standby state and tear down active runtime resources."""
    with shared_state.hardware_lifecycle_lock:
        if shared_state.hardware_state == "homing":
            return {"ok": False, "hardware_state": "homing", "message": "Cannot reset while homing."}

        reset_fn = shared_state.sorter_lifecycle.reset_hardware
        shared_state.setHardwareStatus(homing_step="Resetting...")

        try:
            if reset_fn is not None:
                reset_fn()
        except Exception as exc:
            shared_state.setHardwareStatus(
                state="error",
                error=f"Reset failed: {exc}",
                clear_homing_step=True,
            )
            return {
                "ok": False,
                "hardware_state": "error",
                "message": f"Hardware reset failed: {exc}",
            }

        prepare_rt_fn = shared_state.sorter_lifecycle.prepare_rt_handle
        try:
            if prepare_rt_fn is not None:
                shared_state.setHardwareStatus(homing_step="Preparing rt runtime...")
                prepare_rt_fn()
        except Exception as exc:
            shared_state.setHardwareStatus(
                state="error",
                error=f"RT runtime prepare failed: {exc}",
                clear_homing_step=True,
            )
            return {
                "ok": False,
                "hardware_state": "error",
                "message": f"RT runtime prepare failed: {exc}",
            }

        shared_state.setHardwareStatus(
            state="standby",
            clear_error=True,
            clear_homing_step=True,
        )
        shared_state.hardware_worker_thread = None
        return {"ok": True, "hardware_state": "standby", "message": "Hardware reset to standby."}


@router.post("/api/system/home")
def home_system() -> Dict[str, Any]:
    with shared_state.hardware_lifecycle_lock:
        worker = shared_state.hardware_worker_thread
        if worker is not None and worker.is_alive():
            if shared_state.hardware_state == "homing":
                return {"ok": True, "hardware_state": "homing", "message": "Already homing."}
            return {
                "ok": False,
                "hardware_state": shared_state.hardware_state,
                "message": "Another hardware operation is already in progress.",
            }

        fn = shared_state.sorter_lifecycle.home_hardware
        if fn is None:
            return {
                "ok": False,
                "hardware_state": shared_state.hardware_state,
                "message": "No hardware start function registered.",
            }

        shared_state.setHardwareStatus(
            state="homing",
            clear_error=True,
            homing_step="Starting...",
        )

    def _run() -> None:
        try:
            fn()
        except Exception as exc:
            with shared_state.hardware_lifecycle_lock:
                shared_state.setHardwareStatus(
                    state="error",
                    error=str(exc),
                    clear_homing_step=True,
                )
        else:
            with shared_state.hardware_lifecycle_lock:
                shared_state.setHardwareStatus(
                    state="ready",
                    clear_error=True,
                    clear_homing_step=True,
                )
        finally:
            with shared_state.hardware_lifecycle_lock:
                shared_state.hardware_worker_thread = None

    thread = threading.Thread(target=_run, daemon=True)
    with shared_state.hardware_lifecycle_lock:
        shared_state.hardware_worker_thread = thread
    thread.start()
    return {"ok": True, "hardware_state": "homing", "message": "Hardware homing started."}


@router.post("/api/system/initialize")
def initialize_system() -> Dict[str, Any]:
    """Bring up the IRL without running carousel/chute homing.

    Used by the setup wizard's Motion Direction Check step so the operator can
    jog each stepper before endstops have been verified.
    """
    with shared_state.hardware_lifecycle_lock:
        worker = shared_state.hardware_worker_thread
        if worker is not None and worker.is_alive():
            return {
                "ok": False,
                "hardware_state": shared_state.hardware_state,
                "message": "Another hardware operation is already in progress.",
            }

        fn = shared_state.sorter_lifecycle.initialize_hardware
        if fn is None:
            return {
                "ok": False,
                "hardware_state": shared_state.hardware_state,
                "message": "No hardware initialize function registered.",
            }

        shared_state.setHardwareStatus(
            state="initializing",
            clear_error=True,
            homing_step="Starting...",
        )

    def _run() -> None:
        try:
            fn()
        except Exception as exc:
            with shared_state.hardware_lifecycle_lock:
                shared_state.setHardwareStatus(
                    state="error",
                    error=str(exc),
                    clear_homing_step=True,
                )
        else:
            with shared_state.hardware_lifecycle_lock:
                shared_state.setHardwareStatus(
                    state="initialized",
                    clear_error=True,
                    clear_homing_step=True,
                )
        finally:
            with shared_state.hardware_lifecycle_lock:
                shared_state.hardware_worker_thread = None

    thread = threading.Thread(target=_run, daemon=True)
    with shared_state.hardware_lifecycle_lock:
        shared_state.hardware_worker_thread = thread
    thread.start()
    return {"ok": True, "hardware_state": "initializing", "message": "Hardware initialization started."}


# Keep the old endpoint as alias for backwards compatibility
@router.post("/api/system/start")
def start_system() -> Dict[str, Any]:
    return home_system()


@router.post("/api/system/restart")
def restart_system() -> Dict[str, Any]:
    """Restart the backend process.

    Sends SIGTERM to the current process after a short delay so the HTTP
    response can be delivered first.  When running under systemd the service
    will be restarted automatically.
    """

    def _deferred_exit() -> None:
        import time
        time.sleep(0.5)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=_deferred_exit, daemon=True).start()
    return {"ok": True, "message": "Backend is restarting..."}
