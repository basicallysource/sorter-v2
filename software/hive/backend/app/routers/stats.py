from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.machine import Machine
from app.models.sample import Sample
from app.models.user import User

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
def get_overview(
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Both samples + machine counts exclude archived rigs so the dashboard reflects
    # the active fleet, not retired hardware. Admins can re-archive/un-archive via
    # the machine endpoints if a rig comes back.
    machine_query = db.query(Machine).filter(Machine.archived_at.is_(None))
    if scope == "mine":
        machine_query = machine_query.filter(Machine.owner_id == current_user.id)
    sample_query = db.query(Sample).filter(Sample.machine_id.in_(machine_query.with_entities(Machine.id)))

    total = sample_query.count()
    unreviewed = sample_query.filter(Sample.review_status == "unreviewed").count()
    in_review = sample_query.filter(Sample.review_status == "in_review").count()
    accepted = sample_query.filter(Sample.review_status == "accepted").count()
    rejected = sample_query.filter(Sample.review_status == "rejected").count()
    conflict = sample_query.filter(Sample.review_status == "conflict").count()
    total_machines = machine_query.count()

    return {
        "total_samples": total,
        "unreviewed_samples": unreviewed,
        "in_review_samples": in_review,
        "accepted_samples": accepted,
        "rejected_samples": rejected,
        "conflict_samples": conflict,
        "total_machines": total_machines,
    }
