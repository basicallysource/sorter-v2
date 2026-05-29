"""Router for stepper / StallGuard telemetry: recorded runs, samples, rollups.

The data is written by the StallGuard sweep endpoint (server/routers/steppers.py)
and by the passive background sampler. This router is read-only plus run deletion;
it backs the telemetry visualization page.
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import stepper_telemetry

router = APIRouter()


class TelemetryRunsResponse(BaseModel):
    runs: List[dict]


class StepperSummaryResponse(BaseModel):
    steppers: List[dict]


@router.get("/api/stepper-telemetry/runs", response_model=TelemetryRunsResponse)
def listTelemetryRuns(
    limit: int = 100,
    source: Optional[str] = None,
    stepper: Optional[str] = None,
) -> TelemetryRunsResponse:
    if limit <= 0 or limit > 2000:
        raise HTTPException(status_code=400, detail="limit must be in (0, 2000]")
    return TelemetryRunsResponse(
        runs=stepper_telemetry.listRuns(limit=limit, source=source, stepper_name=stepper)
    )


@router.get("/api/stepper-telemetry/summary", response_model=StepperSummaryResponse)
def stepperTelemetrySummary() -> StepperSummaryResponse:
    return StepperSummaryResponse(steppers=stepper_telemetry.getStepperSummary())


@router.get("/api/stepper-telemetry/runs/{run_id}")
def getTelemetryRun(run_id: str) -> dict[str, Any]:
    run = stepper_telemetry.getRun(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run


@router.get("/api/stepper-telemetry/runs/{run_id}/samples")
def getTelemetryRunSamples(run_id: str, max_points: int = 5000) -> dict[str, Any]:
    run = stepper_telemetry.getRun(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    if max_points <= 0 or max_points > 50000:
        raise HTTPException(status_code=400, detail="max_points must be in (0, 50000]")
    samples = stepper_telemetry.getRunSamples(run_id, max_points=max_points)
    return {"run": run, "samples": samples}


@router.delete("/api/stepper-telemetry/runs/{run_id}")
def deleteTelemetryRun(run_id: str) -> dict[str, bool]:
    if stepper_telemetry.getRun(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    stepper_telemetry.deleteRun(run_id)
    return {"success": True}
