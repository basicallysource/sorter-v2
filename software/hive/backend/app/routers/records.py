"""What a user's own machines sorted, for an assistant building a profile
from the pieces that actually come through them.

Only the caller's machines, whatever their role, and only those a
machine-scoped key names.

No call reads a machine's whole history: piece counts come from the stats
worker's cache, the parts summary is of the machine's newest PARTS_WINDOW
pieces at most, and a page of pieces looks at PIECES_WINDOW pieces at most.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, true
from sqlalchemy.orm import Session

from app.deps import API_KEY_SCOPE_RECORDS_READ, get_db, require_api_key_scopes
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.user import User
from app.services import machine_stats

router = APIRouter(prefix="/api/records", tags=["records"])

READ = Depends(require_api_key_scopes(API_KEY_SCOPE_RECORDS_READ))

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
    return {
        "machine": {"id": str(machine.id), "name": machine.name},
        "items": [_piece(piece) for piece in pieces],
        "next_cursor": next_cursor,
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
