"""Admin view of the background job queue (``app.services.job_queue``)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.user import User
from app.services import job_queue

router = APIRouter(prefix="/api/admin/jobs", tags=["jobs"])


@router.get("")
def jobs_summary(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Counts by kind and status, the worker's state, and the latest failures."""
    return job_queue.summary(db)


@router.post("/{job_id}/retry")
def retry_job(
    job_id: UUID,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
) -> dict[str, Any]:
    """Queue a failed job again, with its attempts reset."""
    try:
        job = job_queue.retry(db, job_id)
    except IntegrityError as exc:
        db.rollback()
        raise APIError(409, "The same job is already queued again.", "JOB_ALREADY_PENDING") from exc
    if job is None:
        raise APIError(404, "No failed job with that id.", "JOB_NOT_FOUND")
    return {"ok": True, "job": job_queue.serialize(job)}
