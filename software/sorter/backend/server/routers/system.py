"""System lifecycle endpoints — home hardware, check status."""

from __future__ import annotations

import os
import signal
import threading
from typing import Callable, Dict, Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel

import server.shared_state as shared_state
from subsystems.sample_collection_speed import (
    default_speed_rpm,
    microsteps_from_stepper_config,
)

router = APIRouter()


def _system_status_payload() -> Dict[str, Any]:
    return {
        "hardware_state": shared_state.hardware_state,
        "hardware_error": shared_state.hardware_error,
        "homing_step": shared_state.hardware_homing_step,
        "no_power_development_mode": bool(
            getattr(shared_state.gc_ref, "no_power_development_mode", False)
        ),
    }


@router.get("/api/system/status")
def get_system_status() -> Dict[str, Any]:
    with shared_state.hardware_lifecycle_lock:
        return _system_status_payload()


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
                error=f"Reset failed: {exc}",
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
                    error=str(exc),
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


def _shared_variables():
    controller = shared_state.controller_ref
    coordinator = getattr(controller, "coordinator", None) if controller is not None else None
    return getattr(coordinator, "shared", None)


def _open_all_layer_doors_for_sample_collection() -> Dict[str, Any]:
    controller = shared_state.controller_ref
    irl = getattr(controller, "irl", None) if controller is not None else shared_state.getActiveIRL()
    gc = getattr(controller, "gc", None) if controller is not None else shared_state.gc_ref
    if irl is None:
        return {"ok": False, "reason": "hardware_not_initialized", "opened": 0, "errors": []}
    if bool(getattr(gc, "disable_servos", False)):
        return {"ok": True, "reason": "servos_disabled", "opened": 0, "errors": []}

    servos = list(getattr(irl, "servos", []) or [])
    errors: list[dict[str, Any]] = []
    opened = 0
    for index, servo in enumerate(servos):
        if not bool(getattr(servo, "available", True)):
            errors.append(
                {
                    "layer_index": index,
                    "reason": "servo_unavailable",
                }
            )
            continue
        try:
            open_fn = getattr(servo, "open", None)
            if not callable(open_fn):
                errors.append(
                    {
                        "layer_index": index,
                        "reason": "open_not_supported",
                    }
                )
                continue
            open_fn()
            opened += 1
        except Exception as exc:
            errors.append(
                {
                    "layer_index": index,
                    "reason": str(exc),
                }
            )

    logger = getattr(gc, "logger", None)
    if logger is not None:
        if errors and hasattr(logger, "warning"):
            logger.warning(
                "Sample collection mode: opened %d/%d layer doors; errors=%r"
                % (opened, len(servos), errors)
            )
        elif hasattr(logger, "info"):
            logger.info(
                "Sample collection mode: opened %d/%d layer doors for discard passthrough"
                % (opened, len(servos))
            )

    return {"ok": len(errors) == 0, "opened": opened, "errors": errors}


def _irl_config_for_speed_defaults():
    controller = shared_state.controller_ref
    coordinator = getattr(controller, "coordinator", None) if controller is not None else None
    config = getattr(coordinator, "irl_config", None)
    if config is not None:
        return config
    config = getattr(shared_state.vision_manager, "_irl_config", None)
    if config is not None:
        return config
    try:
        from irl.config import mkIRLConfig

        return mkIRLConfig()
    except Exception:
        return None


def _sample_collection_default_speeds_rpm() -> Dict[str, float | None]:
    config = _irl_config_for_speed_defaults()
    if config is None:
        return {role: None for role in shared_state.SAMPLE_COLLECTION_SPEED_ROLES}
    feeder_config = getattr(config, "feeder_config", None)
    if feeder_config is None:
        return {role: None for role in shared_state.SAMPLE_COLLECTION_SPEED_ROLES}

    specs = {
        "c_channel_1": (
            getattr(feeder_config, "first_rotor", None),
            getattr(config, "c_channel_1_rotor_stepper", None),
        ),
        "c_channel_2": (
            getattr(feeder_config, "second_rotor_normal", None),
            getattr(config, "c_channel_2_rotor_stepper", None),
        ),
        "c_channel_3": (
            getattr(feeder_config, "third_rotor_normal", None),
            getattr(config, "c_channel_3_rotor_stepper", None),
        ),
        "classification_channel": (
            getattr(feeder_config, "classification_channel_eject", None),
            getattr(config, "c_channel_4_rotor_stepper", None)
            or getattr(config, "carousel_stepper", None),
        ),
    }

    defaults: Dict[str, float | None] = {}
    for role, (pulse_config, stepper_config) in specs.items():
        speed = getattr(pulse_config, "microsteps_per_second", None)
        if not isinstance(speed, int) or isinstance(speed, bool) or speed <= 0:
            defaults[role] = None
            continue
        defaults[role] = default_speed_rpm(
            speed,
            microsteps=microsteps_from_stepper_config(stepper_config),
        )
    return defaults


def _sample_collection_speeds_payload() -> Dict[str, Any]:
    overrides = shared_state.getSampleCollectionSpeedsRpmByRole()
    defaults = _sample_collection_default_speeds_rpm()
    effective = {
        role: overrides.get(role) if overrides.get(role) is not None else defaults.get(role)
        for role in shared_state.SAMPLE_COLLECTION_SPEED_ROLES
    }
    shared = _shared_variables()
    return {
        "ok": True,
        "roles": list(shared_state.SAMPLE_COLLECTION_SPEED_ROLES),
        "aliases": dict(shared_state.SAMPLE_COLLECTION_SPEED_ROLE_ALIASES),
        "min_rpm": shared_state.SAMPLE_COLLECTION_SPEED_MIN_RPM,
        "max_rpm": shared_state.SAMPLE_COLLECTION_SPEED_MAX_RPM,
        "max_rpm_by_role": shared_state.getSampleCollectionSpeedMaxRpmByRole(),
        "speeds_rpm_by_role": overrides,
        "default_speeds_rpm_by_role": defaults,
        "effective_speeds_rpm_by_role": effective,
        "sample_collection_mode": (
            bool(getattr(shared, "sample_collection_mode", False))
            if shared is not None
            else False
        ),
        "sample_collection_mode_available": shared is not None,
    }


@router.get("/api/system/dashboard-config")
def get_dashboard_config() -> Dict[str, Any]:
    from toml_config import getDashboardConfig

    return {"ok": True, **getDashboardConfig()}


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


def _feeding_runtime_state() -> Any | None:
    controller = shared_state.controller_ref
    coordinator = getattr(controller, "coordinator", None) if controller is not None else None
    feeder = getattr(coordinator, "feeder", None)
    states_map = getattr(feeder, "states_map", None)
    if isinstance(states_map, dict):
        for state in states_map.values():
            if hasattr(state, "acknowledgeDropzoneStuckIncident"):
                return state
    return None


def _classification_exit_runtime_state() -> Any | None:
    controller = shared_state.controller_ref
    coordinator = getattr(controller, "coordinator", None) if controller is not None else None
    classification = getattr(coordinator, "classification", None) if coordinator is not None else None
    states_map = getattr(classification, "states_map", None)
    if isinstance(states_map, dict):
        for state in states_map.values():
            if hasattr(state, "approveExitReleaseIncident"):
                return state
    return None


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
    if mode == "off":
        runtime_stats = (
            getattr(shared_state.gc_ref, "runtime_stats", None)
            if shared_state.gc_ref is not None
            else None
        )
        if kind == "channel_dropzone_stuck":
            feeding = _feeding_runtime_state()
            try:
                if feeding is not None:
                    return feeding.clearDropzoneStuckIncident(
                        str(active.get("channel") or ""),
                        int(active.get("global_id", active.get("track_id"))),
                    )
            except Exception:
                pass
        source_kind = str(active.get("source_kind") or "")
        classification_exit = kind == "classification_exit_release" or (
            kind == "exit_stuck"
            and (source_kind == "classification_exit_release" or active.get("piece_uuid") is not None)
        )
        channel_exit = kind == "channel_exit_stuck" or (
            kind == "exit_stuck"
            and (source_kind == "channel_exit_stuck" or active.get("channel") in {"c2", "c3"})
        )
        if classification_exit:
            running = _classification_exit_runtime_state()
            try:
                if running is not None:
                    return running.clearExitReleaseIncident(active.get("piece_uuid"))
            except Exception:
                pass
        if channel_exit:
            if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
                runtime_stats.clearActiveIncident(kind=kind)
                return {"ok": True, "cleared": True, "kind": kind}
        if runtime_stats is not None and hasattr(runtime_stats, "clearActiveIncident"):
            runtime_stats.clearActiveIncident(kind=kind)
            return {"ok": True, "cleared": True, "kind": kind}
        return None
    if mode != "automatic":
        return None

    if kind == "channel_dropzone_stuck":
        feeding = _feeding_runtime_state()
        if feeding is None:
            return None
        try:
            return feeding.acknowledgeDropzoneStuckIncident(
                str(active.get("channel") or ""),
                int(active.get("global_id", active.get("track_id"))),
            )
        except Exception:
            return None

    source_kind = str(active.get("source_kind") or "")
    if kind == "classification_exit_release" or (
        kind == "exit_stuck"
        and (source_kind == "classification_exit_release" or active.get("piece_uuid") is not None)
    ):
        running = _classification_exit_runtime_state()
        if running is None:
            return None
        try:
            incident = running.approveExitReleaseIncident(active.get("piece_uuid"))
            return {"ok": True, "approved": True, "incident": incident}
        except Exception:
            return None

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


@router.get("/api/system/profiler-config")
def get_profiler_config() -> Dict[str, Any]:
    from toml_config import getProfilerConfig

    return {"ok": True, **getProfilerConfig()}


@router.post("/api/system/profiler-config")
def set_profiler_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    from toml_config import setProfilerConfig
    from defs.events import SetProfilerEnabledEvent, SetProfilerEnabledData

    merged = setProfilerConfig(payload or {})
    # Apply live to the running main loop so the toggle takes effect without a
    # restart; the toml write makes it survive one.
    if shared_state.command_queue is not None:
        shared_state.command_queue.put(
            SetProfilerEnabledEvent(
                tag="set_profiler_enabled",
                data=SetProfilerEnabledData(enabled=bool(merged["enabled"])),
            )
        )
    return {"ok": True, **merged}


@router.get("/api/system/sample-collection-mode")
def get_sample_collection_mode() -> Dict[str, Any]:
    shared = _shared_variables()
    if shared is None:
        return {"ok": False, "enabled": False, "reason": "controller_not_initialized"}
    return {"ok": True, "enabled": bool(getattr(shared, "sample_collection_mode", False))}


@router.post("/api/system/sample-collection-mode")
def set_sample_collection_mode(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Toggle the feeder's sample-collection bypass.

    When enabled, C3 advances pieces past the cameras regardless of the
    classification-channel downstream gate. Use during training-sample
    drives where the classification pipeline may be clogged by ghost
    detections we are explicitly trying to record samples to retrain
    against.
    """
    shared = _shared_variables()
    if shared is None:
        return {"ok": False, "reason": "controller_not_initialized"}
    enabled = bool(payload.get("enabled", False))
    shared.sample_collection_mode = enabled
    doors = (
        _open_all_layer_doors_for_sample_collection()
        if enabled
        else {"ok": True, "opened": 0, "errors": []}
    )
    return {
        "ok": True,
        "enabled": shared.sample_collection_mode,
        "doors": doors,
    }


@router.get("/api/system/sample-collection-speeds")
def get_sample_collection_speeds() -> Dict[str, Any]:
    return _sample_collection_speeds_payload()


@router.post("/api/system/sample-collection-speeds")
def set_sample_collection_speeds(payload: Dict[str, Any]) -> Dict[str, Any]:
    speeds = payload.get("speeds_rpm_by_role")
    if speeds is None:
        speeds = payload.get("speeds_rpm")
    if speeds is None:
        speeds = payload
    try:
        shared_state.setSampleCollectionSpeedsRpm(speeds)
    except ValueError as exc:
        result = _sample_collection_speeds_payload()
        result.update({"ok": False, "reason": "invalid_speed", "message": str(exc)})
        return result
    return _sample_collection_speeds_payload()


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
    """Standalone training-image capture: one enable toggle + a target rate.

    Independent of machine mode and of the legacy sample_collection_mode
    feeder bypass. ``enabled`` flips picture-taking on/off; ``rate_hz`` or
    ``interval_s`` sets the cadence (default 1 every 2s). Both persist.
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
    if "annotate" in payload:
        collector.setAnnotate(bool(payload.get("annotate")))
    if "enabled" in payload:
        collector.setEnabled(bool(payload.get("enabled")))
    result = collector.status()
    result.update(_sample_storage_payload())
    return result


@router.post("/api/system/force-teacher-capture")
def force_teacher_capture(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Queue a Gemini-labeled teacher capture for a given role on demand.

    Bypasses the YOLO-driven classic trigger so we can still collect
    Gemini-labeled samples from a channel whose live detector is missing
    real pieces (typical for C4 carousel until a carousel-trained model
    exists). Accepts C4 aliases plus C2/C3.
    """
    role = str(payload.get("role") or "").strip()
    role = {
        "c4": "carousel",
        "c_channel_4": "carousel",
        "classification_channel": "carousel",
    }.get(role, role)
    if role not in {"carousel", "c_channel_2", "c_channel_3"}:
        return {
            "ok": False,
            "reason": "invalid_role",
            "valid": [
                "carousel",
                "classification_channel",
                "c4",
                "c_channel_2",
                "c_channel_3",
            ],
        }
    vm = shared_state.vision_manager
    if vm is None or not hasattr(vm, "forceQueueAuxiliaryTeacherCapture"):
        return {"ok": False, "reason": "vision_not_initialized"}
    queued = bool(vm.forceQueueAuxiliaryTeacherCapture(role))
    return {"ok": True, "role": role, "queued": queued}


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
