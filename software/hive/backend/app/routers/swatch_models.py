"""Colour-reference palette finders: the admin registry, the backfill, and a
sample's readings.

Models are uploaded to SWATCH_MODEL_DIR out of band. Listing reconciles the
registry to what is on disk; an admin activates one. While one is active,
every new classification-camera sample is queued for a ``swatch_find`` job,
and the backfill queues existing ones.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import API_KEY_SCOPE_SAMPLES_READ, get_db, require_api_key_scopes, require_role, verify_csrf
from app.errors import APIError
from app.models.machine import Machine
from app.models.sample import Sample
from app.models.swatch_model import SwatchModel
from app.models.user import User
from app.services import swatch_jobs, swatch_models
from app.services.access_window import sample_access_visible

router = APIRouter(prefix="/api/swatch-models", tags=["swatch-models"])
sample_router = APIRouter(prefix="/api/samples", tags=["samples"])


def _serialize(row: SwatchModel) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "filename": row.filename,
        "name": row.name,
        "description": row.description,
        "kind": row.kind,
        "sha256": row.sha256,
        "colour_count": row.colour_count,
        "net_long_side": row.net_long_side,
        "file_size": row.file_size,
        "is_active": bool(row.is_active),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def list_swatch_models(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Reconcile the registry to the models on disk, then list them."""
    rows = swatch_models.reconcile(db)
    return {
        "models": [_serialize(r) for r in rows],
        "model_dir": str(swatch_models.model_dir()),
        "source_roles": list(settings.SWATCH_FIND_SOURCE_ROLES),
    }


@router.post("/{model_id}/activate")
def activate_swatch_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict[str, Any]:
    """Make this the one active model: new classification-camera samples are
    read with it from now on. Clears any other."""
    row = swatch_models.set_active(db, model_id, True)
    if row is None:
        raise APIError(404, "Swatch model not found", "SWATCH_MODEL_NOT_FOUND")
    return {"ok": True, "model": _serialize(row)}


@router.post("/{model_id}/deactivate")
def deactivate_swatch_model(
    model_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict[str, Any]:
    """Turn this model off. With none active, no swatch_find jobs are queued,
    and queued ones finish without reading anything."""
    row = swatch_models.set_active(db, model_id, False)
    if row is None:
        raise APIError(404, "Swatch model not found", "SWATCH_MODEL_NOT_FOUND")
    return {"ok": True, "model": _serialize(row)}


class SwatchBackfillRequest(BaseModel):
    machine_id: UUID
    # Capture time (upload time where a sample has none), [since, until).
    since: datetime | None = None
    until: datetime | None = None
    # Defaults to SWATCH_FIND_SOURCE_ROLES.
    source_roles: list[str] | None = None
    # Read again samples the active model has already read.
    rerun: bool = False
    limit: int = Field(default=swatch_jobs.BACKFILL_MAX, ge=1, le=swatch_jobs.BACKFILL_MAX)


@router.post("/backfill")
def backfill_swatches(
    payload: SwatchBackfillRequest,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict[str, Any]:
    """Queue swatch_find for one machine's existing classification-camera
    samples in a time range, newest first, behind the live ones."""
    if db.get(Machine, payload.machine_id) is None:
        raise APIError(404, "Machine not found", "MACHINE_NOT_FOUND")
    if payload.since and payload.until and payload.since >= payload.until:
        raise APIError(400, "The start of the range must come before its end.", "INVALID_RANGE")
    if not swatch_models.has_active(db):
        raise APIError(409, "No swatch model is active: activate one first.", "NO_ACTIVE_SWATCH_MODEL")
    return swatch_jobs.backfill(
        db,
        machine_id=payload.machine_id,
        since=payload.since,
        until=payload.until,
        source_roles=payload.source_roles,
        rerun=payload.rerun,
        limit=payload.limit,
    )


@sample_router.get("/{sample_id}/swatch-runs")
def get_sample_swatch_runs(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
) -> dict[str, Any]:
    """Every swatch finder run on this sample, newest first, with its tiles."""
    sample = db.get(Sample, sample_id)
    if sample is None or not sample_access_visible(db, current_user, sample):
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")
    return {"runs": [swatch_jobs.serialize_run(run) for run in swatch_jobs.runs_for_sample(db, sample_id)]}
