from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from defs.sorter_controller import SorterLifecycle
from local_state import getPowerStressRun, listPowerStressRuns
from server import shared_state
from subsystems.power_stress import (
    DEFAULT_CHUTE_MAX_DEG,
    DEFAULT_CHUTE_SPEED,
    DEFAULT_DURATION_S,
    DEFAULT_STEPPER_SPEED,
    MAX_DURATION_S,
    MIN_DURATION_S,
    PowerStressParams,
    PowerStressTestRunner,
    getActivePowerStressRunner,
    getPowerStressRunner,
)

router = APIRouter()


class StartPowerStressRequest(BaseModel):
    duration_s: float = Field(DEFAULT_DURATION_S, ge=MIN_DURATION_S, le=MAX_DURATION_S)
    stepper_speed_microsteps_per_sec: int = Field(DEFAULT_STEPPER_SPEED, gt=16, le=20000)
    chute_speed_microsteps_per_sec: int = Field(DEFAULT_CHUTE_SPEED, gt=16, le=10000)
    chute_max_deg: float = Field(DEFAULT_CHUTE_MAX_DEG, ge=5, le=DEFAULT_CHUTE_MAX_DEG)


class PowerStressStateResponse(BaseModel):
    active: bool
    run: dict[str, Any] | None = None


class PowerStressRunsResponse(BaseModel):
    runs: list[dict[str, Any]]


def _hardwareWorkerAlive() -> bool:
    worker = shared_state.hardware_worker_thread
    return bool(worker is not None and worker.is_alive())


def _ensureReady() -> Any:
    if _hardwareWorkerAlive() or shared_state.hardware_state != "ready":
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot run power stress test while hardware is "
                f"{shared_state.hardware_state}; run Safe Home first."
            ),
        )
    controller = shared_state.controller_ref
    state = getattr(controller, "state", None)
    if state != SorterLifecycle.PAUSED:
        state_value = getattr(state, "value", "unavailable")
        raise HTTPException(
            status_code=409,
            detail=f"Pause the sorter before starting power stress; sorter is {state_value}.",
        )
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(status_code=503, detail="Hardware is unavailable")
    return irl


def _activeRunner() -> PowerStressTestRunner:
    runner = getActivePowerStressRunner()
    if runner is None or not runner.isActive():
        raise HTTPException(status_code=409, detail="No power stress test is running")
    return runner


@router.post("/api/power-stress/start", response_model=PowerStressStateResponse)
def startPowerStress(payload: StartPowerStressRequest) -> PowerStressStateResponse:
    irl = _ensureReady()
    gc = shared_state.gc_ref
    if gc is None:
        raise HTTPException(status_code=503, detail="Backend configuration is unavailable")
    try:
        runner = getPowerStressRunner(gc, irl)
        state = runner.start(
            PowerStressParams(
                duration_s=float(payload.duration_s),
                stepper_speed_microsteps_per_sec=int(
                    payload.stepper_speed_microsteps_per_sec
                ),
                chute_speed_microsteps_per_sec=int(payload.chute_speed_microsteps_per_sec),
                chute_max_deg=float(payload.chute_max_deg),
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PowerStressStateResponse(active=True, run=state.toDict())


@router.post("/api/power-stress/stop", response_model=PowerStressStateResponse)
def stopPowerStress() -> PowerStressStateResponse:
    runner = _activeRunner()
    try:
        runner.stop()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    state = runner.getState()
    return PowerStressStateResponse(
        active=runner.isActive(), run=state.toDict() if state is not None else None
    )


@router.get("/api/power-stress/status", response_model=PowerStressStateResponse)
def getPowerStressStatus() -> PowerStressStateResponse:
    runner = getActivePowerStressRunner()
    if runner is None:
        return PowerStressStateResponse(active=False, run=None)
    state = runner.getState()
    return PowerStressStateResponse(
        active=runner.isActive(), run=state.toDict() if state is not None else None
    )


@router.get("/api/power-stress/runs", response_model=PowerStressRunsResponse)
def getPowerStressRuns(limit: int = 50) -> PowerStressRunsResponse:
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    return PowerStressRunsResponse(runs=listPowerStressRuns(limit=limit))


@router.get("/api/power-stress/runs/{run_id}")
def getPowerStressRunById(run_id: str) -> dict[str, Any]:
    run = getPowerStressRun(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run
