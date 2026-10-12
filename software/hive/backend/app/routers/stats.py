from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.machine import Machine
from app.models.machine_stats_cache import MachineStatsCache
from app.models.user import User

router = APIRouter(prefix="/api/stats", tags=["stats"])

_SAMPLE_COUNTS = (
    ("total_samples", MachineStatsCache.total_samples),
    ("unreviewed_samples", MachineStatsCache.unreviewed_samples),
    ("in_review_samples", MachineStatsCache.in_review_samples),
    ("accepted_samples", MachineStatsCache.accepted_samples),
    ("rejected_samples", MachineStatsCache.rejected_samples),
    ("conflict_samples", MachineStatsCache.conflict_samples),
)


@router.get("/overview")
def get_overview(
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Sample counts by review state for the dashboard.

    A sum over the per-machine rows the machine-stats worker keeps (hourly), not
    a count over the samples table: counting the unreviewed samples meant reading
    the whole 1 GB table on every dashboard load. ``computed_at`` is when the
    oldest of those rows was made."""
    # Both samples + machine counts exclude archived rigs so the dashboard reflects
    # the active fleet, not retired hardware. Admins can re-archive/un-archive via
    # the machine endpoints if a rig comes back.
    machine_query = db.query(Machine.id).filter(Machine.archived_at.is_(None))
    # Members only ever get counts over their OWN machines — otherwise the overview
    # leaks the whole corpus's size/composition to any registrant. Reviewers and
    # admins see fleet-wide totals (respecting an explicit scope=mine).
    if scope == "mine" or current_user.role not in ("admin", "reviewer"):
        machine_query = machine_query.filter(Machine.owner_id == current_user.id)

    row = (
        db.query(
            *(func.coalesce(func.sum(col), 0) for _, col in _SAMPLE_COUNTS),
            func.min(MachineStatsCache.computed_at),
        )
        .filter(MachineStatsCache.machine_id.in_(machine_query))
        .one()
    )
    out = {name: int(value) for (name, _), value in zip(_SAMPLE_COUNTS, row)}
    out["total_machines"] = machine_query.count()
    computed_at = row[-1]
    out["computed_at"] = computed_at.isoformat() if computed_at is not None else None
    return out
