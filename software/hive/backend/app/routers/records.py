"""What a user's own machines sorted, for an assistant building a profile
from the pieces that actually come through them.

Only the caller's machines, whatever their role, and only those a
machine-scoped key names.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import API_KEY_SCOPE_RECORDS_READ, get_db, require_api_key_scopes
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.user import User

router = APIRouter(prefix="/api/records", tags=["records"])

READ = Depends(require_api_key_scopes(API_KEY_SCOPE_RECORDS_READ))


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


@router.get("/machines")
def list_record_machines(db: Session = Depends(get_db), current_user: User = READ):
    """The caller's machines and how many pieces each has sorted."""
    machines = _own_machines(db, current_user).order_by(Machine.name.asc()).all()
    counts = dict(
        db.query(MachinePiece.machine_id, func.count(MachinePiece.id))
        .filter(MachinePiece.machine_id.in_([machine.id for machine in machines]))
        .group_by(MachinePiece.machine_id)
        .all()
    ) if machines else {}
    return {
        "machines": [
            {
                "id": str(machine.id),
                "name": machine.name,
                "last_seen_at": machine.last_seen_at.isoformat() if machine.last_seen_at else None,
                "piece_count": int(counts.get(machine.id, 0)),
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
    """Every part and color the machine has sorted, most pieces first: how
    many, how sure the classifier was, and which bins they went to. Part and
    color IDs are BrickLink's, as the machine reports them."""
    machine = _own_machine(db, current_user, machine_id)
    query = db.query(
        MachinePiece.part_id,
        MachinePiece.color_id,
        func.count(MachinePiece.id),
        func.max(MachinePiece.part_name),
        func.max(MachinePiece.color_name),
        func.avg(MachinePiece.confidence),
        func.max(MachinePiece.recorded_at),
    ).filter(MachinePiece.machine_id == machine.id, MachinePiece.part_id.is_not(None))
    since = _since(since_days)
    if since is not None:
        query = query.filter(MachinePiece.recorded_at >= since)
    rows = (
        query.group_by(MachinePiece.part_id, MachinePiece.color_id)
        .order_by(func.count(MachinePiece.id).desc())
        .limit(limit)
        .all()
    )
    totals = db.query(func.count(MachinePiece.id)).filter(MachinePiece.machine_id == machine.id)
    if since is not None:
        totals = totals.filter(MachinePiece.recorded_at >= since)
    return {
        "machine": {"id": str(machine.id), "name": machine.name},
        "since": since.isoformat() if since else None,
        "total_pieces": int(totals.scalar() or 0),
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
    next_cursor back as cursor for the next page."""
    machine = _own_machine(db, current_user, machine_id)
    query = db.query(MachinePiece).filter(MachinePiece.machine_id == machine.id)
    since = _since(since_days)
    if since is not None:
        query = query.filter(MachinePiece.recorded_at >= since)
    if cursor is not None:
        query = query.filter(MachinePiece.local_id < cursor)
    pieces = query.order_by(MachinePiece.local_id.desc()).limit(limit + 1).all()
    has_more = len(pieces) > limit
    pieces = pieces[:limit]
    return {
        "machine": {"id": str(machine.id), "name": machine.name},
        "items": [_piece(piece) for piece in pieces],
        "next_cursor": pieces[-1].local_id if has_more and pieces else None,
    }


def _piece(piece: MachinePiece) -> dict[str, Any]:
    return {
        "piece_uuid": piece.piece_uuid,
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
        "color_corrected_id": piece.color_corrected_id,
    }
