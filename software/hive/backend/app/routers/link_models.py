"""Admin management of piece_link matcher models.

Each model is a pair of ONNX graphs (encoder + head) uploaded to LINK_MODEL_DIR
out of band (scp/manual), grouped by their baked ``hive.name``. This router
reconciles the DB registry to what's on disk and lets an admin pick the single
globally-active model whose scores drive the same-piece pre-selection in the
color-labeling view (in place of the time/angle heuristic).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.link_model import LinkModel
from app.models.user import User
from app.services import link_predictor

router = APIRouter(prefix="/api/link-models", tags=["link-models"])


def _serialize(row: LinkModel) -> dict:
    return {
        "id": str(row.id),
        "name": row.name,
        "description": row.description,
        "kind": row.kind,
        "encoder_filename": row.encoder_filename,
        "head_filename": row.head_filename,
        "sha256": row.sha256,
        "input_size": row.input_size,
        "embed_dim": row.embed_dim,
        "meta_dim": row.meta_dim,
        "file_size": row.file_size,
        "is_active": bool(row.is_active),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def list_link_models(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
) -> dict:
    """Reconcile the registry to the encoder+head pairs on disk, then list them."""
    rows = link_predictor.reconcile(db)
    return {
        "models": [_serialize(r) for r in rows],
        "model_dir": str(link_predictor.model_dir()),
    }


@router.post("/{model_id}/activate")
def activate_link_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """Make this the single globally-active model. Clears any prior active one."""
    row = link_predictor.set_active(db, model_id, True)
    if row is None:
        raise APIError(404, "Link model not found", "LINK_MODEL_NOT_FOUND")
    return {"ok": True, "model": _serialize(row)}


@router.post("/{model_id}/deactivate")
def deactivate_link_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict:
    """Turn this model off. With none active, the labeling view falls back to the
    time/angle heuristic's pre-selection."""
    row = link_predictor.set_active(db, model_id, False)
    if row is None:
        raise APIError(404, "Link model not found", "LINK_MODEL_NOT_FOUND")
    return {"ok": True, "model": _serialize(row)}
