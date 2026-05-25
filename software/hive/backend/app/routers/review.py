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
from app.schemas.review import (
    ConditionTagRequest,
    ConditionTagResponse,
    ReviewCreate,
    ReviewHistoryResponse,
    ReviewResponse,
)
from app.schemas.sample import SampleResponse
from app.config import settings
from app.models.machine import Machine
from app.routers.samples import apply_kind_filter, attach_my_reviews
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


@router.get("/queue/next", response_model=SampleResponse | None)
def get_next_review(
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    machine_id: UUID | None = None,
    source_role: str | None = None,
    capture_reason: str | None = None,
    kind: str | None = Query(None, pattern="^(regular|condition|all)$"),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 365),
    current_user: User = Depends(require_role("reviewer", "admin")),
    db: Session = Depends(get_db),
):
    """Return the next sample to review.

    Eligibility:
      * The viewer has not personally reviewed it yet.
      * The sample has fewer than ``REVIEW_CONSENSUS_TARGET`` total reviews —
        once enough independent voices have weighed in, the sample drops out
        of every reviewer's queue. Edge cases (ties, conflicts) can still be
        revisited via /samples; the queue is for fresh work only.
      * Neither the sample nor its machine is archived.

    NOTE: the *global* review_status (unreviewed / in_review / accepted /
    rejected / conflict) intentionally does NOT gate the queue. A sample
    that one reviewer already accepted should still appear for the next
    reviewer until consensus is reached — that's the whole point of
    multiple independent reviews.
    """
    already_reviewed = select(SampleReview.sample_id).where(
        SampleReview.reviewer_id == current_user.id
    )

    consensus_cap = max(1, int(settings.REVIEW_CONSENSUS_TARGET))
    query = db.query(Sample).filter(
        Sample.id.notin_(already_reviewed),
        Sample.review_count < consensus_cap,
        # Hide archived rows (per-sample archive + machine-level archive) so
        # the queue never serves something an admin has already taken out of
        # circulation.
        Sample.archived_at.is_(None),
        Sample.machine.has(Machine.archived_at.is_(None)),
    )
    query = apply_kind_filter(query, kind)

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
            # Prefer samples that already have at least one review (closer to
            # consensus) so they get knocked out of the queue first. New
            # samples come next, ordered by upload age.
            Sample.review_count.desc(),
            Sample.uploaded_at.asc(),
        )
        .first()
    )

    if not sample:
        return None

    attach_my_reviews([sample], db, current_user.id)
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


@router.post("/condition/{sample_id}", response_model=ConditionTagResponse)
def tag_condition_sample(
    sample_id: UUID,
    data: ConditionTagRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("reviewer", "admin")),
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
    if not sample:
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
