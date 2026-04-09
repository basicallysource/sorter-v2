from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer", "admin")),
):
    already_reviewed = db.query(SampleReview.sample_id).filter(
        SampleReview.reviewer_id == current_user.id
    ).subquery()

    sample = (
        db.query(Sample)
        .filter(
            Sample.review_status.in_(["unreviewed", "in_review"]),
            Sample.id.notin_(already_reviewed),
        )
        .order_by(
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
