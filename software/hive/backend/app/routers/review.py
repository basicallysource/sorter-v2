from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, joinedload

from app.deps import get_current_user, get_db, verify_csrf
from app.errors import APIError
from app.models.sample import Sample
from app.models.sample_review import SampleReview
from app.models.user import User
from app.schemas.review import (
    ConditionTagRequest,
    ConditionTagResponse,
    ReviewCreate,
    ReviewHistoryResponse,
    ReviewResponse,
)
from app.services.access_window import sample_access_visible
from app.services.condition_analysis import (
    COMPOSITION_VALUES,
    CONDITION_VALUES,
    FLAG_NAMES,
    SOURCE_HUMAN,
    upsert_condition_analysis,
)
from app.services.review_status import recompute_sample_status

router = APIRouter(prefix="/api/review", tags=["review"])


def _review_response(review: SampleReview) -> ReviewResponse:
    resp = ReviewResponse.model_validate(review)
    if review.reviewer:
        resp.reviewer_display_name = review.reviewer.display_name
    return resp


@router.post("/samples/{sample_id}", response_model=ReviewResponse)
def create_or_update_review(
    sample_id: UUID,
    data: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    # Reviewing is a reviewer/admin action — a plain member (even a machine's
    # own owner) doesn't get to vote on sample labels.
    if current_user.role not in ("admin", "reviewer"):
        raise APIError(403, "Only reviewers can review samples", "REVIEW_FORBIDDEN")
    if data.decision not in ("accept", "reject"):
        raise APIError(400, "Decision must be 'accept' or 'reject'", "INVALID_DECISION")

    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample or not sample_access_visible(db, current_user, sample):
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


@router.post("/condition/{sample_id}", response_model=ConditionTagResponse)
def tag_condition_sample(
    sample_id: UUID,
    data: ConditionTagRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf),
):
    """Human tags a condition sample with flag chips.

    Writes a `cond_primary` analysis block with source=human_review, which
    replaces any prior auto-label from the Perceptron worker. Always wins
    over machine output — humans are the override authority.

    Keeping this separate from POST /samples/{id} (which is accept/reject)
    means the binary review queue stays simple and the condition tagger
    can mature independently. No sample_reviews row is written; the
    auditable trail lives inside the analysis block (provider, written_at,
    reviewer_id) since the existing CHECK constraint forbids any
    decision values beyond accept/reject.
    """

    if data.composition not in COMPOSITION_VALUES:
        raise APIError(
            400,
            f"composition must be one of {list(COMPOSITION_VALUES)}",
            "INVALID_COMPOSITION",
        )
    if data.condition not in CONDITION_VALUES:
        raise APIError(
            400,
            f"condition must be one of {list(CONDITION_VALUES)}",
            "INVALID_CONDITION",
        )

    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample or not sample_access_visible(db, current_user, sample):
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")

    # Drop unknown flag keys silently — the writer also filters, but doing
    # it here gives us a tidy payload to return to the client.
    sanitized_flags = {
        key: bool(value)
        for key, value in data.flags.items()
        if key in FLAG_NAMES and isinstance(value, bool)
    }

    analysis = upsert_condition_analysis(
        sample,
        composition=data.composition,
        condition=data.condition,
        flags=sanitized_flags,
        source=SOURCE_HUMAN,
        model=None,
        visible_evidence=data.visible_evidence,
        part_count_estimate=data.part_count_estimate,
        issues=data.issues,
        reviewer_id=str(current_user.id),
    )
    db.commit()
    db.refresh(sample)
    return ConditionTagResponse(
        sample_id=sample.id,
        analysis=analysis,
        review_status=sample.review_status,
        written_by=current_user.id,
    )


@router.get("/samples/{sample_id}/history", response_model=ReviewHistoryResponse)
def get_review_history(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample or not sample_access_visible(db, current_user, sample):
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
