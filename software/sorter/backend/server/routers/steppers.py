"""Router for stepper motion and TMC driver settings, and the hardware-busy guards other routers share."""

from __future__ import annotations

import contextlib
import math
import threading
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from defs.events import (
    PauseCommandData,
    PauseCommandEvent,
    ResumeCommandData,
    ResumeCommandEvent,
)
from defs.sorter_controller import SorterLifecycle
from hardware_settings.motors import Motor, apiNames, motorNamed
from hardware_settings.steppers import (
    TMC_REG_COOLCONF,
    TMC_REG_GCONF,
    StepperSettings,
    applyStepperSettings,
    changedStepperSettings,
    readStepperSettings,
    saveStepperSettings,
)
from server import shared_state
from stepper_stall_monitor import CHUTE_NEEDS_HOMING_INCIDENT_KIND, STEPPER_STALL_INCIDENT_KIND

router = APIRouter()

MAX_STEPPER_PULSE_DURATION_S = 120.0


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class StateResponse(BaseModel):
    state: str


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


class TmcSettingsRequest(BaseModel):
    irun: Optional[int] = None
    ihold: Optional[int] = None
    microsteps: Optional[int] = None
    stealthchop: Optional[bool] = None
    coolstep: Optional[bool] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stepper_mapping() -> Dict[str, Any]:
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Start or home the system first.")
    return {name: getattr(irl, motorNamed(name).attr, None) for name in apiNames()}


def _motor(name: str) -> Motor:
    motor = motorNamed(name)
    if motor is None:
        raise HTTPException(status_code=400, detail=f"Unknown stepper '{name}'")
    return motor


def _live_stepper(motor: Motor) -> Any | None:
    irl = shared_state.getActiveIRL()
    return getattr(irl, motor.attr, None) if irl is not None else None


def save_stepper_settings(motor: Motor, changes: Dict[str, Any]) -> tuple[StepperSettings, bool]:
    """Save settings and put them on the running motor; with the hardware down
    they apply at the next start. Returns the settings and whether they were
    applied now. A change the running driver refuses is not saved, since the
    next start would stop on the same refusal."""
    try:
        updated = changedStepperSettings(motor, changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    stepper = _live_stepper(motor)
    if stepper is not None and changes:
        try:
            applyStepperSettings(stepper, updated, changes)
        except Exception as exc:
            with contextlib.suppress(Exception):
                applyStepperSettings(stepper, readStepperSettings(motor), changes)
            raise HTTPException(
                status_code=502,
                detail=f"The {motor.label} stepper did not take it, so it was not saved: {exc}",
            )
    return saveStepperSettings(motor, changes), stepper is not None and bool(changes)


def _resolve_stepper(stepper_name: str) -> Any:
    mapping = _stepper_mapping()

    if stepper_name not in mapping:
        raise HTTPException(status_code=400, detail=f"Unknown stepper '{stepper_name}'")

    stepper = mapping[stepper_name]
    if stepper is None:
        raise HTTPException(status_code=500, detail=f"Stepper '{stepper_name}' unavailable")
    return stepper


def _ensure_not_homing(action: str) -> None:
    worker = shared_state.hardware_worker_thread
    if (
        (worker is not None and worker.is_alive())
        or shared_state.hardware_state in {"homing", "initializing"}
    ):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} while hardware is {shared_state.hardware_state}.",
        )


def _ensure_runtime_ready(action: str) -> None:
    _ensure_not_homing(action)
    if shared_state.hardware_state != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} while hardware is {shared_state.hardware_state}; run Safe Home first.",
        )


def _ensure_no_blocking_fault(action: str) -> None:
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
    from subsystems.power_stress import getActivePowerStressRunner

    power_runner = getActivePowerStressRunner()
    if power_runner is not None and power_runner.isActive():
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} while power stress is active.",
        )
    _ensure_not_homing(action)


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
                # Firmware brake-underflow guard: braking to zero with
                # min_speed 0 (left behind by feeder pulse moves) can step
                # _current_speed below zero, and pre-fix firmware misses the
                # stop catch on the signed/unsigned compare — unbounded motor
                # runaway. Raise the floor so the catch always fires.
                if hasattr(stepper, "set_speed_limits"):
                    try:
                        stepper.set_speed_limits(16, 60000)
                    except Exception:
                        pass
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


def _stop_all_steppers() -> None:
    """Stop all known steppers. Raises HTTPException on failure."""
    halted: list[str] = []
    errors: Dict[str, str] = {}

    for name, stepper in _stepper_mapping().items():
        if stepper is None:
            continue
        try:
            _halt_stepper(stepper)
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
# TMC2209 driver read-outs. The settings themselves are declared, saved and
# applied in hardware_settings.steppers.
# ---------------------------------------------------------------------------

TMC_REG_GSTAT = 0x01
TMC_REG_IFCNT = 0x02
TMC_REG_IOIN = 0x06
TMC_REG_FACTORY_CONF = 0x07
TMC_REG_TSTEP = 0x12
TMC_REG_SG_RESULT = 0x41
TMC_REG_MSCNT = 0x6A
TMC_REG_MSCURACT = 0x6B
TMC_REG_CHOPCONF = 0x6C
TMC_REG_DRV_STATUS = 0x6F
TMC_REG_PWM_CONF = 0x70
TMC_REG_PWM_SCALE = 0x71
TMC_REG_PWM_AUTO = 0x72

MRES_TO_MICROSTEPS = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1}

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


def settings_payload(settings: StepperSettings) -> Dict[str, Any]:
    """A motor's saved settings (its defaults where none is saved: the primary
    Hive's, else built in), as the driver settings form edits them."""
    return {
        "irun": settings.irun,
        "ihold": settings.ihold,
        "ihold_delay": settings.ihold_delay,
        "microsteps": settings.microsteps,
        "stealthchop": settings.stealthchop,
        "coolstep": settings.coolstep,
        "stallguard": {
            "sgthrs": settings.sgthrs,
            "tcoolthrs": settings.tcoolthrs,
            "enabled": settings.stallguard,
        },
        "inverted": settings.inverted,
        "saved": sorted(settings.saved),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/state", response_model=StateResponse)
def getState() -> StateResponse:
    if shared_state.controller_ref is None:
        return StateResponse(state=SorterLifecycle.INITIALIZING.value)
    return StateResponse(state=shared_state.controller_ref.state.value)


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


@router.post("/stepper/stop", response_model=StepperStopResponse)
def stop_stepper(stepper: str) -> StepperStopResponse:
    target = _resolve_stepper(stepper)

    try:
        _halt_stepper(target, force=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stop failed: {e}")

    return StepperStopResponse(success=True, stepper=stepper)


@router.get("/api/stepper/{name}/tmc")
def get_tmc_settings(name: str) -> Dict[str, Any]:
    """The motor's saved driver settings, which it runs on from every start and
    which a change applies at once, plus what its driver reads back when the
    hardware is up (`driver`, `registers`, DRV_STATUS, SG_RESULT)."""
    motor = _motor(name)
    stepper = _live_stepper(motor)
    result: Dict[str, Any] = {
        "hardware_ready": stepper is not None,
        **settings_payload(readStepperSettings(motor)),
        "capabilities": {
            "tmc_uart_available": False,
            "queryable_fields": list(TMC_QUERYABLE_FIELDS),
        },
        "registers": None,
        "driver": None,
        "drv_status": None,
        "sg_result": None,
        "stalled": False,
    }
    if stepper is None:
        return result

    registers = _tmc_register_snapshot(stepper)
    gconf_raw = registers["gconf"]
    chopconf_raw = registers["chopconf"]
    drv_status_raw = registers["drv_status"]
    result["capabilities"] = {
        **_stepper_diag_capabilities(stepper),
        "tmc_uart_available": True,
        "queryable_fields": list(TMC_QUERYABLE_FIELDS),
    }
    result["registers"] = registers
    # What the driver runs on now. IHOLD_IRUN, COOLCONF, SGTHRS and TCOOLTHRS
    # cannot be read back from a TMC2209, so the current is the last one sent.
    last_current = getattr(stepper, "last_set_current", None)
    result["driver"] = {
        **(last_current if isinstance(last_current, dict) else {"irun": None, "ihold": None, "ihold_delay": None}),
        "microsteps": _parse_chopconf_mres(chopconf_raw) if chopconf_raw is not None else None,
        "stealthchop": not bool(gconf_raw & (1 << 2)) if gconf_raw is not None else None,
        "direction_inverted": bool(getattr(stepper, "direction_inverted", False)),
    }
    if drv_status_raw is not None:
        # DRV_STATUS also contains its own SG_RESULT bitfield view. Keep both:
        # `registers.sg_result` is the raw 0x41 register, while
        # `drv_status.sg_result` is the SG_RESULT field decoded from 0x6F.
        result["drv_status"] = _parse_drv_status(drv_status_raw)
    # The direct 0x41 register value, at top level for convenience.
    result["sg_result"] = registers["sg_result"]
    # Live stall latch (mirrored by the stall monitor) so a station's page can show
    # "this motor is stalled" and offer to clear it.
    result["stalled"] = bool(getattr(stepper, "stalled", False))
    return result


@router.post("/api/stepper/{name}/tmc")
def set_tmc_settings(name: str, body: TmcSettingsRequest) -> Dict[str, Any]:
    """Save the settings sent and put them on the running driver; with the
    hardware down they are saved and apply at the next start."""
    save_stepper_settings(_motor(name), body.model_dump(exclude_none=True))
    return get_tmc_settings(name)
