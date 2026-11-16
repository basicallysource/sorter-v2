"""The stepper drivers' readings, as the watch keeps them (driver_watch.py):
every driver's latest reading, what is wrong with it now and what was done to
get it working again, and one driver's readings over a stretch of time for the
pages that draw them. On a machine that does not watch its drivers both
answers say so (`enabled` false) and hold nothing."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

import driver_watch
from hardware_settings.motors import motorNamed

router = APIRouter()


@router.get("/api/drivers")
def get_drivers() -> dict[str, Any]:
    return driver_watch.describe()


@router.get("/api/drivers/{name}/history")
def get_driver_history(
    name: str,
    seconds: float = Query(600.0, gt=0, le=driver_watch.RETENTION_S),
) -> dict[str, Any]:
    """The readings of the last `seconds`, oldest first, thinned to about
    driver_watch.HISTORY_SAMPLES. `name` is a motor's, as /api/stepper/{name}/tmc
    takes it; a name no motor has is a 404, since no record is kept for it."""
    motor = motorNamed(name)
    if motor is None:
        raise HTTPException(status_code=404, detail=f"Unknown stepper '{name}'")
    return driver_watch.history(motor, name, seconds)
