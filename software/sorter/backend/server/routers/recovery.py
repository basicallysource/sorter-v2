"""Shakes by hand: the dashboard's Shake menu runs exactly the shakes a recovery
procedure runs (recovery/profiles.py, through recovery/motors.py)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/recovery/shakes")
def list_shakes() -> dict[str, Any]:
    import recovery

    return {
        "shakes": [{"key": p.key, "label": p.label, "blurb": p.blurb} for p in recovery.SHAKES],
        "recovery": recovery.current(),
    }


@router.post("/api/recovery/shake")
def shake(stepper: str, profile: str) -> dict[str, Any]:
    import recovery
    from server.routers.steppers import _ensure_manual_motion_allowed, _resolve_stepper

    _ensure_manual_motion_allowed("shake a channel")
    if recovery.running():
        raise HTTPException(status_code=409, detail="A recovery is moving the channels; stop it first.")
    try:
        chosen = recovery.shakeProfile(profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    motor = recovery.ChannelMotor(stepper, _resolve_stepper(stepper), lambda deg: 0)
    if not motor.idle():
        raise HTTPException(status_code=409, detail="That channel is still moving.")
    seconds = motor.shake(chosen)
    if seconds is None:
        raise HTTPException(status_code=409, detail="The motor did not take the shake; it may still be shaking.")
    return {"ok": True, "stepper": stepper, "profile": chosen.key, "seconds": round(seconds, 1)}
