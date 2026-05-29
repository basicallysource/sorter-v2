"""Router for stepper motor control and TMC driver settings endpoints."""

from __future__ import annotations

import math
import os
import threading
import time
from typing import Any, Dict, List, Optional

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
            target.set_acceleration(int(acceleration))
            target.set_speed_limits(min_speed=int(min_speed), max_speed=int(speed))
        else:
            target.set_speed_limits(min_speed=16, max_speed=int(speed))
        if not bool(target.move_degrees(degrees, force=True)):
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
    stepper = _resolve_stepper(name)
    registers = _tmc_register_snapshot(stepper)
    gconf_raw = registers["gconf"]
    chopconf_raw = registers["chopconf"]
    coolconf_raw = registers["coolconf"]
    drv_status_raw = registers["drv_status"]

    result: Dict[str, Any] = {}
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
