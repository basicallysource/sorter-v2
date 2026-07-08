"""Router for stepper motor control and TMC driver settings endpoints."""

from __future__ import annotations

import math
import os
import random
import threading
import time
from typing import Any, Dict, List, Optional

import stepper_telemetry
from toml_config import loadTomlFile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from defs.events import (
    PauseCommandData,
    PauseCommandEvent,
    ResumeCommandData,
    ResumeCommandEvent,
)
from defs.sorter_controller import SorterLifecycle
from irl.parse_user_toml import (
    DEFAULT_STEPPER_IHOLD,
    DEFAULT_STEPPER_IHOLD_DELAY,
    DEFAULT_STEPPER_IRUN,
    DEFAULT_STEPPER_STALLGUARD,
)
from server import shared_state

router = APIRouter()

MAX_STEPPER_PULSE_DURATION_S = 120.0


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StateResponse(BaseModel):
    state: str
    camera_layout: str = "default"


class CommandResponse(BaseModel):
    success: bool


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


class StepperJitterResponse(BaseModel):
    success: bool
    stepper: str
    amplitude_deg: float
    amplitude_microsteps: int
    cycles: int
    speed: int
    acceleration: int
    estimated_duration_s: float


class StepperStopResponse(BaseModel):
    success: bool
    stepper: str


class StepperStopAllResponse(BaseModel):
    success: bool
    steppers: List[str]


class C4SectorMoveResponse(BaseModel):
    success: bool
    executed: bool
    stepper: str
    from_sector: int
    to_sector: int
    sector_delta: int
    output_delta_deg: float
    motor_delta_deg: float
    motor_microsteps: int
    direction: str
    gear_ratio: float
    microsteps: int
    motor_steps_per_revolution: int
    min_speed_microsteps_per_second: int
    max_speed_microsteps_per_second: int
    acceleration_microsteps_per_second_sq: int | None = None
    requested_max_speed_microsteps_per_second: int | None = None
    requested_acceleration_microsteps_per_second_sq: int | None = None
    configured_stepper_default_speed_microsteps_per_second: int | None = None
    warnings: List[str] = Field(default_factory=list)


class TmcSettingsRequest(BaseModel):
    irun: Optional[int] = None
    ihold: Optional[int] = None
    microsteps: Optional[int] = None
    stealthchop: Optional[bool] = None
    coolstep: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _getCameraLayout() -> str:
    if shared_state.vision_manager is not None:
        return getattr(shared_state.vision_manager, "_camera_layout", "default")
    # Fallback: read directly from TOML
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if params_path and os.path.exists(params_path):
        raw = loadTomlFile(params_path)
        return raw.get("cameras", {}).get("layout", "default")
    return "default"


def _stepper_mapping() -> Dict[str, Any]:
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Start or home the system first.")
    c4_stepper = getattr(irl, "c_channel_4_rotor_stepper", None) or getattr(
        irl, "carousel_stepper", None
    )
    return {
        "c_channel_1": getattr(irl, "c_channel_1_rotor_stepper", None),
        "c_channel_2": getattr(irl, "c_channel_2_rotor_stepper", None),
        "c_channel_3": getattr(irl, "c_channel_3_rotor_stepper", None),
        "c_channel_4": c4_stepper,
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


def _hardware_worker_alive() -> bool:
    worker = shared_state.hardware_worker_thread
    return bool(worker is not None and worker.is_alive())


def _ensure_runtime_ready(action: str) -> None:
    state = shared_state.hardware_state
    if _hardware_worker_alive() or state in {"homing", "initializing"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} while hardware is {state}.",
        )
    if state != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} while hardware is {state}; run Safe Home first.",
        )


def _ensure_no_blocking_fault(action: str) -> None:
    from stepper_stall_monitor import (
        STEPPER_STALL_INCIDENT_KIND,
        CHUTE_NEEDS_HOMING_INCIDENT_KIND,
    )

    gc = shared_state.gc_ref
    runtime_stats = getattr(gc, "runtime_stats", None) if gc is not None else None
    incident = runtime_stats.activeIncident() if runtime_stats is not None else None
    kind = incident.get("kind") if isinstance(incident, dict) else None
    if kind == STEPPER_STALL_INCIDENT_KIND:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action}: a motor stall is unresolved. Clear the stall first.",
        )
    if kind == CHUTE_NEEDS_HOMING_INCIDENT_KIND:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action}: the chute must be re-homed after a stall first.",
        )


def _ensure_manual_motion_allowed(action: str) -> None:
    state = shared_state.hardware_state
    if _hardware_worker_alive() or state in {"homing", "initializing"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} while hardware is {state}.",
        )


def _active_irl_config() -> Any | None:
    controller = shared_state.controller_ref
    if controller is not None and hasattr(controller, "coordinator"):
        coordinator = controller.coordinator
        config = getattr(coordinator, "irl_config", None)
        if config is not None:
            return config
    return None


def _halt_stepper(stepper: Any, *, force: bool = False) -> None:
    halt = getattr(stepper, "halt", None)
    if callable(halt):
        if not bool(halt(disable_driver=True)):
            raise RuntimeError("halt() timed out or was not acknowledged")
        return

    errors: list[str] = []
    stopped = False

    if hasattr(stepper, "enable_force") and force:
        try:
            stepper.enable_force(False)
            stopped = True
        except Exception as e:
            errors.append(f"disable failed: {e}")
    elif hasattr(stepper, "enabled"):
        try:
            stepper.enabled = False
            stopped = True
        except Exception as e:
            errors.append(f"disable failed: {e}")

    if hasattr(stepper, "move_at_speed"):
        try:
            is_stopped = stepper.stopped_force() if force and hasattr(stepper, "stopped_force") else stepper.stopped
            if not bool(is_stopped):
                result = stepper.move_at_speed(0, force=force)
                stopped = stopped or bool(result)
                if result is False:
                    errors.append("move_at_speed(0) was not acknowledged")
            else:
                stopped = True
        except Exception as e:
            errors.append(f"move_at_speed(0) failed: {e}")

    if hasattr(stepper, "stop"):
        try:
            stepper.stop()
            stopped = True
        except Exception as e:
            errors.append(f"stop() failed: {e}")

    if not stopped:
        detail = "; ".join(errors) if errors else "No supported stop method found"
        raise RuntimeError(detail)


def _stop_stepper_after_delay(stepper: Any, delay_s: float, lock: threading.Lock, *, force: bool = False) -> None:
    try:
        time.sleep(delay_s)
        _halt_stepper(stepper, force=force)
    except Exception:
        pass
    finally:
        try:
            lock.release()
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# TMC2209 Driver Settings – constants & helpers
# ---------------------------------------------------------------------------

TMC_REG_GCONF = 0x00
TMC_REG_GSTAT = 0x01
TMC_REG_IFCNT = 0x02
TMC_REG_IOIN = 0x06
TMC_REG_FACTORY_CONF = 0x07
TMC_REG_IHOLD_IRUN = 0x10
TMC_REG_TSTEP = 0x12
TMC_REG_TCOOLTHRS = 0x14
TMC_REG_COOLCONF = 0x42
TMC_REG_SGTHRS = 0x40
TMC_REG_SG_RESULT = 0x41
TMC_REG_MSCNT = 0x6A
TMC_REG_MSCURACT = 0x6B
TMC_REG_CHOPCONF = 0x6C
TMC_REG_DRV_STATUS = 0x6F
TMC_REG_PWM_CONF = 0x70
TMC_REG_PWM_SCALE = 0x71
TMC_REG_PWM_AUTO = 0x72

MRES_TO_MICROSTEPS = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1}
MICROSTEPS_TO_MRES = {v: k for k, v in MRES_TO_MICROSTEPS.items()}

TMC_QUERYABLE_FIELDS = [
    "gconf",
    "gstat",
    "ifcnt",
    "ioin",
    "factory_conf",
    "ihold_irun_configured",
    "tstep",
    "sg_result",
    "mscnt",
    "mscuract",
    "chopconf",
    "coolconf",
    "pwm_conf",
    "pwm_scale",
    "pwm_auto",
    "drv_status",
]


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
        "t120": bool(raw & (1 << 8)),
        "t143": bool(raw & (1 << 7)),
        "t150": bool(raw & (1 << 6)),
        "t157": bool(raw & (1 << 11)),
    }


# Cache for last-written IRUN/IHOLD since TMC2209 IHOLD_IRUN register is write-only via UART
_stepper_current_cache: Dict[str, Dict[str, int]] = {}


def _current_payload_from_persisted_config(name: str) -> Dict[str, int]:
    result = {
        "irun": DEFAULT_STEPPER_IRUN,
        "ihold": DEFAULT_STEPPER_IHOLD,
        "ihold_delay": DEFAULT_STEPPER_IHOLD_DELAY,
    }
    try:
        _, config = _read_machine_params_config()
    except Exception:
        return result

    toml_name = _STEPPER_API_TO_TOML_NAME.get(name, name)
    overrides = config.get("stepper_current_overrides", {})
    entry = overrides.get(toml_name, {}) if isinstance(overrides, dict) else {}
    if not isinstance(entry, dict):
        return result

    for key, upper_bound in (("irun", 31), ("ihold", 31), ("ihold_delay", 15)):
        value = entry.get(key)
        if isinstance(value, int) and 0 <= value <= upper_bound:
            result[key] = value
    return result


def _current_payload_from_stepper(stepper: Any) -> Dict[str, int] | None:
    payload = getattr(stepper, "last_set_current", None)
    if not isinstance(payload, dict):
        return None

    irun = payload.get("irun")
    ihold = payload.get("ihold")
    ihold_delay = payload.get("ihold_delay")
    if not isinstance(irun, int) or not isinstance(ihold, int) or not isinstance(ihold_delay, int):
        return None
    if not (0 <= irun <= 31 and 0 <= ihold <= 31 and 0 <= ihold_delay <= 15):
        return None

    return {
        "irun": irun,
        "ihold": ihold,
        "ihold_delay": ihold_delay,
    }


def _desired_stepper_current_payload(name: str, stepper: Any) -> Dict[str, int]:
    cached = _stepper_current_cache.get(name)
    if isinstance(cached, dict):
        irun = cached.get("irun")
        ihold = cached.get("ihold")
        ihold_delay = cached.get("ihold_delay", DEFAULT_STEPPER_IHOLD_DELAY)
        if (
            isinstance(irun, int)
            and isinstance(ihold, int)
            and isinstance(ihold_delay, int)
            and 0 <= irun <= 31
            and 0 <= ihold <= 31
            and 0 <= ihold_delay <= 15
        ):
            return {
                "irun": irun,
                "ihold": ihold,
                "ihold_delay": ihold_delay,
            }

    stepper_payload = _current_payload_from_stepper(stepper)
    if stepper_payload is not None:
        _stepper_current_cache[name] = dict(stepper_payload)
        return stepper_payload

    persisted = _current_payload_from_persisted_config(name)
    _stepper_current_cache[name] = dict(persisted)
    return persisted


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


def _stepper_diag_capabilities(stepper: Any) -> Dict[str, Any]:
    interface = getattr(stepper, "_dev", None)
    observability = {}
    if interface is not None and hasattr(interface, "get_observability_info"):
        try:
            observability = interface.get_observability_info()
        except Exception:
            observability = {}
    diag_pins = observability.get("diag_pins")
    channel = getattr(stepper, "channel", None)
    diag_pin: int | None = None

    if isinstance(diag_pins, list) and isinstance(channel, int) and 0 <= channel < len(diag_pins):
        raw_pin = diag_pins[channel]
        if isinstance(raw_pin, int) and raw_pin >= 0:
            diag_pin = raw_pin

    return {
        "diag_expected": diag_pin is not None,
        "diag_pin": diag_pin,
        "diag_verified": False,
        "diag_status": "unverified" if diag_pin is not None else "not_declared",
    }


def _tmc_register_snapshot(stepper: Any) -> Dict[str, int | None]:
    return {
        "gconf": _safe_read_register(stepper, TMC_REG_GCONF),
        "gstat": _safe_read_register(stepper, TMC_REG_GSTAT),
        "ifcnt": _safe_read_register(stepper, TMC_REG_IFCNT),
        "ioin": _safe_read_register(stepper, TMC_REG_IOIN),
        "factory_conf": _safe_read_register(stepper, TMC_REG_FACTORY_CONF),
        "tstep": _safe_read_register(stepper, TMC_REG_TSTEP),
        # This is the dedicated SG_RESULT register (0x41), read directly.
        "sg_result": _safe_read_register(stepper, TMC_REG_SG_RESULT),
        "mscnt": _safe_read_register(stepper, TMC_REG_MSCNT),
        "mscuract": _safe_read_register(stepper, TMC_REG_MSCURACT),
        "chopconf": _safe_read_register(stepper, TMC_REG_CHOPCONF),
        "coolconf": _safe_read_register(stepper, TMC_REG_COOLCONF),
        "drv_status": _safe_read_register(stepper, TMC_REG_DRV_STATUS),
        "pwm_conf": _safe_read_register(stepper, TMC_REG_PWM_CONF),
        "pwm_scale": _safe_read_register(stepper, TMC_REG_PWM_SCALE),
        "pwm_auto": _safe_read_register(stepper, TMC_REG_PWM_AUTO),
    }


_STEPPER_API_TO_TOML_NAME: Dict[str, str] = {
    "c_channel_1": "c_channel_1_rotor",
    "c_channel_2": "c_channel_2_rotor",
    "c_channel_3": "c_channel_3_rotor",
    "c_channel_4": "carousel",
    "carousel": "carousel",
    "chute": "chute_stepper",
}


from server.config_helpers import (
    read_machine_params_config as _read_machine_params_config,
    write_machine_params_config as _write_machine_params_config,
)


def _persist_stepper_current(api_name: str, irun: int, ihold: int) -> None:
    toml_name = _STEPPER_API_TO_TOML_NAME.get(api_name, api_name)
    try:
        params_path, config = _read_machine_params_config()
        overrides = config.get("stepper_current_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        entry = overrides.get(toml_name, {})
        if not isinstance(entry, dict):
            entry = {}
        entry["irun"] = irun
        entry["ihold"] = ihold
        overrides[toml_name] = entry
        config["stepper_current_overrides"] = overrides
        _write_machine_params_config(params_path, config)
    except Exception:
        pass  # best-effort persistence


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/state", response_model=StateResponse)
def getState() -> StateResponse:
    layout = _getCameraLayout()
    if shared_state.controller_ref is None:
        return StateResponse(state=SorterLifecycle.INITIALIZING.value, camera_layout=layout)
    return StateResponse(state=shared_state.controller_ref.state.value, camera_layout=layout)


@router.post("/pause", response_model=CommandResponse)
def pause() -> CommandResponse:
    if shared_state.command_queue is None:
        raise HTTPException(status_code=500, detail="Command queue not initialized")
    event = PauseCommandEvent(tag="pause", data=PauseCommandData())
    shared_state.command_queue.put(event)
    return CommandResponse(success=True)


@router.post("/resume", response_model=CommandResponse)
def resume() -> CommandResponse:
    _ensure_runtime_ready("resume the sorter")
    _ensure_no_blocking_fault("resume the sorter")
    if shared_state.command_queue is None:
        raise HTTPException(status_code=500, detail="Command queue not initialized")
    event = ResumeCommandEvent(tag="resume", data=ResumeCommandData())
    shared_state.command_queue.put(event)
    return CommandResponse(success=True)


@router.post("/stepper/pulse", response_model=StepperPulseResponse)
def pulse_stepper(
    stepper: str,
    direction: str,
    duration_s: float = 0.25,
    speed: int = 800,
) -> StepperPulseResponse:
    _ensure_manual_motion_allowed("pulse a stepper")
    if duration_s <= 0 or duration_s > MAX_STEPPER_PULSE_DURATION_S:
        raise HTTPException(
            status_code=400,
            detail=f"duration_s must be in (0, {int(MAX_STEPPER_PULSE_DURATION_S)}]",
        )
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")
    if direction not in ("cw", "ccw"):
        raise HTTPException(status_code=400, detail="direction must be 'cw' or 'ccw'")

    target = _resolve_stepper(stepper)

    lock = shared_state.pulse_locks.setdefault(stepper, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is already pulsing")

    signed_speed = speed if direction == "cw" else -speed

    try:
        target.enable_force(True)
        if not bool(target.move_at_speed(signed_speed, force=True)):
            raise RuntimeError("move_at_speed was not acknowledged")
    except Exception as e:
        lock.release()
        raise HTTPException(status_code=500, detail=f"Pulse start failed: {e}")

    threading.Thread(
        target=_stop_stepper_after_delay,
        args=(target, duration_s, lock),
        kwargs={"force": True},
        daemon=True,
    ).start()

    return StepperPulseResponse(
        success=True,
        stepper=stepper,
        direction=direction,
        duration_s=duration_s,
        speed=speed,
    )


class _JitterBusy(Exception):
    """Raised when the firmware refuses a jitter because one is still in flight."""


def _estimate_jitter_duration_s(amplitude_steps: int, cycles: int, speed: int, acceleration: int) -> float:
    """Estimate how long a jitter run will take so the pulse lock can be held.

    Each stroke is a trapezoidal (or triangular, for short strokes) accel/brake
    move of `amplitude_steps` microsteps. Duration drives only lock release, so
    a generous over-estimate is fine.
    """
    accel = max(acceleration, 1)
    accel_distance = (speed * speed) / (2.0 * accel)  # microsteps to reach `speed`
    if 2.0 * accel_distance >= amplitude_steps:
        stroke_s = 2.0 * math.sqrt(amplitude_steps / accel)  # triangular: never reaches `speed`
    else:
        cruise_steps = amplitude_steps - 2.0 * accel_distance
        stroke_s = 2.0 * (speed / accel) + cruise_steps / speed
    strokes = cycles * 2
    return strokes * stroke_s + strokes * 0.001  # +1ms per inter-stroke gap


@router.post("/stepper/jitter", response_model=StepperJitterResponse)
def jitter_stepper(
    stepper: str,
    amplitude_deg: float = 2.0,
    cycles: int = 20,
    speed: int = 4000,
    acceleration: int = 60000,
) -> StepperJitterResponse:
    """Run a short, sharp back-and-forth oscillation to break static friction.

    `amplitude_deg` is the per-stroke amplitude in motor-shaft degrees (before
    any output gear reduction). The motion is symmetric and returns to start.
    """
    _ensure_manual_motion_allowed("jitter a stepper")
    if cycles <= 0 or cycles > 5000:
        raise HTTPException(status_code=400, detail="cycles must be in (0, 5000]")
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")
    if acceleration <= 0:
        raise HTTPException(status_code=400, detail="acceleration must be > 0")

    target = _resolve_stepper(stepper)
    amplitude_steps = target.microsteps_for_degrees(abs(amplitude_deg))
    if amplitude_steps <= 0:
        raise HTTPException(status_code=400, detail="amplitude_deg too small (rounds to zero microsteps)")

    lock = shared_state.pulse_locks.setdefault(stepper, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is already moving")

    # A jitter always runs to completion on the firmware's real-time core and
    # cannot be interrupted mid-run; the firmware refuses an overlapping jitter.
    # Confirm the previous run has truly finished before accepting a new one —
    # `stopped` is unreliable here because it flickers between strokes.
    try:
        if hasattr(target, "is_jittering") and bool(target.is_jittering()):
            lock.release()
            raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is still jittering")
    except HTTPException:
        raise
    except Exception:
        pass

    try:
        target.enable_force(True)
        if not bool(target.jitter(amplitude_steps, cycles, speed, acceleration, force=True)):
            # Firmware rejected it — almost always because a prior jitter is
            # still finishing. Treat as "busy" rather than a hard failure.
            raise _JitterBusy()
    except _JitterBusy:
        lock.release()
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is still jittering")
    except Exception as e:
        lock.release()
        raise HTTPException(status_code=500, detail=f"Jitter start failed: {e}")

    duration_s = _estimate_jitter_duration_s(amplitude_steps, cycles, speed, acceleration)

    # Let the jitter finish on its own, then de-energize the driver. We never
    # send a stop/move that would tear down the run; we only poll completion and
    # cut current afterward. A generous time cap bounds the poll if the firmware
    # never reports done (e.g. driver pulled), so the lock is always released.
    def _release_after_jitter() -> None:
        deadline = time.monotonic() + duration_s * 2 + 5.0
        try:
            while time.monotonic() < deadline:
                time.sleep(0.2)
                try:
                    if not (hasattr(target, "is_jittering") and bool(target.is_jittering())):
                        break
                except Exception:
                    break
            try:
                target.enable_force(False)
            except Exception:
                pass
        finally:
            try:
                lock.release()
            except RuntimeError:
                pass

    threading.Thread(target=_release_after_jitter, daemon=True).start()

    return StepperJitterResponse(
        success=True,
        stepper=stepper,
        amplitude_deg=amplitude_deg,
        amplitude_microsteps=amplitude_steps,
        cycles=cycles,
        speed=speed,
        acceleration=acceleration,
        estimated_duration_s=round(duration_s, 3),
    )


@router.post("/stepper/move-degrees", response_model=StepperMoveDegreesResponse)
def move_stepper_degrees(
    stepper: str,
    degrees: float,
    speed: int = 800,
    min_speed: int | None = None,
    acceleration: int | None = None,
) -> StepperMoveDegreesResponse:
    _ensure_manual_motion_allowed("move a stepper")
    """Blocking-style move to a relative position.

    When ``min_speed`` and ``acceleration`` are both supplied, the firmware
    ramps from ``min_speed`` up to ``speed`` (and back down) using the
    supplied acceleration (µsteps/s²). Leave them unset for a hard-stop
    constant-velocity move.
    """
    if degrees == 0:
        raise HTTPException(status_code=400, detail="degrees must be non-zero")
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")
    if min_speed is not None and min_speed <= 0:
        raise HTTPException(status_code=400, detail="min_speed must be > 0 when supplied")
    if min_speed is not None and min_speed > speed:
        raise HTTPException(status_code=400, detail="min_speed must be <= speed")
    if acceleration is not None and acceleration <= 0:
        raise HTTPException(status_code=400, detail="acceleration must be > 0 when supplied")
    want_ramp = min_speed is not None and acceleration is not None
    if (min_speed is None) ^ (acceleration is None):
        raise HTTPException(
            status_code=400,
            detail="min_speed and acceleration must be supplied together for ramped motion",
        )

    target = _resolve_stepper(stepper)

    lock = shared_state.pulse_locks.setdefault(stepper, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is already moving")

    try:
        target.enable_force(True)
        if want_ramp:
            target.set_speed_limits(min_speed=int(min_speed), max_speed=int(speed))
            move_acceleration: int | None = int(acceleration)
        else:
            target.set_speed_limits(min_speed=16, max_speed=int(speed))
            move_acceleration = None
        if not bool(target.move_degrees(degrees, acceleration=move_acceleration, force=True)):
            raise RuntimeError("move_degrees was not acknowledged")
    except Exception as e:
        lock.release()
        raise HTTPException(status_code=500, detail=f"Move failed: {e}")

    def _release_after_move():
        try:
            start = time.monotonic()
            timed_out = False
            while True:
                try:
                    if target.stopped_force():
                        break
                except Exception:
                    _halt_stepper(target)
                    break
                if (time.monotonic() - start) >= 30:
                    timed_out = True
                    break
                time.sleep(0.02)
            if timed_out:
                _halt_stepper(target)
        finally:
            lock.release()

    threading.Thread(target=_release_after_move, daemon=True).start()

    return StepperMoveDegreesResponse(
        success=True,
        stepper=stepper,
        degrees=degrees,
        speed=speed,
    )


@router.post(
    "/api/classification-channel/sector-move",
    response_model=C4SectorMoveResponse,
)
def classification_channel_sector_move(
    from_sector: int,
    to_sector: int,
    direction: str = "shortest",
    execute: bool = False,
) -> C4SectorMoveResponse:
    """Plan or execute one discrete C4 sector move on the C-channel axis."""
    if execute:
        _ensure_manual_motion_allowed("move the classification channel")
    if direction not in ("shortest", "cw", "ccw"):
        raise HTTPException(status_code=400, detail="direction must be one of: shortest, cw, ccw")

    from subsystems.classification_channel.five_sector_platter import C4FiveSectorPlatter

    platter = C4FiveSectorPlatter.from_irl_config(_active_irl_config())
    try:
        plan = platter.sector_move_plan(
            from_sector,
            to_sector,
            direction=direction,  # type: ignore[arg-type]
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if execute:
        target = _resolve_stepper("c_channel_4")
        lock = shared_state.pulse_locks.setdefault("c_channel_4", threading.Lock())
        if not lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Stepper 'c_channel_4' is already moving")
        try:
            target.enabled = True
            accepted = plan.apply_to_stepper(target)
            if not accepted:
                raise HTTPException(status_code=500, detail="C4 sector move was rejected by the stepper")
        except HTTPException:
            lock.release()
            raise
        except Exception as exc:
            lock.release()
            raise HTTPException(status_code=500, detail=f"C4 sector move failed: {exc}") from exc

        def _release_after_move() -> None:
            try:
                start = time.monotonic()
                while not target.stopped and (time.monotonic() - start) < 30:
                    time.sleep(0.02)
            finally:
                lock.release()

        threading.Thread(target=_release_after_move, daemon=True).start()

    return C4SectorMoveResponse(
        success=True,
        executed=bool(execute),
        stepper="c_channel_4",
        from_sector=plan.from_sector,
        to_sector=plan.to_sector,
        sector_delta=plan.sector_delta,
        output_delta_deg=plan.output_delta_deg,
        motor_delta_deg=plan.motor_delta_deg,
        motor_microsteps=plan.motor_microsteps,
        direction=plan.direction,
        gear_ratio=platter.gear_ratio,
        microsteps=platter.microsteps,
        motor_steps_per_revolution=platter.motor_steps_per_revolution,
        min_speed_microsteps_per_second=(
            plan.motion_profile.min_speed_microsteps_per_second
        ),
        max_speed_microsteps_per_second=(
            plan.motion_profile.max_speed_microsteps_per_second
        ),
        acceleration_microsteps_per_second_sq=(
            plan.motion_profile.acceleration_microsteps_per_second_sq
        ),
        requested_max_speed_microsteps_per_second=(
            plan.motion_profile.requested_max_speed_microsteps_per_second
        ),
        requested_acceleration_microsteps_per_second_sq=(
            plan.motion_profile.requested_acceleration_microsteps_per_second_sq
        ),
        configured_stepper_default_speed_microsteps_per_second=(
            plan.motion_profile.configured_stepper_default_speed_microsteps_per_second
        ),
        warnings=list(plan.motion_profile.warnings),
    )


@router.post("/stepper/stop", response_model=StepperStopResponse)
def stop_stepper(stepper: str) -> StepperStopResponse:
    target = _resolve_stepper(stepper)

    try:
        _halt_stepper(target, force=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stop failed: {e}")

    return StepperStopResponse(success=True, stepper=stepper)


@router.post("/stepper/stop-all", response_model=StepperStopAllResponse)
def stop_all_steppers() -> StepperStopAllResponse:
    halted: list[str] = []
    errors: Dict[str, str] = {}

    for name, stepper in _stepper_mapping().items():
        if stepper is None:
            continue
        try:
            _halt_stepper(stepper, force=True)
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


@router.get("/api/stepper/{name}/tmc")
def get_tmc_settings(name: str) -> Dict[str, Any]:
    if name not in _STEPPER_API_TO_TOML_NAME:
        raise HTTPException(status_code=400, detail=f"Unknown stepper '{name}'")

    # Configured values (currents, StallGuard) live in machine.toml and don't need
    # live hardware to read — so serve them even at standby, when there's no IRL
    # yet. Only the register read-outs (microsteps, chopper mode, DRV_STATUS,
    # SG_RESULT) require a live driver; those come back null until hardware is up.
    try:
        stepper = _resolve_stepper(name)
    except HTTPException:
        stepper = None

    if stepper is None:
        persisted_current = _current_payload_from_persisted_config(name)
        return {
            "hardware_ready": False,
            "irun": persisted_current["irun"],
            "ihold": persisted_current["ihold"],
            "ihold_delay": persisted_current["ihold_delay"],
            "stallguard": _stallguard_payload_from_persisted_config(name),
            "capabilities": {
                "tmc_uart_available": False,
                "queryable_fields": list(TMC_QUERYABLE_FIELDS),
            },
            "registers": None,
            "microsteps": None,
            "stealthchop": None,
            "coolstep": None,
            "drv_status": None,
            "sg_result": None,
        }

    registers = _tmc_register_snapshot(stepper)
    gconf_raw = registers["gconf"]
    chopconf_raw = registers["chopconf"]
    coolconf_raw = registers["coolconf"]
    drv_status_raw = registers["drv_status"]

    result: Dict[str, Any] = {"hardware_ready": True}
    current_payload = _desired_stepper_current_payload(name, stepper)
    result["irun"] = current_payload["irun"]
    result["ihold"] = current_payload["ihold"]
    result["ihold_delay"] = current_payload["ihold_delay"]
    result["capabilities"] = {
        **_stepper_diag_capabilities(stepper),
        "tmc_uart_available": True,
        "queryable_fields": list(TMC_QUERYABLE_FIELDS),
    }
    result["registers"] = registers

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
        # DRV_STATUS also contains its own SG_RESULT bitfield view. Keep both:
        # `registers.sg_result` is the raw 0x41 register, while
        # `drv_status.sg_result` is the SG_RESULT field decoded from 0x6F.
        result["drv_status"] = _parse_drv_status(drv_status_raw)
    else:
        result["drv_status"] = None

    if registers["sg_result"] is not None:
        # Surface the direct 0x41 register value at top level for convenience.
        result["sg_result"] = registers["sg_result"]
    else:
        result["sg_result"] = None

    # Persisted StallGuard stall-detection config (or defaults) so the driver
    # settings UI can show/edit it alongside the other TMC settings.
    result["stallguard"] = _stallguard_payload_from_persisted_config(name)

    # Live stall latch (mirrored by the stall monitor) so a station's page can show
    # "this motor is stalled" and offer to clear it.
    result["stalled"] = bool(getattr(stepper, "stalled", False))

    return result


@router.post("/api/stepper/{name}/tmc")
def set_tmc_settings(name: str, body: TmcSettingsRequest) -> Dict[str, Any]:
    stepper = _resolve_stepper(name)

    if body.irun is not None or body.ihold is not None:
        current = _desired_stepper_current_payload(name, stepper)
        irun = body.irun if body.irun is not None else current["irun"]
        ihold = body.ihold if body.ihold is not None else current["ihold"]
        if not (0 <= irun <= 31):
            raise HTTPException(status_code=400, detail="irun must be 0-31")
        if not (0 <= ihold <= 31):
            raise HTTPException(status_code=400, detail="ihold must be 0-31")
        stepper.set_current(irun, ihold, current["ihold_delay"])
        _stepper_current_cache[name] = {
            "irun": irun,
            "ihold": ihold,
            "ihold_delay": current["ihold_delay"],
        }
        _persist_stepper_current(name, irun, ihold)

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


# ---------------------------------------------------------------------------
# StallGuard tuning — data collection sweep + threshold persistence
# ---------------------------------------------------------------------------

# A sweep is a pure measurement: it runs the motor at constant speed, polls
# SG_RESULT (load proxy, 0-510; drops toward 0 as load rises) plus CS_ACTUAL and
# TSTEP, then stops. It never writes SGTHRS and restores TCOOLTHRS=0 on exit, so
# it cannot leave stall enforcement half-configured. StallGuard only reports
# while running above the TCOOLTHRS velocity floor, so we raise TCOOLTHRS for the
# duration to keep SG_RESULT live across the operating range.
DEFAULT_STALLGUARD_TCOOLTHRS = 0xFFFFF


class StallGuardSample(BaseModel):
    t: float
    sg_result: int
    cs_actual: int
    tstep: int


class StallGuardSweepStats(BaseModel):
    samples: int
    sg_min: int
    sg_max: int
    sg_mean: float
    suggested_sgthrs: int
    suggested_trigger_level: int


class StallGuardSweepResponse(BaseModel):
    success: bool
    stepper: str
    speed: int
    duration_s: float
    sample_interval_s: float
    tcoolthrs: int
    run_id: str
    samples: List[StallGuardSample]
    stats: Optional[StallGuardSweepStats]


def _suggested_sgthrs(sg_min: int) -> int:
    # Heuristic validated on the stall-01 bring-up: place the trigger well below
    # the unloaded minimum so normal running never trips, but high enough that a
    # real stall (SG_RESULT -> ~0) does. DIAG fires at SG_RESULT <= 2*SGTHRS.
    return max(1, int(sg_min * 0.4) // 2)


# ---------------------------------------------------------------------------
# Sweep motion profiles
#
# A constant-speed spin is a poor stand-in for how a motor is actually loaded in
# service: the chute aims to angles and reverses (a constant spin just rams its
# endstop and reads SG_RESULT=0), and the rotors/carousel run in discrete pulses
# with dwells and the odd unstick jitter — not a steady cruise. These profiles
# reproduce that so the recorded SG_RESULT reflects real operating load.
#
# Each profile models its own timeline from estimated move durations and exposes
# moving(now): the sampler only records load-bearing motion phases and ignores
# idle dwells, so dwell zeros don't pollute the threshold. No extra UART status
# reads — the sample loop is already bus-bound.
# ---------------------------------------------------------------------------

SWEEP_PROFILES = ("constant", "chute_random", "pulsed")

# Defaults for the unstick jitter folded into the pulsed profile, matching the
# feeder's real fall-recovery values (go_to_angle config).
_PULSED_JITTER_AMPLITUDE_DEG = 6.0
_PULSED_JITTER_CYCLES = 8
_PULSED_JITTER_SPEED = 6500
_PULSED_JITTER_ACCEL = 180000


class _SweepMotion:
    def start(self, now: float) -> None: ...
    def tick(self, now: float) -> None: ...
    def moving(self, now: float) -> bool:
        return True


class _ConstantMotion(_SweepMotion):
    def __init__(self, target: Any, signed_speed: int) -> None:
        self._target = target
        self._signed_speed = signed_speed

    def start(self, now: float) -> None:
        if not bool(self._target.move_at_speed(self._signed_speed, force=True)):
            raise RuntimeError("move_at_speed was not acknowledged")


# The chute hits HARD STOPS at 0 and 360 deg of output travel (it can cross
# neither). Stay well inside that with the same cap the stress test uses.
CHUTE_SAFE_MAX_DEG = 345.0


class _ChuteRandomMotion(_SweepMotion):
    """Random go-to-angle with immediate turnaround on the real chute, like the
    chute stress test. Operates on the homed Chute object in ABSOLUTE output
    degrees clamped to [min_deg, max_deg] within [0, CHUTE_SAFE_MAX_DEG], so it
    can never reach an endstop. Homes first if the chute lacks a reference —
    without that, "0 deg" is wherever it powered on and the clamp is meaningless.
    Targets are at least min_delta_deg apart so every move is a real excursion."""

    def __init__(self, chute: Any, speed: int, min_delta_deg: float, min_deg: float, max_deg: float) -> None:
        self._chute = chute
        self._speed = speed
        self._min_delta = max(1.0, min_delta_deg)
        self._min = max(0.0, min(min_deg, CHUTE_SAFE_MAX_DEG))
        self._max = max(self._min, min(max_deg, CHUTE_SAFE_MAX_DEG))
        # Don't re-check stopped for a beat after issuing a move, so we don't read
        # a stale "stopped" before the firmware has started the move.
        self._next_check_at = 0.0

    def _home_if_needed(self) -> None:
        if bool(getattr(self._chute, "homed", False)):
            return
        from subsystems.distribution.chute import HOME_SPEED_MICROSTEPS_PER_SEC, HOME_TIMEOUT_MS

        st = self._chute.stepper
        st.enabled = True
        st.home(
            HOME_SPEED_MICROSTEPS_PER_SEC,
            self._chute.home_pin,
            home_pin_active_high=self._chute.endstop_active_high,
        )
        deadline = time.monotonic() + HOME_TIMEOUT_MS / 1000.0 + 5.0
        while time.monotonic() < deadline:
            try:
                if st.stopped:
                    break
            except Exception:
                break
            time.sleep(0.02)

    def _pick(self, current: float) -> float:
        for _ in range(20):
            cand = random.uniform(self._min, self._max)
            if abs(cand - current) >= self._min_delta:
                return cand
        mid = (self._min + self._max) / 2.0
        return self._max if current < mid else self._min

    def _go(self, now: float) -> None:
        current = float(self._chute.current_angle)
        target_deg = self._pick(current)
        self._chute.moveToAngle(target_deg)  # absolute, clamps to [0,360]
        self._next_check_at = now + 0.05

    def start(self, now: float) -> None:
        self._chute.stepper.set_speed_limits(0, self._speed)
        self._home_if_needed()
        self._go(now)

    def tick(self, now: float) -> None:
        # Issue the next target only once the previous move has actually finished.
        # Re-issuing on a guessed timer floods the chute with overlapping reversals
        # it can't follow (it stalls in place); waiting for a real stop gives clean
        # go-to-angle moves. Immediate turnaround on stop = the quick reversal.
        if now < self._next_check_at:
            return
        try:
            if self._chute.stepper.stopped:
                self._go(now)
        except Exception:
            pass


class _PulsedMotion(_SweepMotion):
    """Discrete forward pulses with a dwell between (how the rotors and carousel
    actually run), with an unstick jitter folded in every jitter_every pulses.
    moving() is true only during the move/jitter phase, not the dwell."""

    def __init__(
        self,
        target: Any,
        speed: int,
        pulse_deg: float,
        dwell_ms: float,
        jitter_every: int,
        sign: int,
    ) -> None:
        self._target = target
        self._speed = speed
        self._pulse_deg = abs(pulse_deg) * (1 if sign >= 0 else -1)
        self._dwell = max(0.0, dwell_ms) / 1000.0
        self._jitter_every = max(0, jitter_every)
        self._count = 0
        self._phase_end = 0.0
        self._dwell_end = 0.0

    def _next(self, now: float) -> None:
        self._count += 1
        if self._jitter_every and self._count % self._jitter_every == 0:
            self._target.jitter_degrees(
                _PULSED_JITTER_AMPLITUDE_DEG,
                _PULSED_JITTER_CYCLES,
                _PULSED_JITTER_SPEED,
                _PULSED_JITTER_ACCEL,
                force=True,
            )
            # Rough upper bound on jitter duration; only gates sampling, not motion.
            dur_ms = max(200, _PULSED_JITTER_CYCLES * 60)
        else:
            self._target.set_speed_limits(0, self._speed)
            self._target.move_degrees(self._pulse_deg, force=True)
            dur_ms = self._target.estimateMoveDegreesMs(abs(self._pulse_deg), max_speed=self._speed)
        self._phase_end = now + max(dur_ms, 1) / 1000.0
        self._dwell_end = self._phase_end + self._dwell

    def start(self, now: float) -> None:
        self._next(now)

    def tick(self, now: float) -> None:
        if now >= self._dwell_end:
            self._next(now)

    def moving(self, now: float) -> bool:
        return now < self._phase_end


@router.post("/stepper/stallguard-sweep", response_model=StallGuardSweepResponse)
def stallguard_sweep(
    stepper: str,
    speed: int,
    direction: str = "cw",
    duration_s: float = 4.0,
    sample_interval_s: float = 0.02,
    spin_up_s: float = 0.3,
    tcoolthrs: int = DEFAULT_STALLGUARD_TCOOLTHRS,
    cruise_tstep: int = 150,
    loaded: bool = False,
    label: Optional[str] = None,
    profile: str = "constant",
    chute_min_deg: float = 10.0,
    chute_max_deg: float = 340.0,
    min_delta_deg: float = 30.0,
    pulse_deg: float = 30.0,
    dwell_ms: float = 250.0,
    jitter_every: int = 5,
) -> StallGuardSweepResponse:
    _ensure_manual_motion_allowed("run a StallGuard sweep")
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")
    if direction not in ("cw", "ccw"):
        raise HTTPException(status_code=400, detail="direction must be 'cw' or 'ccw'")
    if profile not in SWEEP_PROFILES:
        raise HTTPException(
            status_code=400, detail=f"profile must be one of {', '.join(SWEEP_PROFILES)}"
        )
    if cruise_tstep <= 0:
        raise HTTPException(status_code=400, detail="cruise_tstep must be > 0")
    if duration_s <= 0:
        raise HTTPException(status_code=400, detail="duration_s must be > 0")
    if sample_interval_s <= 0:
        raise HTTPException(status_code=400, detail="sample_interval_s must be > 0")

    target = _resolve_stepper(stepper)

    lock = shared_state.pulse_locks.setdefault(stepper, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is busy")

    signed_speed = speed if direction == "cw" else -speed
    sign = 1 if direction == "cw" else -1
    samples: List[StallGuardSample] = []
    telemetry_rows: List[Dict[str, Any]] = []

    chute_restore_speed: Optional[int] = None
    if profile == "chute_random":
        # The chute has hard endstops, so its motion must run on the homed Chute
        # object (absolute, clamped angles) — never a raw open-loop spin.
        irl = shared_state.getActiveIRL()
        chute = getattr(irl, "chute", None) if irl is not None else None
        if chute is None:
            lock.release()
            raise HTTPException(
                status_code=409,
                detail="chute_random needs the initialized chute; initialize hardware first.",
            )
        chute_restore_speed = int(getattr(chute, "operating_speed_microsteps_per_second", speed))
        motion: _SweepMotion = _ChuteRandomMotion(
            chute, speed, min_delta_deg, chute_min_deg, chute_max_deg
        )
    elif profile == "pulsed":
        motion = _PulsedMotion(target, speed, pulse_deg, dwell_ms, jitter_every, sign)
    else:
        motion = _ConstantMotion(target, signed_speed)

    # Static per-run context, captured once (these don't change mid-sweep).
    channel_ctx = getattr(target, "channel", None)
    microsteps_ctx = getattr(target, "_microsteps", None)
    last_current = getattr(target, "last_set_current", None)
    irun_ctx = last_current.get("irun") if isinstance(last_current, dict) else None
    # Acceleration the sweep runs at: move_at_speed re-asserts the stepper's
    # configured default acceleration, so that's the value in effect per sample.
    accel_ctx = getattr(target, "default_acceleration", None)
    gconf = _safe_read_register(target, TMC_REG_GCONF)
    stealth_ctx = (not bool(gconf & (1 << 2))) if isinstance(gconf, int) else None

    source = stepper_telemetry.SOURCE_STALL_TEST if loaded else stepper_telemetry.SOURCE_SWEEP
    run_id = stepper_telemetry.createRun(
        source,
        stepper_name=stepper,
        label=label,
        params={
            "speed": signed_speed,
            "direction": direction,
            "duration_s": duration_s,
            "sample_interval_s": sample_interval_s,
            "tcoolthrs": tcoolthrs,
            "cruise_tstep": cruise_tstep,
            "loaded": loaded,
            "irun": irun_ctx,
            "acceleration": accel_ctx,
            "microsteps": microsteps_ctx,
            "stealthchop": stealth_ctx,
            "profile": profile,
            "chute_min_deg": chute_min_deg if profile == "chute_random" else None,
            "chute_max_deg": chute_max_deg if profile == "chute_random" else None,
            "min_delta_deg": min_delta_deg if profile == "chute_random" else None,
            "pulse_deg": pulse_deg if profile == "pulsed" else None,
            "dwell_ms": dwell_ms if profile == "pulsed" else None,
            "jitter_every": jitter_every if profile == "pulsed" else None,
        },
    )

    try:
        # The sweep deliberately stalls the motor (loaded test) and opens the
        # velocity floor wide — so turn live stall detection OFF for the duration,
        # or an enabled motor would trip its own incident mid-sweep. This is the
        # ONE place detection is suppressed; it's restored in the finally.
        try:
            target.enable_stall_detection(False)
        except Exception:
            pass
        # Measure with SG reported across the whole speed range; the cruise_tstep
        # filter is applied at analysis time so we still see the transients in the
        # chart but don't let them set the threshold.
        target.write_driver_register(TMC_REG_TCOOLTHRS, tcoolthrs)
        target.enable_force(True)
        motion.start(time.monotonic())

        # A constant spin needs a moment to reach speed before SG_RESULT is valid;
        # the pulsed/chute profiles are sampled per-move via moving(), so skip it.
        if profile == "constant":
            time.sleep(min(max(spin_up_s, 0.0), 2.0))

        wall_start = time.time()
        t_start = time.monotonic()
        while True:
            now = time.monotonic()
            t = now - t_start
            if t >= duration_s:
                break
            motion.tick(now)
            if not motion.moving(now):
                # Idle dwell between pulses — its SG_RESULT isn't load data.
                remaining = sample_interval_s - (time.monotonic() - t_start - t)
                if remaining > 0:
                    time.sleep(remaining)
                continue
            sg = _safe_read_register(target, TMC_REG_SG_RESULT)
            drv = _safe_read_register(target, TMC_REG_DRV_STATUS)
            tstep = _safe_read_register(target, TMC_REG_TSTEP)
            sg_val = sg if isinstance(sg, int) else None
            cs_val = ((drv >> 16) & 0x1F) if isinstance(drv, int) else None
            tstep_val = tstep if isinstance(tstep, int) else None
            samples.append(
                StallGuardSample(
                    t=round(t, 4),
                    sg_result=sg_val if sg_val is not None else -1,
                    cs_actual=cs_val if cs_val is not None else -1,
                    tstep=tstep_val if tstep_val is not None else -1,
                )
            )
            telemetry_rows.append(
                {
                    "recorded_at": wall_start + t,
                    "stepper_name": stepper,
                    "channel": channel_ctx,
                    "sg_result": sg_val,
                    "cs_actual": cs_val,
                    "tstep": tstep_val,
                    "drv_status_raw": drv if isinstance(drv, int) else None,
                    "commanded_speed": signed_speed,
                    "irun": irun_ctx,
                    "acceleration": accel_ctx,
                    "microsteps": microsteps_ctx,
                    "stealthchop": stealth_ctx,
                    "loaded": loaded,
                }
            )
            remaining = sample_interval_s - (time.monotonic() - t_start - t)
            if remaining > 0:
                time.sleep(remaining)
    except Exception as e:
        # Best-effort save of partial data, but never let a DB error mask the
        # underlying motor failure we're about to surface.
        try:
            stepper_telemetry.insertSamples(run_id, telemetry_rows)
            stepper_telemetry.finishRun(
                run_id, status=stepper_telemetry.RUN_STATUS_ERROR, error=str(e)
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"StallGuard sweep failed: {e}")
    finally:
        try:
            _halt_stepper(target, force=True)
        except Exception:
            pass
        # Restore the motor's resting state. If it has live stall detection
        # configured, put its enforcement velocity floor back and re-enable
        # detection (we turned it off above); otherwise just zero the floor so the
        # sweep leaves nothing half-configured.
        try:
            if getattr(target, "stallguard_enabled", False) and target.stallguard_sgthrs is not None:
                target.write_driver_register(TMC_REG_TCOOLTHRS, target.stallguard_tcoolthrs)
                target.clear_stall()
                target.enable_stall_detection(True)
            else:
                target.write_driver_register(TMC_REG_TCOOLTHRS, 0)
        except Exception:
            pass
        # chute_random retunes the chute stepper's speed limits; restore them to
        # the chute's operating speed so normal aiming isn't left at sweep speed.
        if chute_restore_speed is not None:
            try:
                target.set_speed_limits(16, chute_restore_speed)
            except Exception:
                pass
        try:
            lock.release()
        except RuntimeError:
            pass

    valid = [s.sg_result for s in samples if s.sg_result >= 0]
    # Threshold tuning only considers CRUISE samples (TSTEP <= cruise_tstep). At
    # accel/decel/reversal the velocity is low and SG_RESULT dips even unloaded,
    # which would drag the floor down and produce a uselessly low threshold. The
    # chart still shows every sample; only the suggestion is cruise-filtered.
    cruise = [s.sg_result for s in samples if s.sg_result >= 0 and 0 <= s.tstep <= cruise_tstep]
    basis = cruise if cruise else valid
    stats: Optional[StallGuardSweepStats] = None
    sgthrs: Optional[int] = None
    if basis:
        sg_min = min(basis)
        sgthrs = _suggested_sgthrs(sg_min)
        stats = StallGuardSweepStats(
            samples=len(basis),
            sg_min=sg_min,
            sg_max=max(basis),
            sg_mean=round(sum(basis) / len(basis), 1),
            suggested_sgthrs=sgthrs,
            suggested_trigger_level=sgthrs * 2,
        )

    stepper_telemetry.insertSamples(run_id, telemetry_rows)
    stepper_telemetry.finishRun(
        run_id,
        status=stepper_telemetry.RUN_STATUS_COMPLETED,
        sg_min=stats.sg_min if stats else None,
        sg_max=stats.sg_max if stats else None,
        sg_mean=stats.sg_mean if stats else None,
        suggested_sgthrs=sgthrs,
    )

    return StallGuardSweepResponse(
        success=True,
        stepper=stepper,
        speed=speed,
        duration_s=duration_s,
        sample_interval_s=sample_interval_s,
        tcoolthrs=tcoolthrs,
        run_id=run_id,
        samples=samples,
        stats=stats,
    )


class StallGuardConfigBody(BaseModel):
    sgthrs: int = Field(..., ge=0, le=255)
    tcoolthrs: int = Field(DEFAULT_STALLGUARD_TCOOLTHRS, ge=0)
    enabled: bool = True


class StallGuardConfigResponse(BaseModel):
    success: bool
    stepper: str
    toml_name: str
    sgthrs: int
    tcoolthrs: int
    enabled: bool


# Defaults shown in the per-stepper driver settings when a motor has no saved
# StallGuard config yet. Disabled by default; the numbers are just sane starting
# points to tune from on the StallGuard page (cruise velocity floor ~150).
DEFAULT_STALLGUARD_SGTHRS = 50
DEFAULT_STALLGUARD_ENFORCE_TCOOLTHRS = 150


def _stallguard_payload_from_persisted_config(name: str) -> Dict[str, Any]:
    toml_name = _STEPPER_API_TO_TOML_NAME.get(name, name)
    # Seed from the motor's built-in default (chute/carousel have tuned ones), so a
    # fresh machine with no TOML entry still shows its real applied config rather
    # than a generic placeholder. Motors with no built-in default fall back to the
    # generic disabled placeholder.
    builtin = DEFAULT_STEPPER_STALLGUARD.get(toml_name)
    if builtin is not None:
        result: Dict[str, Any] = {"sgthrs": builtin[0], "tcoolthrs": builtin[1], "enabled": builtin[2]}
    else:
        result = {
            "sgthrs": DEFAULT_STALLGUARD_SGTHRS,
            "tcoolthrs": DEFAULT_STALLGUARD_ENFORCE_TCOOLTHRS,
            "enabled": False,
        }
    try:
        _, config = _read_machine_params_config()
    except Exception:
        return result
    section = config.get("stepper_stallguard", {})
    entry = section.get(toml_name, {}) if isinstance(section, dict) else {}
    if isinstance(entry, dict):
        if isinstance(entry.get("sgthrs"), int):
            result["sgthrs"] = entry["sgthrs"]
        if isinstance(entry.get("tcoolthrs"), int):
            result["tcoolthrs"] = entry["tcoolthrs"]
        if isinstance(entry.get("enabled"), bool):
            result["enabled"] = entry["enabled"]
    return result


def _persist_stepper_stallguard(api_name: str, sgthrs: int, tcoolthrs: int, enabled: bool) -> None:
    toml_name = _STEPPER_API_TO_TOML_NAME.get(api_name, api_name)
    params_path, config = _read_machine_params_config()
    section = config.get("stepper_stallguard", {})
    if not isinstance(section, dict):
        section = {}
    entry = section.get(toml_name, {})
    if not isinstance(entry, dict):
        entry = {}
    entry["sgthrs"] = sgthrs
    entry["tcoolthrs"] = tcoolthrs
    entry["enabled"] = enabled
    section[toml_name] = entry
    config["stepper_stallguard"] = section
    _write_machine_params_config(params_path, config)


@router.post("/stepper/{stepper}/stallguard-config", response_model=StallGuardConfigResponse)
def set_stallguard_config(stepper: str, body: StallGuardConfigBody) -> StallGuardConfigResponse:
    target = _resolve_stepper(stepper)
    toml_name = _STEPPER_API_TO_TOML_NAME.get(stepper, stepper)
    _persist_stepper_stallguard(stepper, body.sgthrs, body.tcoolthrs, body.enabled)

    # Apply live so the change takes effect on the very next move — no reinit
    # needed. Stamp the attrs the stall monitor reads, write the driver registers,
    # and turn detection on/off. When disabled, drop the velocity floor to 0 so
    # DIAG can never fire. Best-effort: a UART hiccup here still leaves the config
    # persisted, and hardware init will re-apply it.
    try:
        target.stallguard_sgthrs = body.sgthrs
        target.stallguard_tcoolthrs = body.tcoolthrs
        target.stallguard_enabled = body.enabled
        target.write_driver_register(TMC_REG_SGTHRS, body.sgthrs)
        target.write_driver_register(TMC_REG_TCOOLTHRS, body.tcoolthrs if body.enabled else 0)
        target.clear_stall()
        target.enable_stall_detection(bool(body.enabled))
    except Exception:
        pass

    return StallGuardConfigResponse(
        success=True,
        stepper=stepper,
        toml_name=toml_name,
        sgthrs=body.sgthrs,
        tcoolthrs=body.tcoolthrs,
        enabled=body.enabled,
    )


# ---------------------------------------------------------------------------
# Threshold suggestion — pair-based, from the measured unloaded/loaded gap
#
# A single run can't set an accurate SGTHRS: an unloaded run only shows the floor
# (the ceiling the trigger must stay under) and a loaded run only shows the stall
# dip (the level the trigger must clear). The accurate trigger sits in the gap
# between the two, so we take cruise samples from the LATEST run of BOTH kinds for
# the motor and place the trigger at the geometric midpoint — equal ratio margin
# above the stall dip and below the normal floor. SGTHRS = trigger / 2 because
# DIAG fires at SG_RESULT <= 2*SGTHRS.
#
# Deliberately the *latest* run of each kind, not a pool of recent ones: pooling
# sweeps in stale runs at other speeds or from a since-changed driver config
# (e.g. the old SpreadCycle-hybrid runs whose floor collapsed to ~6), which drags
# the pooled floor down and yields a uselessly low threshold. The freshest run is
# the one tuned to the current config. Percentiles within that run still guard
# against single-sample outliers.
# ---------------------------------------------------------------------------

_FLOOR_PERCENTILE = 0.05   # unloaded: worst-case normal cruise (low end of floor)
_DIP_PERCENTILE = 0.10     # loaded: representative stall dip (low end)

# Cruise TSTEP / TCOOLTHRS derivation. The single biggest tuning trap was leaving
# TCOOLTHRS (the velocity gate) as a typed guess: if it sits below the motor's real
# cruise TSTEP at the operating speed, the gate is shut the whole move and DIAG
# never fires no matter the SGTHRS. So we MEASURE it. The fastest-sustained TSTEP
# (a low percentile of the moving samples) is the cruise floor; the enforcement
# gate is set a margin above it so it stays open through cruise (incl. a slightly
# slower loaded cruise) but closed during accel/decel/reversal, where SG is junk.
# Margin 1.75 reproduces the empirically-good chute value (cruise ~114 -> ~200).
_CRUISE_TSTEP_PERCENTILE = 0.10  # fastest-sustained TSTEP = cruise floor
_TCOOLTHRS_CRUISE_MARGIN = 1.75  # gate = this * measured cruise floor
_TSTEP_STANDSTILL = 1_000_000    # >= this is the TMC standstill reading, not motion

# Reliability cross-check. A gentle unloaded sweep gives an optimistically clean
# floor; real reversing motion at the same speed can dip cruise SG far lower
# (StealthChop's SG baseline isn't always stable run-to-run). So we cross-check the
# proposed trigger against the worst in-gate SG seen in recent REAL motion (the
# stress-test runs). If normal motion gets within this margin of the trip line,
# no SGTHRS is safe at this speed and we say so loudly instead of pretending.
_REALISTIC_RUNS = 6              # recent stress runs to scan for the worst floor
_REALISTIC_FLOOR_PERCENTILE = 0.02
_RELIABLE_MARGIN = 1.5          # realistic floor must clear the trigger by this much
_STALL_CAPTURE_RATIO = 0.5     # a loaded run must dip to <= this * floor to count


class StallGuardSuggestionResponse(BaseModel):
    success: bool
    stepper: str
    cruise_tstep: int            # recommended TCOOLTHRS (derived, or override)
    measured_cruise_tstep: Optional[int]  # raw fastest-sustained TSTEP from the data
    unloaded_floor: Optional[int]
    loaded_dip: Optional[int]
    trigger_level: Optional[int]
    suggested_sgthrs: Optional[int]
    enough_data: bool
    # reliable=False means a threshold CAN be computed but the data says it won't
    # actually work at this speed — show a hard warning, not a confident Save.
    reliable: bool
    realistic_floor: Optional[int]  # lowest cruise SG seen in real (stress) motion
    speed: Optional[int]            # operating speed of the unloaded run, for messaging
    unloaded_runs: int
    loaded_runs: int
    detail: str


def _percentile(sorted_vals: List[int], q: float) -> Optional[int]:
    if not sorted_vals:
        return None
    idx = int(round(q * (len(sorted_vals) - 1)))
    return sorted_vals[max(0, min(len(sorted_vals) - 1, idx))]


def _moving_tstep(run: Optional[Dict[str, Any]]) -> List[int]:
    if run is None:
        return []
    out: List[int] = []
    for s in stepper_telemetry.getRunSamples(run["id"]):
        ts = s.get("tstep")
        if isinstance(ts, int) and 0 < ts < _TSTEP_STANDSTILL:
            out.append(ts)
    return sorted(out)


def _measured_cruise_tstep(*runs: Optional[Dict[str, Any]]) -> Optional[int]:
    """Fastest-sustained TSTEP (cruise floor) from the first run that has motion."""
    for run in runs:
        ts = _moving_tstep(run)
        if ts:
            return _percentile(ts, _CRUISE_TSTEP_PERCENTILE)
    return None


def _cruise_sg(run: Optional[Dict[str, Any]], cruise_tstep: int) -> List[int]:
    if run is None:
        return []
    out: List[int] = []
    for s in stepper_telemetry.getRunSamples(run["id"]):
        sg = s.get("sg_result")
        ts = s.get("tstep")
        if (
            isinstance(sg, int)
            and sg >= 0
            and isinstance(ts, int)
            and 0 <= ts <= cruise_tstep
        ):
            out.append(sg)
    return sorted(out)


def _realistic_in_gate_floor(
    toml_name: str, cruise_tstep: int, speed: Optional[int]
) -> Optional[int]:
    """Worst-case cruise SG seen in recent REAL (stress-test) motion, AT THIS SPEED.
    The pessimistic p02 across the last few stress runs — what ordinary reversing
    motion actually produces in-gate, vs the cleaner number a gentle sweep reports.
    Filtered to samples whose commanded_speed matches so a run at another speed can't
    poison the verdict. None if there's no matching stress data (only the chute has it)."""
    runs = stepper_telemetry.listRuns(
        stepper_name=toml_name,
        source=stepper_telemetry.SOURCE_CHUTE_STRESS,
        limit=_REALISTIC_RUNS,
    )
    worst: Optional[int] = None
    for r in runs:
        vals: List[int] = []
        for s in stepper_telemetry.getRunSamples(r["id"]):
            sg = s.get("sg_result")
            ts = s.get("tstep")
            cs = s.get("commanded_speed")
            if not (isinstance(sg, int) and sg >= 0 and isinstance(ts, int) and 0 <= ts <= cruise_tstep):
                continue
            if speed is not None and (not isinstance(cs, int) or cs != speed):
                continue
            vals.append(sg)
        p = _percentile(sorted(vals), _REALISTIC_FLOOR_PERCENTILE)
        if p is not None:
            worst = p if worst is None else min(worst, p)
    return worst


@router.get(
    "/stepper/{stepper}/stallguard-suggestion",
    response_model=StallGuardSuggestionResponse,
)
def stallguard_suggestion(
    stepper: str, cruise_tstep: Optional[int] = None, speed: Optional[int] = None
) -> StallGuardSuggestionResponse:
    """Pure DB analysis — no hardware. Takes cruise SG from the latest unloaded
    (sweep) and latest loaded (stall_test) run for this motor and returns the
    geometric-midpoint trigger between the normal floor and the stall dip.

    SG floor/dip/baseline all shift with speed, so when `speed` is given every input
    (unloaded, loaded, stress) is filtered to that speed — otherwise a 2000 sweep
    could get paired with an old 3000 stall test and a clean run wrongly flagged.
    The UI passes the selected run's speed so the suggestion matches what you see."""
    if stepper not in _STEPPER_API_TO_TOML_NAME:
        raise HTTPException(status_code=400, detail=f"Unknown stepper '{stepper}'")

    def _run_speed(r: Dict[str, Any]) -> Optional[int]:
        p = r.get("params")
        sp = p.get("speed") if isinstance(p, dict) else None
        return int(sp) if isinstance(sp, (int, float)) else None

    def _latest(source: str) -> Optional[Dict[str, Any]]:
        rows = stepper_telemetry.listRuns(
            stepper_name=stepper, source=source, limit=50
        )
        for r in rows:  # listRuns is newest-first
            if r.get("status") != stepper_telemetry.RUN_STATUS_COMPLETED:
                continue
            if speed is not None and _run_speed(r) != speed:
                continue
            return r
        return None

    unloaded_run = _latest(stepper_telemetry.SOURCE_SWEEP)
    loaded_run = _latest(stepper_telemetry.SOURCE_STALL_TEST)

    # Measure the cruise floor from the data (unloaded preferred), then set the
    # recommended TCOOLTHRS a margin above it. An explicit ?cruise_tstep= overrides
    # the derivation (manual tuning); otherwise everything below — including the
    # cruise filter for the SG floor/dip — uses the measured gate, so the threshold
    # is computed within the exact velocity window enforcement will use.
    measured_ct = _measured_cruise_tstep(unloaded_run, loaded_run)
    if cruise_tstep is not None:
        ct = max(1, cruise_tstep)
    elif measured_ct is not None:
        ct = max(1, int(round(measured_ct * _TCOOLTHRS_CRUISE_MARGIN)))
    else:
        ct = 150  # no motion data yet — harmless fallback

    unloaded_cruise = _cruise_sg(unloaded_run, ct)
    loaded_cruise = _cruise_sg(loaded_run, ct)
    floor = _percentile(unloaded_cruise, _FLOOR_PERCENTILE)
    dip = _percentile(loaded_cruise, _DIP_PERCENTILE)

    eff_speed = speed if speed is not None else (_run_speed(unloaded_run) if unloaded_run else None)
    speed_txt = f"{eff_speed} µs/s" if eff_speed else "this speed"

    toml_name = _STEPPER_API_TO_TOML_NAME.get(stepper, stepper)
    realistic_floor = _realistic_in_gate_floor(toml_name, ct, eff_speed)

    trigger: Optional[int] = None
    sgthrs: Optional[int] = None
    enough = False
    reliable = False
    if floor is not None and dip is not None:
        # Geometric midpoint of the gap. Clamp dip to >=1 so a stall floor that
        # reaches 0 doesn't collapse the geo-mean to 0.
        trigger = int(round(math.sqrt(float(floor) * float(max(1, dip)))))
        sgthrs = max(1, min(255, round(trigger / 2)))
        enough = True
        gate_note = (
            f"; gate TCOOLTHRS {ct} = cruise {measured_ct}×{_TCOOLTHRS_CRUISE_MARGIN:g}"
            if measured_ct is not None
            else f"; gate TCOOLTHRS {ct} (manual)"
        )
        # Did the loaded run actually stall? If it never dipped well below the
        # floor, it's not a real stall reference and the trigger is guesswork.
        loaded_min = loaded_cruise[0] if loaded_cruise else None
        captured_stall = loaded_min is not None and loaded_min <= floor * _STALL_CAPTURE_RATIO

        if realistic_floor is not None and realistic_floor < trigger * _RELIABLE_MARGIN:
            # The killer case: real reversing motion dips into the trip range, so no
            # SGTHRS separates a stall from an ordinary move at this speed.
            reliable = False
            detail = (
                f"⚠ NOT reliably tunable at {speed_txt}. Real (stress-test) motion dips to "
                f"SG {realistic_floor} at cruise — at/near the {trigger} trip line — so this "
                f"threshold WILL false-trip on ordinary moves. The cruise SG baseline isn't "
                f"stable enough at this speed to separate normal motion from a stall. Lower the "
                f"speed for a steadier baseline and re-characterize, or accept it's unreliable."
            )
        elif not captured_stall:
            reliable = False
            detail = (
                f"⚠ The loaded run never actually stalled — its cruise SG only reached "
                f"{loaded_min} vs the {floor} unloaded floor. Hold/resist the motor until it "
                f"bogs down, then re-run the loaded sweep so there's a real stall to tune to."
            )
        else:
            reliable = True
            extra = (
                f" Real-motion floor {realistic_floor} clears it."
                if realistic_floor is not None
                else ""
            )
            detail = (
                f"Balanced trigger {trigger} = geo-mean(floor {floor}, dip {dip}) "
                f"from the latest unloaded + latest loaded run{gate_note}.{extra}"
            )
    elif floor is not None:
        # Provisional: no loaded stall test yet, so we can't see the dip. Fall
        # back to a fraction of the floor and flag it as unvalidated.
        trigger = int(round(floor * 0.4))
        sgthrs = max(1, min(255, round(trigger / 2)))
        detail = (
            f"No loaded stall test at {speed_txt} yet — provisional SGTHRS from the "
            "unloaded floor only. Run a loaded (held/resisted) sweep at this speed to validate."
        )
    elif dip is not None:
        detail = "Only loaded runs found — run an unloaded sweep to measure the normal floor."
    elif unloaded_run is not None or loaded_run is not None:
        # Runs exist and completed, but the cruise filter kept nothing from either
        # — every sample was below cruise velocity (TSTEP > cruise_tstep). This is
        # what the pulsed/jitter profiles produce: the motor never sustains cruise,
        # so SG_RESULT is all accel/decel and there's no valid load reading to tune
        # from. Don't tell the user to re-run sweeps they already ran.
        have = " + ".join(
            kind
            for kind, run in (("unloaded", unloaded_run), ("loaded", loaded_run))
            if run is not None
        )
        detail = (
            f"Latest {have} run completed but produced 0 cruise samples "
            f"(none reached TSTEP <= {ct}) — the profile never sustained cruise "
            "velocity. StallGuard only reads load at constant cruise; use the "
            "constant profile to calibrate SGTHRS."
        )
    else:
        detail = "No completed runs for this motor yet — run an unloaded and a loaded sweep."

    return StallGuardSuggestionResponse(
        success=True,
        stepper=stepper,
        cruise_tstep=ct,
        measured_cruise_tstep=measured_ct,
        unloaded_floor=floor,
        loaded_dip=dip,
        trigger_level=trigger,
        suggested_sgthrs=sgthrs,
        enough_data=enough,
        reliable=reliable,
        realistic_floor=realistic_floor,
        speed=eff_speed,
        unloaded_runs=1 if unloaded_run else 0,
        loaded_runs=1 if loaded_run else 0,
        detail=detail,
    )


def _armed_steppers() -> List[Any]:
    """Every stall-armed StepperMotor across all boards (raw per-board objects)."""
    irl = shared_state.getActiveIRL()
    out: List[Any] = []
    interfaces = getattr(irl, "interfaces", None) or {}
    for iface in interfaces.values():
        for st in getattr(iface, "steppers", ()):
            if getattr(st, "stallguard_enabled", False):
                out.append(st)
    return out


def _clear_one_stall(stepper: Any) -> None:
    """Clear a stepper's firmware DIAG latch and re-arm detection. The monitor's
    next poll mirrors the now-cleared state and the derived incident follows."""
    stepper.clear_stall()
    stepper.enable_stall_detection(bool(getattr(stepper, "stallguard_enabled", False)))
    stepper.stalled = False


@router.get("/steppers/stall-state")
def steppers_stall_state() -> Dict[str, Any]:
    """Live per-stepper stall latch, keyed by API stepper name (the same name the
    station pages use) — what the UI polls to show stall badges and resolve
    incidents indirectly. Keyed by API name, NOT the raw firmware name, so the
    frontend's stepperKey lookups match."""
    state: Dict[str, Any] = {}
    try:
        mapping = _stepper_mapping()
    except HTTPException:
        return {"steppers": state}
    for api_name, stepper in mapping.items():
        if stepper is None or not getattr(stepper, "stallguard_enabled", False):
            continue
        state[api_name] = {
            "stalled": bool(getattr(stepper, "stalled", False)),
            "enabled": True,
        }
    return {"steppers": state}


@router.post("/stepper/{stepper}/clear-stall")
def clear_stepper_stall(stepper: str) -> Dict[str, Any]:
    """Clear ONE motor's stall latch (from its station page). The blocking incident
    is derived from the latch state, so it resolves on the next monitor poll once no
    motor is still latched — no separate ack needed."""
    target = _resolve_stepper(stepper)
    try:
        _clear_one_stall(target)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to clear stall: {e}")
    return {"ok": True, "stepper": stepper, "stalled": False}


@router.post("/stall-incident/clear")
def clear_stall_incident() -> Dict[str, Any]:
    """Clear ALL motors' stall latches (the global 'Acknowledge'). Resets every
    armed driver's firmware latch + re-arms, then drops the blocking incident; the
    monitor confirms the cleared state on its next poll."""
    from stepper_stall_monitor import STEPPER_STALL_INCIDENT_KIND

    gc = shared_state.gc_ref
    runtime_stats = getattr(gc, "runtime_stats", None) if gc is not None else None
    if runtime_stats is None or not hasattr(runtime_stats, "clearActiveIncident"):
        raise HTTPException(status_code=503, detail="runtime stats unavailable")

    for st in _armed_steppers():
        try:
            _clear_one_stall(st)
        except Exception:
            pass  # best-effort; the monitor re-reads and a stuck latch re-raises

    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    runtime_stats.clearActiveIncident(kind=STEPPER_STALL_INCIDENT_KIND)
    cleared = isinstance(active, dict) and active.get("kind") == STEPPER_STALL_INCIDENT_KIND
    return {"ok": True, "cleared": cleared, "kind": STEPPER_STALL_INCIDENT_KIND}


@router.post("/stall-incident/rehome")
def rehome_after_stall() -> Dict[str, Any]:
    """Clear stall latches AND re-home the chute in place, then drop the hold.

    A chute stall loses the home reference, so 'clear the stall' alone leaves the
    machine in a `chute_needs_homing` hold. This is the one-shot 'clear + re-home'
    the operator gets on the stall/needs-homing cards. The blocking incident is
    kept active across the (blocking) home so the coordinator — which skips
    distribution while any incident is active — never commands the chute out from
    under the homing move. Only proceeds when such a hold is active, which
    guarantees the coordinator is already parked."""
    from stepper_stall_monitor import (
        STEPPER_STALL_INCIDENT_KIND,
        CHUTE_NEEDS_HOMING_INCIDENT_KIND,
    )

    from server.routers.hardware import _ensure_not_homing

    _ensure_not_homing("re-home the chute")

    gc = shared_state.gc_ref
    runtime_stats = getattr(gc, "runtime_stats", None) if gc is not None else None
    if runtime_stats is None or not hasattr(runtime_stats, "clearActiveIncident"):
        raise HTTPException(status_code=503, detail="runtime stats unavailable")

    ours = {STEPPER_STALL_INCIDENT_KIND, CHUTE_NEEDS_HOMING_INCIDENT_KIND}
    active = runtime_stats.activeIncident() if hasattr(runtime_stats, "activeIncident") else None
    active_kind = active.get("kind") if isinstance(active, dict) else None
    if active_kind not in ours:
        raise HTTPException(
            status_code=409,
            detail="No stall or needs-homing hold is active; nothing to re-home.",
        )

    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized.")
    chute = getattr(irl, "chute", None)
    if chute is None or not hasattr(chute, "home"):
        raise HTTPException(status_code=503, detail="Chute subsystem unavailable.")

    for st in _armed_steppers():
        try:
            _clear_one_stall(st)
        except Exception:
            pass  # best-effort; a stuck latch just re-raises the stall hold

    try:
        irl.enableSteppers()
    except Exception:
        pass

    try:
        homed = bool(chute.home())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chute re-home failed: {e}")
    if not homed:
        raise HTTPException(
            status_code=409,
            detail=(
                "Chute homing stopped before the endstop triggered. Clear any "
                "obstruction and try again."
            ),
        )

    # The chute is homed now; drop our hold immediately (the monitor would clear
    # it on its next poll anyway, but don't make the operator watch it linger).
    active_kind = runtime_stats.activeIncident()
    active_kind = active_kind.get("kind") if isinstance(active_kind, dict) else None
    if active_kind in ours:
        runtime_stats.clearActiveIncident(kind=active_kind)
    return {"ok": True, "homed": True}
