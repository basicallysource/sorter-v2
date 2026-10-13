from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import hive_metadata_cache
import training_runs

router = APIRouter()


class BinIn(BaseModel):
    layer: int
    section: int
    bin: int


class ConfigIn(BaseModel):
    enabled: Optional[bool] = None
    mode: Optional[str] = None
    color_ids: Optional[list[str]] = None
    # Leave out to keep it; null to route by the sorting profile again.
    bin: Optional[BinIn] = None


class ExcludedIn(BaseModel):
    excluded: bool


def _palette() -> dict[str, dict[str, Any]]:
    return {str(c.get("id")): c for c in hive_metadata_cache.get_cached_palette() or []}


def _colors(color_ids: list[str], palette: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": color_id,
            "name": palette.get(color_id, {}).get("name"),
            "rgb": palette.get(color_id, {}).get("rgb"),
        }
        for color_id in color_ids
    ]


def _withColors(item: dict[str, Any], palette: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out = {**item, "colors": _colors(item["color_ids"], palette)}
    if "segments" in item:
        out["segments"] = [_withColors(segment, palette) for segment in item["segments"]]
    return out


def _pieceOut(piece: dict[str, Any], palette: dict[str, dict[str, Any]]) -> dict[str, Any]:
    label = piece.get("training_color_id")
    return {**piece, "training_color_name": palette.get(str(label), {}).get("name") if label else None}


def _overview() -> dict[str, Any]:
    palette = _palette()
    current = training_runs.openRun()
    return {
        "config": _withColors(training_runs.getConfig(), palette),
        "current_run": _withColors(current, palette) if current else None,
        "runs": [_withColors(run, palette) for run in training_runs.listRuns()],
    }


@router.get("/api/training")
def get_training() -> dict[str, Any]:
    return _overview()


@router.post("/api/training/config")
def set_training_config(body: ConfigIn) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if "bin" in body.model_fields_set:
        extra["bin"] = body.bin.model_dump() if body.bin is not None else None
    try:
        training_runs.setConfig(enabled=body.enabled, mode=body.mode, color_ids=body.color_ids, **extra)
    except training_runs.TrainingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    return _overview()


@router.post("/api/training/runs")
def start_training_run() -> dict[str, Any]:
    try:
        training_runs.startRun()
    except training_runs.TrainingError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message)
    return _overview()


@router.post("/api/training/runs/{run_id}/end")
def end_training_run(run_id: str) -> dict[str, Any]:
    if training_runs.endRun(run_id) is None:
        raise HTTPException(status_code=404, detail="No such training run")
    return _overview()


@router.get("/api/training/runs/{run_id}")
def get_training_run(
    run_id: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    filter: str = Query("all"),
) -> dict[str, Any]:
    if filter not in training_runs.FILTERS:
        raise HTTPException(status_code=400, detail=f"Unknown filter: {filter}")
    run = training_runs.getRun(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="No such training run")
    palette = _palette()
    pieces, total = training_runs.listRunPieces(run_id, limit=limit, offset=offset, filter_name=filter)
    return {
        "run": _withColors(run, palette),
        "pieces": [_pieceOut(p, palette) for p in pieces],
        "total": total,
    }


@router.patch("/api/training/runs/{run_id}")
def set_training_run_excluded(run_id: str, body: ExcludedIn) -> dict[str, Any]:
    run = training_runs.setRunExcluded(run_id, body.excluded)
    if run is None:
        raise HTTPException(status_code=404, detail="No such training run")
    return _withColors(run, _palette())


@router.post("/api/training/pieces/{piece_uuid}")
def set_training_piece_excluded(piece_uuid: str, body: ExcludedIn) -> dict[str, Any]:
    piece = training_runs.setPieceExcluded(piece_uuid, body.excluded)
    if piece is None:
        raise HTTPException(status_code=404, detail="That piece is in no training run")
    return _pieceOut(piece, _palette())
