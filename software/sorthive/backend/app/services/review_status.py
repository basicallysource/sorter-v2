from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.sample import Sample
from app.models.sample_review import SampleReview


def recompute_sample_status(db: Session, sample_id) -> None:
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if sample is None:
        return

    reviews = db.query(SampleReview).filter(SampleReview.sample_id == sample_id).all()

    total = len(reviews)
    accepted = sum(1 for r in reviews if r.decision == "accept")
    rejected = sum(1 for r in reviews if r.decision == "reject")

    sample.review_count = total
    sample.accepted_count = accepted
    sample.rejected_count = rejected

    min_reviews = settings.MIN_REVIEWS_FOR_CONSENSUS

    if total == 0:
        sample.review_status = "unreviewed"
        sample.resolved_at = None
    elif total < min_reviews:
        sample.review_status = "in_review"
        sample.resolved_at = None
    elif accepted == total:
        sample.review_status = "accepted"
        sample.resolved_at = datetime.now(timezone.utc)
    elif rejected == total:
        sample.review_status = "rejected"
        sample.resolved_at = datetime.now(timezone.utc)
    else:
        sample.review_status = "conflict"
        sample.resolved_at = datetime.now(timezone.utc)

    db.commit()
