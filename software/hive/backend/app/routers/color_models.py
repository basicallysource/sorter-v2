"""Admin management of color-classifier models.

Models are uploaded to COLOR_MODEL_DIR out of band (scp/manual). This router
reconciles the DB registry to what's on disk and lets an admin pick the single
globally-active model whose prediction the piece-labeling view serves.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.color_model import ColorModel
from app.models.user import User
from app.services import color_predictor

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
