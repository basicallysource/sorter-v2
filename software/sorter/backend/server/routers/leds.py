from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from irl.leds import assignChannelLed
from local_state import LED_CHANNEL_KEYS, get_led_state
from server import shared_state

router = APIRouter()


class LedAssignmentPayload(BaseModel):
    channel: str
    output: str | None = None
    brightness_percent: int = 100


def _ledController() -> Any | None:
    # getActiveIRL() falls back to the runtime IRL when the controller has no
    # .irl of its own. Reading controller_ref directly misses that case, and the
    # miss is silent: the endpoint reports success while the LEDs keep whatever
    # duty hardware init left them at.
    irl = shared_state.getActiveIRL()
    return getattr(irl, "led_controller", None) if irl is not None else None


def _status(state: dict[str, Any]) -> dict[str, Any]:
    # No outputs means no hardware exposing LED GPIOs (or none discovered yet);
    # the UI grays its card out on exactly that.
    controller = _ledController()
    return {
        "channels": list(LED_CHANNEL_KEYS),
        "outputs": controller.outputs if controller is not None else [],
        **state,
    }


@router.get("/api/leds")
def get_leds() -> dict[str, Any]:
    return _status(get_led_state())


@router.post("/api/leds")
def set_leds(payload: LedAssignmentPayload) -> dict[str, Any]:
    if payload.channel not in LED_CHANNEL_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown LED channel {payload.channel}")
    if not 0 <= payload.brightness_percent <= 100:
        raise HTTPException(
            status_code=400, detail="brightness_percent must be between 0 and 100"
        )

    state = assignChannelLed(payload.channel, payload.output, payload.brightness_percent)
    controller = _ledController()
    if controller is not None:
        controller.apply(state)
    return _status(state)
