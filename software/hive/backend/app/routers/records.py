"""What a user's own machines sorted, for an assistant building a profile
from the pieces that actually come through them, or a tool that keeps a
catalog of what was sorted: each piece with every colour people and later
model runs gave it, and the machine's lots and sorting runs.

Only the caller's machines, whatever their role, and only those a
machine-scoped key names. An admin can also add a later model run's
predictions for a machine's pieces (``predictions:write``), as a machine's
own import does.

No call reads a machine's whole history: piece counts come from the stats
worker's cache, the parts summary is of the machine's newest PARTS_WINDOW
pieces at most, and a page of pieces looks at PIECES_WINDOW pieces at most.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, true
from sqlalchemy.orm import Session

from app.deps import (
    API_KEY_SCOPE_PREDICTIONS_WRITE,
    API_KEY_SCOPE_RECORDS_READ,
    get_db,
    require_api_key_scopes,
)
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_prediction import SOURCE_LIVE, MachinePiecePrediction
from app.models.machine_sorting_run import MachineLot, MachineSortingRun
from app.models.piece_color_label import PieceColorLabel
from app.models.piece_model_output import PieceModelColor
from app.models.user import User
from app.services import color_model_runs, machine_stats

router = APIRouter(prefix="/api/records", tags=["records"])

READ = Depends(require_api_key_scopes(API_KEY_SCOPE_RECORDS_READ))
WRITE_PREDICTIONS = Depends(require_api_key_scopes(API_KEY_SCOPE_PREDICTIONS_WRITE))

# The newest pieces the parts summary reads, at most: plenty to see what a
# machine sorts, and what one call may cost.
PARTS_WINDOW = 20_000
# The most pieces one page of the pieces list looks at to find its rows.
PIECES_WINDOW = 5_000


def _own_machines(db: Session, user: User):
    query = db.query(Machine).filter(Machine.owner_id == user.id)
    allowed = getattr(user, "_api_key_machine_ids", None)
    if allowed is not None:
        query = query.filter(Machine.id.in_([UUID(machine_id) for machine_id in allowed]))
    return query


def _own_machine(db: Session, user: User, machine_id: UUID) -> Machine:
    machine = _own_machines(db, user).filter(Machine.id == machine_id).first()
    if machine is None:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
    return machine


def _since(days: float | None):
    return datetime.now(timezone.utc) - timedelta(days=days) if days else None


def _on_or_after(moment: datetime | None, since: datetime) -> bool:
    if moment is None:
        return False
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)) >= since


@router.get("/machines")
def list_record_machines(db: Session = Depends(get_db), current_user: User = READ):
    """The caller's machines and how many pieces each has sorted."""
    machines = _own_machines(db, current_user).order_by(Machine.name.asc()).all()
    return {
        "machines": [
            {
                "id": str(machine.id),
                "name": machine.name,
                "last_seen_at": machine.last_seen_at.isoformat() if machine.last_seen_at else None,
                "piece_count": machine_stats.piece_total(db, machine.id),
            }
            for machine in machines
        ]
    }


@router.get("/machines/{machine_id}/parts")
def machine_parts_seen(
    machine_id: UUID,
    since_days: float | None = Query(default=None, gt=0, le=3650),
    limit: int = Query(default=200, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """The parts and colors the machine sorted, most pieces first: how many,
    how sure the classifier was, and when it last saw each. Part and color IDs
    are BrickLink's, as the machine reports them.

    Read from the machine's newest pieces, PARTS_WINDOW at most (recorded
    since ``since_days`` if given): ``pieces_examined`` says how many, and
    ``capped`` is true when older pieces in the range were left out.
    ``total_pieces`` is every piece the machine has synced (no ``since_days``),
    or the pieces examined in the range."""
    machine = _own_machine(db, current_user, machine_id)
    newest = (
        db.query(
            MachinePiece.part_id,
            MachinePiece.part_name,
            MachinePiece.color_id,
            MachinePiece.color_name,
            MachinePiece.confidence,
            MachinePiece.recorded_at,
        )
        .filter(MachinePiece.machine_id == machine.id)
        .order_by(MachinePiece.local_id.desc())
        .limit(PARTS_WINDOW)
        .subquery()
    )
    since = _since(since_days)
    in_range = newest.c.recorded_at >= since if since is not None else true()
    read, examined, oldest = db.query(
        func.count(), func.count().filter(in_range), func.min(newest.c.recorded_at).filter(in_range)
    ).one()
    rows = (
        db.query(
            newest.c.part_id,
            newest.c.color_id,
            func.count(),
            func.max(newest.c.part_name),
            func.max(newest.c.color_name),
            func.avg(newest.c.confidence),
            func.max(newest.c.recorded_at),
        )
        .filter(newest.c.part_id.is_not(None), in_range)
        .group_by(newest.c.part_id, newest.c.color_id)
        .order_by(func.count().desc())
        .limit(limit)
        .all()
    )
    return {
        "machine": {"id": str(machine.id), "name": machine.name},
        "since": since.isoformat() if since else None,
        "total_pieces": machine_stats.piece_total(db, machine.id) if since is None else int(examined or 0),
        "pieces_examined": int(examined or 0),
        "capped": bool(read >= PARTS_WINDOW and (since is None or _on_or_after(oldest, since))),
        "parts": [
            {
                "part_id": part_id,
                "part_name": part_name,
                "color_id": color_id,
                "color_name": color_name,
                "count": int(count),
                "avg_confidence": round(float(confidence), 3) if confidence is not None else None,
                "last_seen_at": last_seen.isoformat() if last_seen else None,
            }
            for part_id, color_id, count, part_name, color_name, confidence, last_seen in rows
        ],
    }


@router.get("/machines/{machine_id}/pieces")
def machine_pieces(
    machine_id: UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    cursor: int | None = Query(default=None),
    since_days: float | None = Query(default=None, gt=0, le=3650),
    db: Session = Depends(get_db),
    current_user: User = READ,
):
    """Each piece the machine sorted, newest first, a page at a time: pass
    next_cursor back as cursor for the next page, until it is null.

    With ``since_days`` a page looks at PIECES_WINDOW pieces at most, so it can
    come back short with a next_cursor; the list ends at the first stretch
    recorded before the range."""
    machine = _own_machine(db, current_user, machine_id)
    query = db.query(MachinePiece).filter(MachinePiece.machine_id == machine.id)
    if cursor is not None:
        query = query.filter(MachinePiece.local_id < cursor)
    since = _since(since_days)
    end = None
    if since is not None:
        # The last piece of this stretch, from the (machine_id, local_id) index.
        end = (
            query.with_entities(MachinePiece.local_id, MachinePiece.recorded_at)
            .order_by(MachinePiece.local_id.desc())
            .offset(PIECES_WINDOW - 1)
            .limit(1)
            .first()
        )
        if end is not None:
            query = query.filter(MachinePiece.local_id >= end.local_id)
        query = query.filter(MachinePiece.recorded_at >= since)
    pieces = query.order_by(MachinePiece.local_id.desc()).limit(limit + 1).all()
    if len(pieces) > limit:
        pieces = pieces[:limit]
        next_cursor = pieces[-1].local_id
    elif end is not None and _on_or_after(end.recorded_at, since):
        next_cursor = end.local_id
    else:
        next_cursor = None
    labels, predictions = _colors(db, machine, [piece.piece_uuid for piece in pieces])
    return {
        "machine": {"id": str(machine.id), "name": machine.name},
        "items": [
            _piece(piece, labels.get(piece.piece_uuid, []), predictions.get(piece.piece_uuid, [])) for piece in pieces
        ],
        "next_cursor": next_cursor,
    }


def _iso(moment: datetime | None) -> str | None:
    """A stored time as ISO 8601 in UTC (SQLite hands them back naive)."""
    if moment is None:
        return None
    return (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)).isoformat()


def _colors(
    db: Session, machine: Machine, piece_uuids: list[str]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    """For a page of a machine's pieces: the colour each was labelled on Hive
    (by whom only as whether it was the machine's owner), and the top colour of
    every later model run over its images: those imported or synced from the
    machine (any source but the live classification), and the active colour
    model's answer on Hive (source "hive"). Newest last."""
    labels: dict[str, list[dict[str, Any]]] = defaultdict(list)
    predictions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not piece_uuids:
        return labels, predictions
    for row in (
        db.query(
            PieceColorLabel.piece_uuid,
            PieceColorLabel.labeler_id,
            PieceColorLabel.color_id,
            PieceColorLabel.cant_tell,
            PieceColorLabel.updated_at,
        )
        .filter(PieceColorLabel.machine_id == machine.id, PieceColorLabel.piece_uuid.in_(piece_uuids))
        .order_by(PieceColorLabel.updated_at)
    ):
        labels[row.piece_uuid].append(
            {
                "color_id": str(row.color_id) if row.color_id is not None else None,
                "cant_tell": bool(row.cant_tell),
                "by_owner": row.labeler_id == machine.owner_id,
                "at": _iso(row.updated_at),
            }
        )
    for row in (
        db.query(
            MachinePiecePrediction.piece_uuid,
            MachinePiecePrediction.source,
            MachinePiecePrediction.model_name,
            MachinePiecePrediction.model,
            MachinePiecePrediction.value_id,
            MachinePiecePrediction.value_name,
            MachinePiecePrediction.score,
            MachinePiecePrediction.predicted_at,
            MachinePiecePrediction.created_at,
        )
        # As ix_machine_piece_predictions_later_colors is defined.
        .filter(
            MachinePiecePrediction.machine_id == machine.id,
            MachinePiecePrediction.piece_uuid.in_(piece_uuids),
            MachinePiecePrediction.source != SOURCE_LIVE,
            MachinePiecePrediction.kind == "color",
            MachinePiecePrediction.rank == 0,
        )
    ):
        predictions[row.piece_uuid].append(
            {
                "source": row.source,
                "model_name": row.model_name,
                "model_sha256": row.model,
                "color_id": row.value_id,
                "color_name": row.value_name,
                "score": row.score,
                "made_at": _iso(row.predicted_at or row.created_at),
            }
        )
    active = color_model_runs.active_sha256(db)
    if active:
        palette = None
        for row in db.query(
            PieceModelColor.piece_uuid,
            PieceModelColor.model_name,
            PieceModelColor.color_id,
            PieceModelColor.confidence,
            PieceModelColor.created_at,
        ).filter(
            PieceModelColor.machine_id == machine.id,
            PieceModelColor.piece_uuid.in_(piece_uuids),
            PieceModelColor.model_sha256 == active,
        ):
            if palette is None:
                palette = color_model_runs._palette()
            predictions[row.piece_uuid].append(
                {
                    "source": "hive",
                    "model_name": row.model_name,
                    "model_sha256": active,
                    "color_id": str(row.color_id),
                    "color_name": (palette.get(row.color_id) or {}).get("name"),
                    "score": float(row.confidence),
                    "made_at": _iso(row.created_at),
                }
            )
    for answers in predictions.values():
        answers.sort(key=lambda a: a["made_at"] or "")
    return labels, predictions


def _piece(
    piece: MachinePiece,
    color_labels: list[dict[str, Any]] | None = None,
    color_predictions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "piece_uuid": piece.piece_uuid,
        "local_id": piece.local_id,
        "seen_at": _iso(piece.seen_at),
        "dead": bool(piece.dead),
        "recorded_at": piece.recorded_at.isoformat() if piece.recorded_at else None,
        "part_id": piece.part_id,
        "part_name": piece.part_name,
        "color_id": piece.color_id,
        "color_name": piece.color_name,
        "confidence": piece.confidence,
        "color_confidence": piece.color_confidence,
        "category_id": piece.category_id,
        "bin": {"layer": piece.bin_x, "section": piece.bin_y, "bin": piece.bin_z} if piece.bin_x is not None else None,
        "classification_status": piece.classification_status,
        "part_correct": piece.part_correct,
        # The machine operator's colour verdict, and when they gave it.
        "color_corrected_id": piece.color_corrected_id,
        "correction_updated_at": _iso(piece.correction_updated_at),
        "color_labels": color_labels or [],
        "color_predictions": color_predictions or [],
    }


@router.get("/machines/{machine_id}/sorting-runs")
def machine_sorting_runs(machine_id: UUID, db: Session = Depends(get_db), current_user: User = READ):
    """The machine's lots and sorting runs, as it keeps them. A run lasts from
    started_at until the next run starts (ends_at; null for the newest), and a
    piece belongs to the run whose stretch holds its seen_at. A lot's pieces
    are those of its runs that add to it; a run naming the lot that does not
    add to it is another pass over pieces the lot already counted."""
    machine = _own_machine(db, current_user, machine_id)
    lots = db.query(MachineLot).filter(MachineLot.machine_id == machine.id).order_by(MachineLot.created_at).all()
    runs = (
        db.query(MachineSortingRun)
        .filter(MachineSortingRun.machine_id == machine.id)
        .order_by(MachineSortingRun.started_at)
        .all()
    )
    return {
        "machine": {"id": str(machine.id), "name": machine.name},
        "lots": [
            {"id": lot.lot_id, "name": lot.name, "description": lot.description, "created_at": _iso(lot.created_at)}
            for lot in lots
        ],
        "runs": [
            {
                "id": run.run_id,
                "name": run.name,
                "note": run.note,
                "lot_id": run.lot_id,
                "adds_to_lot": bool(run.adds_to_lot),
                "started_at": _iso(run.started_at),
                "ends_at": _iso(runs[i + 1].started_at) if i + 1 < len(runs) else None,
                "created_at": _iso(run.created_at),
            }
            for i, run in enumerate(runs)
        ],
    }


# Pieces one import may carry.
IMPORT_MAX_PIECES = 1000


def _palette_name(palette: dict[int, dict[str, Any]], value_id: str) -> str | None:
    try:
        return (palette.get(int(value_id)) or {}).get("name")
    except ValueError:
        return None


class PredictionAnswerIn(BaseModel):
    value_id: str = Field(min_length=1, max_length=64)
    value_name: str | None = Field(default=None, max_length=200)
    score: float | None = None


class PredictionPieceIn(BaseModel):
    piece_uuid: str = Field(min_length=1, max_length=64)
    # Best first.
    answers: list[PredictionAnswerIn] = Field(min_length=1, max_length=10)
    # The piece's burst crops (seq) the model read.
    image_seqs: list[int] | None = Field(default=None, max_length=64)


class PredictionImportIn(BaseModel):
    # What the run is called wherever its answers show (e.g. "colorpred-v6
    # rerun, 15 Oct"); not "live", the machine's own classification.
    source: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=64)
    model_name: str = Field(min_length=1, max_length=120)
    # The model's sha256.
    model_sha: str | None = Field(default=None, max_length=128)
    kind: Literal["part", "color"]
    # When the run was made (unix seconds); now when left out.
    made_at: float | None = None
    pieces: list[PredictionPieceIn] = Field(min_length=1, max_length=IMPORT_MAX_PIECES)


@router.post("/machines/{machine_id}/predictions")
def import_predictions(
    machine_id: UUID,
    payload: PredictionImportIn,
    db: Session = Depends(get_db),
    current_user: User = WRITE_PREDICTIONS,
):
    """Keep a later run's predictions for some of the machine's pieces: one
    model over their stored images, as the machine's own POST
    /api/predictions/import keeps them, for pieces the machine may no longer
    keep. Admins only. Idempotent per (piece, source, model name): a piece
    that already has this run's answers keeps them. Pieces Hive has no record
    of come back as unknown."""
    if current_user.role != "admin":
        raise APIError(403, "Only an admin can add predictions", "ADMIN_ONLY")
    if payload.source == SOURCE_LIVE:
        raise APIError(400, f"The source {SOURCE_LIVE!r} is the machine's own classification", "SOURCE_RESERVED")
    machine = _own_machine(db, current_user, machine_id)
    wanted = list(dict.fromkeys(piece.piece_uuid for piece in payload.pieces))
    known = {
        puid
        for (puid,) in db.query(MachinePiece.piece_uuid).filter(
            MachinePiece.machine_id == machine.id, MachinePiece.piece_uuid.in_(wanted)
        )
    }
    had = {
        puid
        for (puid,) in db.query(MachinePiecePrediction.piece_uuid)
        .filter(
            MachinePiecePrediction.machine_id == machine.id,
            MachinePiecePrediction.piece_uuid.in_(wanted),
            MachinePiecePrediction.source == payload.source,
            MachinePiecePrediction.request == payload.model_name,
            MachinePiecePrediction.kind == payload.kind,
            MachinePiecePrediction.rank == 0,
        )
    }
    now = datetime.now(timezone.utc)
    made_at = datetime.fromtimestamp(payload.made_at, timezone.utc) if payload.made_at is not None else now
    # A colour the run left unnamed takes its BrickLink name.
    palette = (
        color_model_runs._palette()
        if payload.kind == "color" and any(a.value_name is None for piece in payload.pieces for a in piece.answers)
        else {}
    )
    added: list[str] = []
    already: list[str] = []
    unknown: list[str] = []
    done: set[str] = set()
    for piece in payload.pieces:
        puid = piece.piece_uuid
        if puid in done:
            continue
        done.add(puid)
        if puid not in known:
            unknown.append(puid)
            continue
        if puid in had:
            already.append(puid)
            continue
        images = [{"set": "burst", "seq": seq, "channel": None} for seq in piece.image_seqs or []]
        for rank, answer in enumerate(piece.answers):
            db.add(
                MachinePiecePrediction(
                    id=uuid4(),
                    machine_id=machine.id,
                    piece_uuid=puid,
                    local_id=0,
                    source=payload.source,
                    request=payload.model_name,
                    provider=payload.provider,
                    model=payload.model_sha,
                    model_name=payload.model_name,
                    images=images or None,
                    kind=payload.kind,
                    rank=rank,
                    value_id=answer.value_id,
                    value_name=answer.value_name or _palette_name(palette, answer.value_id),
                    score=answer.score if answer.score is None or math.isfinite(answer.score) else None,
                    applied=False,
                    predicted_at=made_at,
                    created_at=now,
                )
            )
        added.append(puid)
    db.commit()
    return {"added": len(added), "already": len(already), "unknown": unknown}
