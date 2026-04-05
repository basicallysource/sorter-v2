"""Router for stepper motor control and TMC driver settings endpoints."""

from __future__ import annotations

import os
import threading
import time
import tomllib
from typing import Any, Dict, List, Optional

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _getCameraLayout() -> str:
    if shared_state.vision_manager is not None:
        return getattr(shared_state.vision_manager, "_camera_layout", "default")
    # Fallback: read directly from TOML
    params_path = os.getenv("MACHINE_SPECIFIC_PARAMS_PATH")
    if params_path and os.path.exists(params_path):
        try:
            with open(params_path, "rb") as f:
                raw = tomllib.load(f)
            return raw.get("cameras", {}).get("layout", "default")
        except Exception:
            pass
    return "default"


def _stepper_mapping() -> Dict[str, Any]:
    if shared_state.controller_ref is None or not hasattr(shared_state.controller_ref, "irl"):
        raise HTTPException(status_code=500, detail="Controller not initialized")

    irl = shared_state.controller_ref.irl
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
TMC_REG_IHOLD_IRUN = 0x10
TMC_REG_TCOOLTHRS = 0x14
TMC_REG_COOLCONF = 0x42
TMC_REG_CHOPCONF = 0x6C
TMC_REG_DRV_STATUS = 0x6F

MRES_TO_MICROSTEPS = {0: 256, 1: 128, 2: 64, 3: 32, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1}
MICROSTEPS_TO_MRES = {v: k for k, v in MRES_TO_MICROSTEPS.items()}


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
) -> StepperMoveDegreesResponse:
    if degrees == 0:
        raise HTTPException(status_code=400, detail="degrees must be non-zero")
    if speed <= 0:
        raise HTTPException(status_code=400, detail="speed must be > 0")

    target = _resolve_stepper(stepper)

    lock = shared_state.pulse_locks.setdefault(stepper, threading.Lock())
    if not lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=f"Stepper '{stepper}' is already moving")

    try:
        target.enabled = True
        target.set_speed_limits(min_speed=speed, max_speed=speed)
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

    if drv_status_raw is not None:
        result["drv_status"] = _parse_drv_status(drv_status_raw)
    else:
        result["drv_status"] = None

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
