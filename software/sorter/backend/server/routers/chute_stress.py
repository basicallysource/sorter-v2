"""Router for the chute stress-test mode."""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from local_state import getChuteStressRun, listChuteStressRuns
from server import shared_state
from subsystems.distribution.chute_stress import (
    CHUTE_MAX_ANGLE_LIMIT_DEG,
    ChuteStressTestRunner,
    StressTestParams,
    getActiveChuteStressRunner,
    getChuteStressRunner,
)

router = APIRouter()


class StartStressTestRequest(BaseModel):
    mode: str = Field(..., description="'sweep' or 'random'")
    target_max_deg: float = Field(..., gt=0, le=CHUTE_MAX_ANGLE_LIMIT_DEG)
    duration_s: float = Field(..., gt=0)
    speed_microsteps_per_sec: int = Field(..., gt=0)
    invert_direction: bool = False


class StressTestStateResponse(BaseModel):
    active: bool
    run: Optional[dict[str, Any]] = None


class StressTestRunsResponse(BaseModel):
    runs: List[dict[str, Any]]


def _resolveChute() -> Any:
    irl = shared_state.getActiveIRL()
    if irl is None:
        raise HTTPException(
            status_code=503,
            detail="Hardware not initialized. Start or home the system first.",
        )
    chute = getattr(irl, "chute", None)
    if chute is None:
        raise HTTPException(status_code=500, detail="Chute hardware unavailable")
    return chute


def _hardwareWorkerAlive() -> bool:
    worker = shared_state.hardware_worker_thread
    return bool(worker is not None and worker.is_alive())


def _ensureManualMotionAllowed() -> None:
    state = shared_state.hardware_state
    if _hardwareWorkerAlive() or state in {"homing", "initializing"}:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot run chute stress test while hardware is {state}.",
        )


def _activeRunner() -> ChuteStressTestRunner:
    runner = getActiveChuteStressRunner()
    if runner is None:
        raise HTTPException(status_code=409, detail="No chute stress test is running.")
    return runner


@router.post("/api/chute/stress-test/start", response_model=StressTestStateResponse)
def startStressTest(payload: StartStressTestRequest) -> StressTestStateResponse:
    _ensureManualMotionAllowed()
    chute = _resolveChute()
    gc = chute.gc

    runner = getChuteStressRunner(gc, chute)
    try:
        params = StressTestParams(
            mode=payload.mode,  # type: ignore[arg-type]
            target_max_deg=float(payload.target_max_deg),
            duration_s=float(payload.duration_s),
            speed_microsteps_per_sec=int(payload.speed_microsteps_per_sec),
            invert_direction=bool(payload.invert_direction),
        )
        state = runner.start(params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return StressTestStateResponse(active=True, run=state.toDict())


@router.post("/api/chute/stress-test/pause", response_model=StressTestStateResponse)
def pauseStressTest() -> StressTestStateResponse:
    runner = _activeRunner()
    try:
        runner.pause()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    state = runner.getState()
    return StressTestStateResponse(
        active=runner.isActive(),
        run=state.toDict() if state is not None else None,
    )


@router.post("/api/chute/stress-test/resume", response_model=StressTestStateResponse)
def resumeStressTest() -> StressTestStateResponse:
    runner = _activeRunner()
    try:
        runner.resume()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    state = runner.getState()
    return StressTestStateResponse(
        active=runner.isActive(),
        run=state.toDict() if state is not None else None,
    )


@router.post("/api/chute/stress-test/stop", response_model=StressTestStateResponse)
def stopStressTest() -> StressTestStateResponse:
    runner = _activeRunner()
    try:
        runner.stop()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    state = runner.getState()
    return StressTestStateResponse(
        active=runner.isActive(),
        run=state.toDict() if state is not None else None,
    )


@router.get("/api/chute/stress-test/status", response_model=StressTestStateResponse)
def getStressTestStatus() -> StressTestStateResponse:
    runner = getActiveChuteStressRunner()
    if runner is None:
        return StressTestStateResponse(active=False, run=None)
    state = runner.getState()
    return StressTestStateResponse(
        active=runner.isActive(),
        run=state.toDict() if state is not None else None,
    )


@router.get("/api/chute/stress-test/runs", response_model=StressTestRunsResponse)
def listStressTestRuns(limit: int = 100) -> StressTestRunsResponse:
    if limit <= 0 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be in (0, 1000]")
    return StressTestRunsResponse(runs=listChuteStressRuns(limit=limit))


@router.get("/api/chute/stress-test/runs/{run_id}")
def getStressTestRun(run_id: str) -> dict[str, Any]:
    run = getChuteStressRun(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run
