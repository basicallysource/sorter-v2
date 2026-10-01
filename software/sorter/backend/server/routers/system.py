"""System lifecycle endpoints — home hardware, check status."""

from __future__ import annotations

import os
import signal
import threading
from typing import Callable, Dict, Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

import server.shared_state as shared_state
from hardware.fault import HardwareFault

router = APIRouter()


@router.get("/api/system/status")
def get_system_status() -> Dict[str, Any]:
    with shared_state.hardware_lifecycle_lock:
        return shared_state.systemStatusData()


@router.post("/api/system/reset")
def reset_system() -> Dict[str, Any]:
    """Return hardware to standby state and tear down active runtime resources."""
    with shared_state.hardware_lifecycle_lock:
        worker = shared_state.hardware_worker_thread
        worker_alive = worker is not None and worker.is_alive()
        if worker_alive or shared_state.hardware_state in {"homing", "initializing"}:
            return {
                "ok": False,
                "hardware_state": shared_state.hardware_state,
                "message": "Cannot reset while hardware recovery is active.",
            }

        reset_fn = shared_state._hardware_reset_fn
        shared_state.setHardwareStatus(homing_step="Resetting...")

        try:
            if reset_fn is not None:
                reset_fn()
        except Exception as exc:
            shared_state.setHardwareStatus(
                state="error",
                error=HardwareFault("Reset failed", str(exc)),
                clear_homing_step=True,
            )
            return {
                "ok": False,
                "hardware_state": "error",
                "message": f"Hardware reset failed: {exc}",
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
    """Safely recover the machine to a homed, paused runtime.

    Historically this endpoint was the broad "start hardware" button. Keep
    the URL stable for existing frontends, but route it through the same
    exclusive recovery path as ``/api/system/recover`` so there is only one
    global way back from standby/error/restart to ready.
    """
    return recover_system()


def _start_hardware_worker(
    *,
    state: str,
    step: str,
    success_state: str,
    fn: Callable[[], None] | None,
    busy_message: str,
    missing_fn_message: str,
    started_message: str,
) -> Dict[str, Any]:
    def _run() -> None:
        try:
            fn()
        except Exception as exc:
            with shared_state.hardware_lifecycle_lock:
                shared_state.setHardwareStatus(
                    state="error",
                    error=HardwareFault.of(exc),
                    clear_homing_step=True,
                )
        else:
            with shared_state.hardware_lifecycle_lock:
                shared_state.setHardwareStatus(
                    state=success_state,
                    clear_error=True,
                    clear_homing_step=True,
                )
        finally:
            with shared_state.hardware_lifecycle_lock:
                shared_state.hardware_worker_thread = None

    thread = threading.Thread(target=_run, daemon=True)

    with shared_state.hardware_lifecycle_lock:
        worker = shared_state.hardware_worker_thread
        worker_busy = worker is not None and worker.is_alive()
        state_busy = shared_state.hardware_state in {"homing", "initializing"}
        if worker_busy or state_busy:
            if shared_state.hardware_state == state:
                return {
                    "ok": True,
                    "hardware_state": state,
                    "message": busy_message,
                }
            return {
                "ok": False,
                "hardware_state": shared_state.hardware_state,
                "message": "Another hardware operation is already in progress.",
            }

        if fn is None:
            return {
                "ok": False,
                "hardware_state": shared_state.hardware_state,
                "message": missing_fn_message,
            }

        shared_state.setHardwareStatus(
            state=state,
            clear_error=True,
            homing_step=step,
        )
        shared_state.hardware_worker_thread = thread

    thread.start()
    return {"ok": True, "hardware_state": state, "message": started_message}


@router.post("/api/system/recover")
def recover_system() -> Dict[str, Any]:
    return _start_hardware_worker(
        state="homing",
        step="Starting safe recovery...",
        success_state="ready",
        fn=shared_state._hardware_start_fn,
        busy_message="Already recovering hardware.",
        missing_fn_message="No hardware recovery function registered.",
        started_message="Safe hardware recovery started.",
    )


@router.post("/api/system/initialize")
def initialize_system() -> Dict[str, Any]:
    """Bring up the IRL without running carousel/chute homing.

    Used by the setup wizard's Motion Direction Check step so the operator can
    jog each stepper before endstops have been verified.
    """
    return _start_hardware_worker(
        state="initializing",
        step="Starting...",
        success_state="initialized",
        fn=shared_state._hardware_initialize_fn,
        busy_message="Already initializing hardware.",
        missing_fn_message="No hardware initialize function registered.",
        started_message="Hardware initialization started.",
    )


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


@router.post("/api/system/shutdown")
def shutdown_machine() -> Dict[str, Any]:
    """Power down the whole Linux machine — equivalent to `shutdown -h now`.

    The shell command runs from a background thread after a short delay so the
    HTTP response is delivered before the OS starts tearing services down.
    """

    def _deferred_shutdown() -> None:
        import subprocess
        import time

        time.sleep(0.5)
        # Backend runs as root on the Pi, so a plain `shutdown` works; fall back to
        # sudo / systemctl in case it's ever launched as an unprivileged user.
        candidates = [
            ["shutdown", "-h", "now"],
            ["systemctl", "poweroff"],
            ["sudo", "-n", "shutdown", "-h", "now"],
            ["sudo", "-n", "systemctl", "poweroff"],
        ]
        logger = getattr(shared_state.gc_ref, "logger", None)
        for cmd in candidates:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0)
                if result.returncode == 0:
                    return
                if logger is not None:
                    logger.error(f"Shutdown command {cmd!r} failed: {result.stderr.strip()}")
            except FileNotFoundError:
                continue
            except Exception as exc:
                if logger is not None:
                    logger.error(f"Shutdown command {cmd!r} raised: {exc}")
        if logger is not None:
            logger.error("All shutdown commands failed; machine did not power down.")

    threading.Thread(target=_deferred_shutdown, daemon=True).start()
    return {"ok": True, "message": "Machine is powering down..."}


@router.post("/api/system/reboot")
def reboot_machine() -> Dict[str, Any]:
    """Reboot the whole Linux machine — equivalent to `reboot`.

    Same deal as the shutdown endpoint: the shell command runs from a
    background thread after a short delay so the HTTP response is delivered
    before the OS starts tearing services down.
    """

    def _deferred_reboot() -> None:
        import subprocess
        import time

        time.sleep(0.5)
        # Backend runs as root on the Pi, so a plain `reboot` works; fall back to
        # sudo / systemctl in case it's ever launched as an unprivileged user.
        candidates = [
            ["shutdown", "-r", "now"],
            ["systemctl", "reboot"],
            ["sudo", "-n", "shutdown", "-r", "now"],
            ["sudo", "-n", "systemctl", "reboot"],
        ]
        logger = getattr(shared_state.gc_ref, "logger", None)
        for cmd in candidates:
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10.0)
                if result.returncode == 0:
                    return
                if logger is not None:
                    logger.error(f"Reboot command {cmd!r} failed: {result.stderr.strip()}")
            except FileNotFoundError:
                continue
            except Exception as exc:
                if logger is not None:
                    logger.error(f"Reboot command {cmd!r} raised: {exc}")
        if logger is not None:
            logger.error("All reboot commands failed; machine did not restart.")

    threading.Thread(target=_deferred_reboot, daemon=True).start()
    return {"ok": True, "message": "Machine is restarting..."}


@router.get("/api/system/dashboard-config")
def get_dashboard_config() -> Dict[str, Any]:
    from toml_config import getDashboardConfig, incidentDefinitions

    return {
        "ok": True,
        **getDashboardConfig(),
        "incident_definitions": incidentDefinitions(),
    }


def _active_runtime_incident() -> dict[str, Any] | None:
    runtime_stats = (
        getattr(shared_state.gc_ref, "runtime_stats", None)
        if shared_state.gc_ref is not None
        else None
    )
    if runtime_stats is None or not hasattr(runtime_stats, "activeIncident"):
        return None
    try:
        active = runtime_stats.activeIncident()
    except Exception:
        return None
    return active if isinstance(active, dict) else None


def _apply_dashboard_incident_policy(config: dict[str, Any]) -> dict[str, Any] | None:
    handling = config.get("incident_handling")
    if not isinstance(handling, dict):
        return None
    active = _active_runtime_incident()
    if not isinstance(active, dict):
        return None

    kind = str(active.get("kind") or "")
    try:
        from toml_config import incidentHandlingMode

        mode = incidentHandlingMode(kind)
    except Exception:
        mode = handling.get(kind)
    if mode != "off":
        return None
    runtime_stats = (
        getattr(shared_state.gc_ref, "runtime_stats", None)
        if shared_state.gc_ref is not None
        else None
    )
    if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
        runtime_stats.clearActiveIncident(kind=kind)
        return {"ok": True, "cleared": True, "kind": kind}
    return None


@router.post("/api/system/dashboard-config")
def set_dashboard_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    from toml_config import setDashboardConfig

    merged = setDashboardConfig(payload or {})
    applied = _apply_dashboard_incident_policy(merged)
    response = {"ok": True, **merged}
    if applied is not None:
        response["active_incident_policy_applied"] = applied
    return response


def _sample_collector():
    controller = shared_state.controller_ref
    gc = getattr(controller, "gc", None) if controller is not None else shared_state.gc_ref
    return getattr(gc, "sample_collector", None)


def _sample_storage_payload() -> Dict[str, Any]:
    from server.classification_training import getClassificationTrainingManager

    info = getClassificationTrainingManager().getStorageStatus()
    cap = info.get("storage_cap_bytes")
    used = info.get("storage_used_bytes")
    mb = 1024 * 1024
    return {
        "storage_cap_bytes": cap if isinstance(cap, int) else None,
        "storage_cap_mb": round(cap / mb) if isinstance(cap, int) else None,
        "storage_used_bytes": used if isinstance(used, int) else None,
        "storage_used_mb": round(used / mb) if isinstance(used, int) else None,
    }


@router.get("/api/system/sample-capture")
def get_sample_capture() -> Dict[str, Any]:
    collector = _sample_collector()
    if collector is None:
        status: Dict[str, Any] = {"ok": False, "enabled": False, "reason": "collector_not_initialized"}
    else:
        status = collector.status()
    status.update(_sample_storage_payload())
    return status


@router.post("/api/system/sample-capture")
def set_sample_capture(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Standalone training-image capture: one enable toggle + a cadence.

    Independent of machine mode. ``enabled`` flips picture-taking on/off. Cadence is either
    the decay schedule (``decay_enabled`` + ``burst_interval_s`` /
    ``floor_interval_s`` / ``ramp_hours`` / ``jitter_frac``, default) or a
    fixed rate (``rate_hz`` / ``interval_s``, default 10s). ``reset_decay``
    re-arms the burst. All persist.
    """
    if "storage_cap_mb" in payload and payload.get("storage_cap_mb") is not None:
        from server.classification_training import getClassificationTrainingManager

        cap_mb = float(payload["storage_cap_mb"])
        cap_bytes = int(cap_mb * 1024 * 1024) if cap_mb > 0 else None
        getClassificationTrainingManager().setStorageCapBytes(cap_bytes)

    collector = _sample_collector()
    if collector is None:
        result: Dict[str, Any] = {"ok": False, "enabled": False, "reason": "collector_not_initialized"}
        result.update(_sample_storage_payload())
        return result
    if "interval_s" in payload and payload.get("interval_s") is not None:
        collector.setIntervalSeconds(float(payload["interval_s"]))
    elif "rate_hz" in payload and payload.get("rate_hz") is not None:
        try:
            collector.setRateHz(float(payload["rate_hz"]))
        except ValueError as exc:
            result = collector.status()
            result.update({"ok": False, "reason": "invalid_rate", "message": str(exc)})
            result.update(_sample_storage_payload())
            return result
    decay_keys = ("decay_enabled", "burst_interval_s", "floor_interval_s", "ramp_hours", "jitter_frac")
    if any(key in payload for key in decay_keys):
        collector.setDecayConfig(
            decay_enabled=bool(payload["decay_enabled"]) if "decay_enabled" in payload else None,
            burst_interval_s=float(payload["burst_interval_s"]) if payload.get("burst_interval_s") is not None else None,
            floor_interval_s=float(payload["floor_interval_s"]) if payload.get("floor_interval_s") is not None else None,
            ramp_hours=float(payload["ramp_hours"]) if payload.get("ramp_hours") is not None else None,
            jitter_frac=float(payload["jitter_frac"]) if payload.get("jitter_frac") is not None else None,
        )
    if payload.get("reset_decay"):
        collector.resetDecay()
    if "annotate" in payload:
        collector.setAnnotate(bool(payload.get("annotate")))
    if "enabled" in payload:
        collector.setEnabled(bool(payload.get("enabled")))
    result = collector.status()
    result.update(_sample_storage_payload())
    return result


class ClientErrorPayload(BaseModel):
    message: Optional[str] = None
    source: Optional[str] = None
    lineno: Optional[int] = None
    colno: Optional[int] = None
    stack: Optional[str] = None
    type: Optional[str] = None


@router.post("/api/system/client-error")
def report_client_error(payload: ClientErrorPayload) -> Dict[str, Any]:
    logger = getattr(shared_state.gc_ref, "logger", None)
    msg = payload.message or "(no message)"
    location = ""
    if payload.source:
        location = f" @ {payload.source}"
        if payload.lineno is not None:
            location += f":{payload.lineno}"
    stack = f"\n{payload.stack}" if payload.stack else ""
    full = f"[browser] {payload.type or 'error'}: {msg}{location}{stack}"
    if logger is not None:
        logger.error(full)
    else:
        import logging
        logging.getLogger(__name__).error(full)
    return {"ok": True}
