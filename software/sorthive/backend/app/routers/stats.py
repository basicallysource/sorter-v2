from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.machine import Machine
from app.models.sample import Sample
from app.models.user import User

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/overview")
def get_overview(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_samples = db.query(Sample).filter(Sample.machine_id.in_(
        db.query(Machine.id).filter(Machine.owner_id == current_user.id)
    ))
    total = user_samples.count()
    unreviewed = user_samples.filter(Sample.review_status == "unreviewed").count()
    in_review = user_samples.filter(Sample.review_status == "in_review").count()
    accepted = user_samples.filter(Sample.review_status == "accepted").count()
    rejected = user_samples.filter(Sample.review_status == "rejected").count()
    conflict = user_samples.filter(Sample.review_status == "conflict").count()
    total_machines = db.query(Machine).filter(Machine.owner_id == current_user.id).count()

    return {
        "total_samples": total,
        "unreviewed_samples": unreviewed,
        "in_review_samples": in_review,
        "accepted_samples": accepted,
        "rejected_samples": rejected,
        "conflict_samples": conflict,
        "total_machines": total_machines,
    }
