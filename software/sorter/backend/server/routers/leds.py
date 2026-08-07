"""LED endpoints: on/off, brightness, and whether the LEDs light up at boot."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from local_state import (
    LED_CONTROL_DEFAULTS,
    get_led_control_state,
    set_led_control_state,
)
from server import shared_state

router = APIRouter()


class LedSettingsPayload(BaseModel):
    enabled: bool | None = None
    brightness_percent: int | None = None
    on_at_boot: bool | None = None


def _ledController() -> Any | None:
    # getActiveIRL() falls back to the runtime IRL when the controller has no
    # .irl of its own. Reading controller_ref directly misses that case, and the
    # miss is silent: the endpoint takes the offline path and reports success
    # while the LEDs keep whatever duty hardware init left them at.
    irl = shared_state.getActiveIRL()
    return getattr(irl, "led_controller", None) if irl is not None else None


def _offlineStatus() -> dict[str, Any]:
    # Hardware is not up (standby, or a machine with no boards discovered yet).
    # Still report the persisted settings so the UI renders the real values.
    return {
        **get_led_control_state(),
        "defaults": dict(LED_CONTROL_DEFAULTS),
        "configured": False,
        "pwm_supported": False,
        "leds": [],
        "hardware_ready": False,
    }


@router.get("/api/leds")
def get_leds() -> dict[str, Any]:
    led_controller = _ledController()
    if led_controller is None:
        return _offlineStatus()
    return {**led_controller.status(), "hardware_ready": True}


@router.post("/api/leds")
def set_leds(payload: LedSettingsPayload) -> dict[str, Any]:
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No LED settings supplied")

    brightness = updates.get("brightness_percent")
    if brightness is not None and not 0 <= brightness <= 100:
        raise HTTPException(
            status_code=400, detail="brightness_percent must be between 0 and 100"
        )

    led_controller = _ledController()
    if led_controller is None:
        # Standby, or hardware not discovered yet. Persist anyway so the choice
        # survives to the next hardware init instead of silently failing.
        set_led_control_state({**get_led_control_state(), **updates})
        return _offlineStatus()

    led_controller.update(updates)
    return {**led_controller.status(), "hardware_ready": True}
