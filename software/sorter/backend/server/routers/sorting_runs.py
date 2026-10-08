from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import sorting_runs

router = APIRouter()


class LotIn(BaseModel):
    name: str
    description: Optional[str] = None


class LotPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class RunIn(BaseModel):
    name: str
    note: Optional[str] = None
    lot_id: Optional[str] = None
    adds_to_lot: bool = True
    # Unix seconds; leave out to start the run now.
    started_at: Optional[float] = None


class RunPatch(BaseModel):
    name: Optional[str] = None
    note: Optional[str] = None
    lot_id: Optional[str] = None
    adds_to_lot: Optional[bool] = None


def _call(fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except sorting_runs.RunError as exc:
        status = 404 if str(exc).startswith("No ") else 400
        raise HTTPException(status_code=status, detail=str(exc))


@router.get("/api/sorting-runs")
def list_runs() -> dict[str, Any]:
    return {"runs": sorting_runs.listRuns(), "lots": sorting_runs.listLots()}


@router.post("/api/sorting-runs")
def start_run(body: RunIn) -> dict[str, Any]:
    return _call(
        sorting_runs.startRun,
        body.name,
        lot_id=body.lot_id,
        adds_to_lot=body.adds_to_lot,
        note=body.note,
        started_at=body.started_at,
    )


@router.patch("/api/sorting-runs/{run_id}")
def update_run(run_id: str, body: RunPatch) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    return _call(sorting_runs.updateRun, run_id, **fields)


@router.post("/api/lots")
def create_lot(body: LotIn) -> dict[str, Any]:
    return _call(sorting_runs.createLot, body.name, body.description)


@router.patch("/api/lots/{lot_id}")
def update_lot(lot_id: str, body: LotPatch) -> dict[str, Any]:
    return _call(sorting_runs.updateLot, lot_id, **body.model_dump(exclude_unset=True))


@router.get("/api/lots/{lot_id}/parts")
def lot_parts(lot_id: str) -> dict[str, Any]:
    return _call(sorting_runs.lotParts, lot_id)
