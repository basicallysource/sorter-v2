from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.deps import get_db, require_role, verify_csrf
from app.errors import APIError
from app.models.sample import Sample
from app.models.sample_review import SampleReview
from app.models.user import User
from app.schemas.review import ReviewCreate, ReviewHistoryResponse, ReviewResponse
from app.schemas.sample import SampleResponse
from app.services.review_status import recompute_sample_status

router = APIRouter(prefix="/api/review", tags=["review"])


def _review_response(review: SampleReview) -> ReviewResponse:
    resp = ReviewResponse.model_validate(review)
    if review.reviewer:
        resp.reviewer_display_name = review.reviewer.display_name
    return resp


@router.get("/queue/next", response_model=SampleResponse | None)
def get_next_review(
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    machine_id: UUID | None = None,
    source_role: str | None = None,
    capture_reason: str | None = None,
    max_age_hours: int | None = Query(None, ge=1, le=24 * 365),
    current_user: User = Depends(require_role("reviewer", "admin")),
    db: Session = Depends(get_db),
):
    """Return the next sample to review, honouring the same filters as the samples list.

    The samples list page passes its sidebar selection through to the Review Samples link
    as URL params; the review queue then drains only the slice the reviewer chose. Without
    a filter the queue behaves exactly as before (any unreviewed/in-review sample).
    """
    already_reviewed = select(SampleReview.sample_id).where(
        SampleReview.reviewer_id == current_user.id
    )

    query = db.query(Sample).filter(
        Sample.review_status.in_(["unreviewed", "in_review"]),
        Sample.id.notin_(already_reviewed),
    )

    if scope == "mine":
        query = query.filter(Sample.machine.has(owner_id=current_user.id))
    if machine_id is not None:
        query = query.filter(Sample.machine_id == machine_id)
    if source_role:
        query = query.filter(Sample.source_role == source_role)
    if capture_reason:
        query = query.filter(Sample.capture_reason == capture_reason)
    if max_age_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        query = query.filter(Sample.uploaded_at >= cutoff)

    sample = (
        query.order_by(
            Sample.review_status.desc(),
            Sample.uploaded_at.asc(),
        )
        .first()
    )

    if not sample:
        return None

    return SampleResponse.model_validate(sample)


@router.post("/samples/{sample_id}", response_model=ReviewResponse)
def create_or_update_review(
    sample_id: UUID,
    data: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer", "admin")),
    _csrf: None = Depends(verify_csrf),
):
    if data.decision not in ("accept", "reject"):
        raise APIError(400, "Decision must be 'accept' or 'reject'", "INVALID_DECISION")

    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")

    # Upsert review
    existing = (
        db.query(SampleReview)
        .filter(SampleReview.sample_id == sample_id, SampleReview.reviewer_id == current_user.id)
        .first()
    )

    if existing:
        existing.decision = data.decision
        existing.notes = data.notes
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        recompute_sample_status(db, sample_id)
        return _review_response(existing)
    else:
        review = SampleReview(
            sample_id=sample_id,
            reviewer_id=current_user.id,
            decision=data.decision,
            notes=data.notes,
        )
        db.add(review)
        db.commit()
        db.refresh(review)
        recompute_sample_status(db, sample_id)
        return _review_response(review)


@router.get("/samples/{sample_id}/history", response_model=ReviewHistoryResponse)
def get_review_history(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer", "admin")),
):
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")

    reviews = (
        db.query(SampleReview)
        .options(joinedload(SampleReview.reviewer))
        .filter(SampleReview.sample_id == sample_id)
        .order_by(SampleReview.created_at)
        .all()
    )

    return ReviewHistoryResponse(
        reviews=[_review_response(r) for r in reviews],
        sample_id=sample.id,
        review_status=sample.review_status,
    )
