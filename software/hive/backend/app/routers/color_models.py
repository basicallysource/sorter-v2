"""Admin management of color-classifier models.

Models are uploaded to COLOR_MODEL_DIR out of band (scp/manual). This router
reconciles the DB registry to what's on disk and lets an admin pick the single
globally-active model whose prediction the piece-labeling view serves.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db, require_role, statement_timeout, verify_csrf
from app.errors import APIError
from app.models.color_model import ColorModel
from app.models.machine import Machine
from app.models.user import User
from app.services import color_model_runs, color_predictor

router = APIRouter(prefix="/api/color-models", tags=["color-models"])


def _serialize(row: ColorModel) -> dict:
    return {
        "id": str(row.id),
        "filename": row.filename,
        "name": row.name,
        "description": row.description,
        "kind": row.kind,
        "sha256": row.sha256,
        "class_count": row.class_count,
        "input_size": row.input_size,
        "file_size": row.file_size,
        "is_active": bool(row.is_active),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def list_color_models(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
) -> dict:
    """Reconcile the registry to the models on disk, then list them. The scan
    picks up newly-uploaded files and drops rows whose files were removed."""
    rows = color_predictor.reconcile(db)
    return {
        "models": [_serialize(r) for r in rows],
        "model_dir": str(color_predictor.model_dir()),
    }


@router.post("/{model_id}/activate")
def activate_color_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """Make this the single globally-active model. Clears any prior active one."""
    row = color_predictor.set_active(db, model_id, True)
    if row is None:
        raise APIError(404, "Color model not found", "COLOR_MODEL_NOT_FOUND")
    return {"ok": True, "model": _serialize(row)}


@router.post("/{model_id}/deactivate")
def deactivate_color_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """Turn this model off. With none active, the labeling view falls back to the
    pixel-average suggestion."""
    row = color_predictor.set_active(db, model_id, False)
    if row is None:
        raise APIError(404, "Color model not found", "COLOR_MODEL_NOT_FOUND")
    return {"ok": True, "model": _serialize(row)}


class ColorModelBackfillRequest(BaseModel):
    machine_id: UUID
    # Sha256s of the models to run; every registered model when left out.
    models: list[str] | None = None
    with_palette: bool = False
    with_candidates: bool = False
    rerun: bool = False
    limit: int = Field(default=color_model_runs.BACKFILL_MAX, ge=1, le=color_model_runs.BACKFILL_MAX)


@router.post("/backfill")
# Selects up to BACKFILL_MAX of one machine's queued pieces and queues batches of them per model.
@statement_timeout(seconds=60)
def backfill_color_models(
    payload: ColorModelBackfillRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """Run every colour model (or the ones named) over one machine's labelable
    pieces, or the ones with the colour reference palette near them or with
    same-piece candidates, as color_model_run jobs behind the live work. The
    registry is reconciled with the model folder first, so a newly copied
    model is included."""
    if db.get(Machine, payload.machine_id) is None:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
    color_predictor.reconcile(db)
    try:
        return color_model_runs.backfill(
            db,
            machine_id=payload.machine_id,
            model_sha256s=payload.models,
            with_palette=payload.with_palette,
            with_candidates=payload.with_candidates,
            rerun=payload.rerun,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise APIError(400, str(exc), "UNKNOWN_COLOR_MODEL") from exc
