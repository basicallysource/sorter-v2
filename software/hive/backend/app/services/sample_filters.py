"""What the Channel samples filters mean, in one place.

The samples list, the review queue, the counts, the batch archive and delete,
and a teacher re-run all act on "the samples the filters show". They used to
each assemble the filters themselves, and the copies drifted (one dropped the
kind filter, another took one machine where the page could show several). Now
every one of them takes a ``SampleFilters`` and calls ``apply_sample_filters``
on its own base query, so an action can never reach a sample the page did not
show.

To add a filter: a field on ``SampleFilters`` (request bodies and the teacher
job filter inherit it), its meaning in ``apply_sample_filters``, and its query
parameter in ``sample_filters_query`` (the list's GET). All three are here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.sample import Sample

# Capture reasons that mark a sample as a piece-condition crop (collected by
# the sorter's condition_collector or the archived condition_teacher).
CONDITION_CAPTURE_REASONS: tuple[str, ...] = (
    "piece_condition_collector",
    "piece_condition_teacher",
)


class SampleFilters(BaseModel):
    """The Channel samples filters. None means "no filter" for every field.

    The same model is the body of the batch actions and the teacher job filter
    (they subclass it), and ``sample_filters_query`` builds it from the list's
    query parameters.
    """

    # Only these machines (one or several).
    machine_ids: list[UUID] | None = None
    upload_session_id: UUID | None = None
    source_role: str | None = None
    capture_reason: str | None = None
    review_status: str | None = None
    kind: str | None = None  # 'regular' | 'condition'
    my_review: str | None = None  # 'unreviewed' | 'reviewed' | 'accepted' | 'rejected'
    annotated: str | None = None  # 'teacher' | 'raw'
    exposure: str | None = None  # 'under' | 'normal' | 'over'
    max_age_hours: int | None = None
    # The review queue's fresh work for the viewer: samples they have not
    # reviewed that still need reviews to reach consensus.
    needs_review: bool = False


def sample_filters_query(
    machine_id: list[UUID] | None = Query(None),
    upload_session_id: UUID | None = None,
    source_role: str | None = None,
    capture_reason: str | None = None,
    review_status: str | None = None,
    kind: str | None = Query(None, pattern="^(regular|condition|all)$"),
    my_review: str | None = Query(None, pattern="^(unreviewed|reviewed|accepted|rejected)$"),
    annotated: str | None = Query(None, pattern="^(teacher|raw|all)$"),
    exposure: str | None = Query(None, pattern="^(under|normal|over)$"),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 365),
    needs_review: bool = False,
) -> SampleFilters:
    """``SampleFilters`` from query parameters (a FastAPI dependency).
    machine_id may be given several times."""
    return SampleFilters(
        machine_ids=machine_id or None,
        upload_session_id=upload_session_id,
        source_role=source_role,
        capture_reason=capture_reason,
        review_status=review_status,
        kind=kind,
        my_review=my_review,
        annotated=annotated,
        exposure=exposure,
        max_age_hours=max_age_hours,
        needs_review=needs_review,
    )


def restrict_to_machines(query, column, machine_ids):
    """Keep only rows of these machines. The one place a machine filter is
    applied, for samples and pieces alike; None or empty means every machine
    the caller may see."""
    if machine_ids:
        return query.filter(column.in_(list(machine_ids)))
    return query


def apply_kind_filter(query, kind: str | None):
    """'condition' keeps condition-collector crops, 'regular' everything else;
    anything else is no filter."""
    if kind == "condition":
        return query.filter(Sample.capture_reason.in_(CONDITION_CAPTURE_REASONS))
    if kind == "regular":
        return query.filter(
            (Sample.capture_reason.is_(None)) | (Sample.capture_reason.notin_(CONDITION_CAPTURE_REASONS))
        )
    return query


def apply_exposure_filter(query, exposure: str | None):
    """One exposure bucket: 'under', 'over', or 'normal' (neither, or no stats
    yet, so un-backfilled rows are not hidden). Thresholds mirror
    ``ExposureStats.classify``. Anything else is no filter."""
    if exposure not in {"under", "normal", "over"}:
        return query
    from app.services.image_stats import (
        OVEREXPOSED_CLIPPED_HIGH,
        OVEREXPOSED_MEAN_MIN,
        UNDEREXPOSED_CLIPPED_LOW,
        UNDEREXPOSED_MEAN_MAX,
    )

    is_under = (Sample.luminance_mean <= UNDEREXPOSED_MEAN_MAX) | (Sample.clipped_low_ratio >= UNDEREXPOSED_CLIPPED_LOW)
    is_over = (Sample.luminance_mean >= OVEREXPOSED_MEAN_MIN) | (Sample.clipped_high_ratio >= OVEREXPOSED_CLIPPED_HIGH)
    if exposure == "under":
        return query.filter(is_under)
    if exposure == "over":
        return query.filter(is_over)
    return query.filter(Sample.luminance_mean.is_(None) | (~is_under & ~is_over))


def apply_annotated_filter(query, annotated: str | None):
    """'teacher': a Hive teacher pass validated the boxes
    (``extra_metadata.teacher_rerun`` is set); 'raw': not yet. Anything else is
    no filter. ``col["teacher_rerun"] IS NOT NULL`` is the key-exists check
    that works on Postgres JSONB and SQLite alike."""
    if annotated not in {"teacher", "raw"}:
        return query
    has_teacher = Sample.extra_metadata["teacher_rerun"].isnot(None)
    if annotated == "teacher":
        return query.filter(has_teacher)
    return query.filter(~has_teacher | Sample.extra_metadata.is_(None))


def apply_my_review_filter(query, my_review: str | None, viewer_id):
    """The viewer's own decision: 'unreviewed', 'reviewed', 'accepted',
    'rejected'; anything else is no filter."""
    if my_review not in {"unreviewed", "reviewed", "accepted", "rejected"}:
        return query
    from app.models.sample_review import SampleReview

    ids = select(SampleReview.sample_id).where(SampleReview.reviewer_id == viewer_id)
    if my_review == "accepted":
        ids = ids.where(SampleReview.decision == "accept")
    elif my_review == "rejected":
        ids = ids.where(SampleReview.decision == "reject")
    if my_review == "unreviewed":
        return query.filter(Sample.id.notin_(ids))
    return query.filter(Sample.id.in_(ids))


def apply_needs_review(query, viewer_id):
    """The review queue's fresh work: not reviewed by the viewer, and short of
    the reviews it takes to reach consensus."""
    from app.models.sample_review import SampleReview

    mine = select(SampleReview.sample_id).where(SampleReview.reviewer_id == viewer_id)
    cap = max(1, int(settings.REVIEW_CONSENSUS_TARGET))
    return query.filter(Sample.id.notin_(mine), Sample.review_count < cap)


def apply_sample_filters(query, f: SampleFilters, viewer_id):
    """Narrow a Sample query to what the filters show. Every path that lists
    or acts on "the filtered samples" goes through here."""
    query = restrict_to_machines(query, Sample.machine_id, f.machine_ids)
    if f.upload_session_id is not None:
        query = query.filter(Sample.upload_session_id == f.upload_session_id)
    if f.source_role:
        query = query.filter(Sample.source_role == f.source_role)
    if f.capture_reason:
        query = query.filter(Sample.capture_reason == f.capture_reason)
    if f.review_status:
        query = query.filter(Sample.review_status == f.review_status)
    query = apply_kind_filter(query, f.kind)
    query = apply_my_review_filter(query, f.my_review, viewer_id)
    query = apply_annotated_filter(query, f.annotated)
    query = apply_exposure_filter(query, f.exposure)
    if f.max_age_hours is not None and f.max_age_hours > 0:
        query = query.filter(Sample.uploaded_at >= datetime.now(timezone.utc) - timedelta(hours=f.max_age_hours))
    if f.needs_review:
        query = apply_needs_review(query, viewer_id)
    return query


def attach_my_reviews(items: list, db: Session, viewer_id) -> None:
    """Set ``my_review_decision`` on each Sample row from one batch lookup."""
    if not items or viewer_id is None:
        for sample in items:
            sample.my_review_decision = None
        return
    from app.models.sample_review import SampleReview

    rows = (
        db.query(SampleReview.sample_id, SampleReview.decision)
        .filter(SampleReview.reviewer_id == viewer_id, SampleReview.sample_id.in_([s.id for s in items]))
        .all()
    )
    by_id = dict(rows)
    for sample in items:
        sample.my_review_decision = by_id.get(sample.id)
