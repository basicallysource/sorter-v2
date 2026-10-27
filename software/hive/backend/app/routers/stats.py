from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.user import User
from app.services.review_queue import sample_counts

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
def get_overview(
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    machine_id: list[UUID] | None = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sample counts by review state for the dashboard and the Channel samples
    header, over the active (not archived) machines the caller may see, or the
    ones named by machine_id (one or several). Members only ever get their own
    machines; reviewers and admins the fleet unless scope=mine.

    A sum over the per-machine rows the stats worker keeps (hourly), not a
    count over the samples table: counting the unreviewed samples meant reading
    the whole table on every load. ``computed_at`` is when the oldest of those
    rows was made."""
    counts = sample_counts(db, current_user, mine_only=scope == "mine", machine_ids=machine_id)
    return {
        key: counts[key]
        for key in (
            "total_samples",
            "unreviewed_samples",
            "in_review_samples",
            "accepted_samples",
            "rejected_samples",
            "conflict_samples",
            "total_machines",
            "computed_at",
        )
    }
