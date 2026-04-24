"""Router for stepper motor control and TMC driver settings endpoints."""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional

from toml_config import loadTomlFile

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
from hardware.tmc2209_status import (
    TMC_REG_DRV_STATUS,
    active_temperature_flags,
    overtemperature_fault_flags,
    parse_drv_status,
)
from server import shared_state

router = APIRouter()


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


class StepperStopResponse(BaseModel):
    success: bool
    stepper: str


class StepperStopAllResponse(BaseModel):
    success: bool
    steppers: List[str]


class TmcSettingsRequest(BaseModel):
    irun: Optional[int] = None
    ihold: Optional[int] = None
    microsteps: Optional[int] = None
    stealthchop: Optional[bool] = None
    coolstep: Optional[bool] = None
    driver_mode: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _getCameraLayout() -> str:
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if params_path and os.path.exists(params_path):
        raw = loadTomlFile(params_path)
        return raw.get("cameras", {}).get("layout", "default")
    return "default"


def _stepper_mapping() -> Dict[str, Any]:
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware not initialized. Start or home the system first.")
    return {
        "c_channel_1": getattr(irl, "c_channel_1_rotor_stepper", None),
        "c_channel_2": getattr(irl, "c_channel_2_rotor_stepper", None),
        "c_channel_3": getattr(irl, "c_channel_3_rotor_stepper", None),
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


def _halt_stepper(stepper: Any) -> None:
    errors: list[str] = []
    stopped = False

    if hasattr(stepper, "move_at_speed"):
        try:
            result = stepper.move_at_speed(0)
            stopped = stopped or bool(result)
            if result is False:
                errors.append("move_at_speed(0) was not acknowledged")
        except Exception as e:
            errors.append(f"move_at_speed(0) failed: {e}")

    if hasattr(stepper, "stop"):
        try:
            stepper.stop()
            stopped = True
        except Exception as e:
            errors.append(f"stop() failed: {e}")

    if hasattr(stepper, "enabled"):
        try:
            stepper.enabled = False
            stopped = True
        except Exception as e:
            errors.append(f"disable failed: {e}")

    if not stopped:
        detail = "; ".join(errors) if errors else "No supported stop method found"
        raise RuntimeError(detail)


def _stop_stepper_after_delay(stepper: Any, delay_s: float, lock: threading.Lock) -> None:
    try:
        time.sleep(delay_s)
        _halt_stepper(stepper)
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
TMC_REG_IFCNT = 0x02
TMC_REG_IHOLD_IRUN = 0x10
TMC_REG_TCOOLTHRS = 0x14
TMC_REG_COOLCONF = 0x42
TMC_REG_CHOPCONF = 0x6C
MRES_TO_MICROSTEPS = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1}
MICROSTEPS_TO_MRES = {v: k for k, v in MRES_TO_MICROSTEPS.items()}


def _parse_drv_status(raw: int) -> Dict[str, Any]:
    return parse_drv_status(raw)


def _effective_driver_mode(*, stealthchop: bool | None, coolstep: bool | None) -> str | None:
    if coolstep and not stealthchop:
        return "coolstep"
    if stealthchop:
        return "stealthchop"
    if coolstep is not None or stealthchop is not None:
        return "off"
    return None


def _driver_mode_warning(*, stealthchop: bool | None, coolstep: bool | None) -> str | None:
    if stealthchop and coolstep:
        return "CoolStep is configured but ineffective while StealthChop is active."
    return None


def _legacy_driver_mode_from_request(body: TmcSettingsRequest) -> str | None:
    if body.driver_mode is not None:
        mode = body.driver_mode.strip().lower()
        if mode not in {"off", "stealthchop", "coolstep"}:
            raise HTTPException(
                status_code=400,
                detail="driver_mode must be one of: off, stealthchop, coolstep",
            )
        return mode
    if body.coolstep is True:
        return "coolstep"
    if body.stealthchop is True:
        return "stealthchop"
    if body.coolstep is False or body.stealthchop is False:
        return "off"
    return None


def _apply_driver_mode(stepper: Any, mode: str) -> tuple[bool, bool]:
    gconf_raw = _safe_read_register(stepper, TMC_REG_GCONF)
    if gconf_raw is None:
        raise HTTPException(status_code=502, detail="Could not read TMC GCONF register")

    if mode == "stealthchop":
        stepper.write_driver_register(TMC_REG_COOLCONF, 0)
        stepper.write_driver_register(TMC_REG_TCOOLTHRS, 0)
        gconf_raw &= ~(1 << 2)  # clear EN_SPREADCYCLE
        stepper.write_driver_register(TMC_REG_GCONF, gconf_raw)
        return True, False
    if mode == "coolstep":
        gconf_raw |= (1 << 2)  # CoolStep needs SpreadCycle, not StealthChop.
        stepper.write_driver_register(TMC_REG_GCONF, gconf_raw)
        ifcnt_before = _safe_read_register(stepper, TMC_REG_IFCNT)
        coolconf = (5 & 0x0F) | ((2 & 0x0F) << 8) | ((1 & 0x03) << 5) | ((0 & 0x03) << 13)
        stepper.write_driver_register(TMC_REG_COOLCONF, coolconf)
        stepper.write_driver_register(TMC_REG_TCOOLTHRS, 0xFFFFF)
        ifcnt_after = _safe_read_register(stepper, TMC_REG_IFCNT)
        _verify_driver_mode(
            stepper,
            mode,
            ifcnt_before=ifcnt_before,
            ifcnt_after=ifcnt_after,
        )
        return False, True

    stepper.write_driver_register(TMC_REG_COOLCONF, 0)
    stepper.write_driver_register(TMC_REG_TCOOLTHRS, 0)
    gconf_raw |= (1 << 2)  # plain SpreadCycle
    stepper.write_driver_register(TMC_REG_GCONF, gconf_raw)
    return False, False


def _verify_driver_mode(
    stepper: Any,
    mode: str,
    *,
    ifcnt_before: int | None = None,
    ifcnt_after: int | None = None,
) -> None:
    if mode != "coolstep":
        return
    gconf_raw = _safe_read_register(stepper, TMC_REG_GCONF)
    coolconf_raw = _safe_read_register(stepper, TMC_REG_COOLCONF)
    tcoolthrs_raw = _safe_read_register(stepper, TMC_REG_TCOOLTHRS)

    failures: list[str] = []
    if gconf_raw is None or not bool(gconf_raw & (1 << 2)):
        failures.append("SpreadCycle bit did not stay enabled")
    if coolconf_raw is None or (coolconf_raw & 0x0F) == 0:
        failures.append("COOLCONF.semin stayed 0")
    if tcoolthrs_raw is None or tcoolthrs_raw == 0:
        failures.append("TCOOLTHRS stayed 0")
    if failures:
        details = "; ".join(failures)
        raw = {
            "gconf": gconf_raw,
            "coolconf": coolconf_raw,
            "tcoolthrs": tcoolthrs_raw,
            "ifcnt_before": ifcnt_before,
            "ifcnt_after": ifcnt_after,
        }
        raise HTTPException(
            status_code=502,
            detail=f"CoolStep did not stick on the TMC driver ({details}; raw={raw})",
        )


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


_STEPPER_API_TO_TOML_NAME: Dict[str, str] = {
    "c_channel_1": "c_channel_1_rotor",
    "c_channel_2": "c_channel_2_rotor",
    "c_channel_3": "c_channel_3_rotor",
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


def _persist_stepper_driver_setting(
    api_name: str,
    *,
    microsteps: Optional[int] = None,
    coolstep: Optional[bool] = None,
    stealthchop: Optional[bool] = None,
) -> None:
    toml_name = _STEPPER_API_TO_TOML_NAME.get(api_name, api_name)
    try:
        params_path, config = _read_machine_params_config()
        overrides = config.get("stepper_driver_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        entry = overrides.get(toml_name, {})
        if not isinstance(entry, dict):
            entry = {}
        if microsteps is not None:
            entry["microsteps"] = int(microsteps)
        if coolstep is not None:
            entry["coolstep"] = bool(coolstep)
        if stealthchop is not None:
            entry["stealthchop"] = bool(stealthchop)
        overrides[toml_name] = entry
        config["stepper_driver_overrides"] = overrides
        _write_machine_params_config(params_path, config)
    except Exception:
        pass  # best-effort persistence


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/state", response_model=StateResponse)
def getState() -> StateResponse:
    layout = _getCameraLayout()
    rt = shared_state.rt_handle
    if rt is None:
        return StateResponse(state=SorterLifecycle.INITIALIZING.value, camera_layout=layout)
    if getattr(rt, "paused", False):
        state = "paused"
    elif getattr(rt, "started", False):
        state = "running"
    else:
        state = SorterLifecycle.INITIALIZING.value
    return StateResponse(state=state, camera_layout=layout)


@router.post("/pause", response_model=CommandResponse)
def pause() -> CommandResponse:
    if shared_state.command_queue is None:
        raise HTTPException(status_code=500, detail="Command queue not initialized")
    event = PauseCommandEvent(tag="pause", data=PauseCommandData())
    shared_state.command_queue.put(event)
    return CommandResponse(success=True)


@router.post("/resume", response_model=CommandResponse)
def resume() -> CommandResponse:
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
    if duration_s <= 0 or duration_s > 5.0:
        raise HTTPException(status_code=400, detail="duration_s must be in (0, 5]")
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
        target.enabled = True
        target.move_at_speed(signed_speed)
    except Exception as e:
        lock.release()
        raise HTTPException(status_code=500, detail=f"Pulse start failed: {e}")

    threading.Thread(
        target=_stop_stepper_after_delay,
        args=(target, duration_s, lock),
        daemon=True,
    ).start()

    return StepperPulseResponse(
        success=True,
        stepper=stepper,
        direction=direction,
        duration_s=duration_s,
        speed=speed,
    )


@router.post("/stepper/move-degrees", response_model=StepperMoveDegreesResponse)
def move_stepper_degrees(
    stepper: str,
    degrees: float,
    speed: int = 800,
    min_speed: int | None = None,
    acceleration: int | None = None,
) -> StepperMoveDegreesResponse:
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
        target.enabled = True
        if want_ramp:
            target.set_acceleration(int(acceleration))
            target.set_speed_limits(min_speed=int(min_speed), max_speed=int(speed))
        else:
            target.set_speed_limits(min_speed=int(speed), max_speed=int(speed))
        target.move_degrees(degrees)
    except Exception as e:
        lock.release()
        raise HTTPException(status_code=500, detail=f"Move failed: {e}")

    def _release_after_move():
        try:
            start = time.monotonic()
            while not target.stopped and (time.monotonic() - start) < 30:
                time.sleep(0.02)
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
        _halt_stepper(target)
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

    return StepperStopAllResponse(success=True, steppers=halted)


@router.get("/api/stepper/{name}/tmc")
def get_tmc_settings(name: str) -> Dict[str, Any]:
    stepper = _resolve_stepper(name)

    gconf_raw = _safe_read_register(stepper, TMC_REG_GCONF)
    ifcnt_raw = _safe_read_register(stepper, TMC_REG_IFCNT)
    tcoolthrs_raw = _safe_read_register(stepper, TMC_REG_TCOOLTHRS)
    chopconf_raw = _safe_read_register(stepper, TMC_REG_CHOPCONF)
    coolconf_raw = _safe_read_register(stepper, TMC_REG_COOLCONF)
    drv_status_raw = _safe_read_register(stepper, TMC_REG_DRV_STATUS)

    result: Dict[str, Any] = {}
    current_payload = _desired_stepper_current_payload(name, stepper)
    result["irun"] = current_payload["irun"]
    result["ihold"] = current_payload["ihold"]

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

    result["driver_mode"] = _effective_driver_mode(
        stealthchop=result.get("stealthchop"),
        coolstep=result.get("coolstep"),
    )
    result["driver_mode_warning"] = _driver_mode_warning(
        stealthchop=result.get("stealthchop"),
        coolstep=result.get("coolstep"),
    )
    result["registers"] = {
        "gconf": gconf_raw,
        "ifcnt": ifcnt_raw,
        "tcoolthrs": tcoolthrs_raw,
        "chopconf": chopconf_raw,
        "coolconf": coolconf_raw,
        "drv_status": drv_status_raw,
    }

    if drv_status_raw is not None:
        drv_status = _parse_drv_status(drv_status_raw)
        result["drv_status"] = drv_status
        result["temperature_flags"] = active_temperature_flags(drv_status)
        result["thermal_fault_flags"] = overtemperature_fault_flags(drv_status)
    else:
        result["drv_status"] = None
        result["temperature_flags"] = []
        result["thermal_fault_flags"] = []

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
        _persist_stepper_driver_setting(name, microsteps=body.microsteps)

    driver_mode = _legacy_driver_mode_from_request(body)
    if driver_mode is not None:
        stealthchop, coolstep = _apply_driver_mode(stepper, driver_mode)
        _persist_stepper_driver_setting(
            name,
            stealthchop=stealthchop,
            coolstep=coolstep,
        )

    return get_tmc_settings(name)
