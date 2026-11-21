from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import lot_summary
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


class NowIn(BaseModel):
    # None: sorting without a lot.
    lot_id: Optional[str] = None
    # False: the lot's pieces are being put through again, not counted again.
    adds_to_lot: bool = True


class BinIn(BaseModel):
    layer_index: int = Field(ge=0)
    section_index: int = Field(ge=0)
    bin_index: int = Field(ge=0)


class SendBackIn(BaseModel):
    bins: list[BinIn] = Field(min_length=1)
    # Why, e.g. "emptied into the hopper to be sorted again".
    note: Optional[str] = None


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


@router.get("/api/sorting-runs/now")
def sorting_now() -> dict[str, Any]:
    return sorting_runs.sortingNow()


@router.post("/api/sorting-runs/now")
def set_sorting_now(body: NowIn) -> dict[str, Any]:
    """What is being sorted from now on: a lot (adding to it, or putting its
    pieces through again) or none. Answers as GET does, so the menu redraws."""
    _call(sorting_runs.setNow, body.lot_id, body.adds_to_lot)
    return sorting_runs.sortingNow()


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


@router.get("/api/lots/{lot_id}/summary")
def lot_summary_route(lot_id: str) -> dict[str, Any]:
    return _call(lot_summary.lotSummary, lot_id)


@router.post("/api/lots/{lot_id}/send-back")
def send_back(lot_id: str, body: SendBackIn) -> dict[str, Any]:
    """The lot's pieces in these bins went back in the hopper to be sorted
    again (sorting_runs.sendBack)."""
    bins = [(b.layer_index, b.section_index, b.bin_index) for b in body.bins]
    answer = _call(sorting_runs.sendBack, lot_id, bins, body.note)
    lot_summary.forget()
    return answer
