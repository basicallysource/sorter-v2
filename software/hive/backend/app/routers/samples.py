import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from app.deps import (
    API_KEY_SCOPE_SAMPLES_READ,
    API_KEY_SCOPE_SAMPLES_WRITE,
    get_db,
    require_api_key_scopes,
    require_role,
    verify_csrf,
)
from app.errors import APIError
from app.models.machine import Machine
from app.models.sample import Sample
from app.models.user import User
from app.schemas.sample import (
    BatchArchiveSamplesRequest,
    BatchArchiveSamplesResponse,
    BatchDeleteSamplesRequest,
    BatchDeleteSamplesResponse,
    SampleDetailResponse,
    SampleListResponse,
    SampleResponse,
    SampleAnnotationsPayload,
    SampleClassificationPayload,
    SaveSampleAnnotationsRequest,
    SaveSampleAnnotationsResponse,
    SaveSampleClassificationRequest,
    SaveSampleClassificationResponse,
)
from app.services.storage import delete_sample_files, serve_stored_file
from app.services.sample_payloads import (
    is_classification_payload,
    set_manual_annotations,
    set_manual_classification,
)

router = APIRouter(prefix="/api/samples", tags=["samples"])

ASSET_CACHE_CONTROL = "no-store"


def _is_classification_sample(sample: Sample) -> bool:
    return is_classification_payload(
        sample.sample_payload,
        fallback_source_role=sample.source_role,
        fallback_capture_reason=sample.capture_reason,
    )


def _normalized_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _visible_sample_query(
    db: Session,
    current_user: User,
    scope: str | None,
    *,
    include_archived: bool = False,
):
    """Read-side query.

    Default scope is 'all' — samples are public to any logged-in user. ``scope='mine'``
    restricts to the caller's machines.

    Always hides samples whose machine is archived. Archived rigs (old hardware,
    decommissioned setups) shouldn't show up in browse/diversity/training pulls; their
    samples stay in the DB so an admin can un-archive without data loss.

    Per-sample archive flag (``Sample.archived_at``) is also filtered out by default.
    Admins can opt in to seeing them with ``include_archived=True`` so they have a
    surface to un-archive from.
    """
    query = db.query(Sample).filter(Sample.machine.has(Machine.archived_at.is_(None)))
    if not include_archived:
        query = query.filter(Sample.archived_at.is_(None))
    if scope == "mine":
        query = query.filter(Sample.machine.has(owner_id=current_user.id))
    return query


# Capture reasons that mark a sample as a piece-condition crop (collected by
# the sorter's condition_collector or the archived condition_teacher). Kept as
# a single source of truth so the kind filter on /samples and the queue filter
# on /review can't drift.
CONDITION_CAPTURE_REASONS: tuple[str, ...] = (
    "piece_condition_collector",
    "piece_condition_teacher",
)


def apply_kind_filter(query, kind: str | None):
    """Filter a Sample query down to 'regular' or 'condition' samples.

    `kind=condition` keeps only condition-collector / condition-teacher rows.
    `kind=regular` keeps everything *but* those. Anything else (None / 'all')
    is a no-op so the filter is safe to call unconditionally.
    """

    if kind == "condition":
        return query.filter(Sample.capture_reason.in_(CONDITION_CAPTURE_REASONS))
    if kind == "regular":
        return query.filter(
            (Sample.capture_reason.is_(None))
            | (Sample.capture_reason.notin_(CONDITION_CAPTURE_REASONS))
        )
    return query


def apply_exposure_filter(query, exposure: str | None):
    """Filter by computed exposure bucket — underexposed / normal / overexposed.

    Thresholds mirror ``ExposureStats.classify`` so the server-side filter
    and the per-sample badge stay in sync. ``None``-luminance rows (older
    samples awaiting backfill) drop out of any explicit bucket so they're
    visible only with the 'all' default.
    """

    if exposure not in {"under", "normal", "over"}:
        return query
    from app.services.image_stats import (
        OVEREXPOSED_CLIPPED_HIGH,
        OVEREXPOSED_MEAN_MIN,
        UNDEREXPOSED_CLIPPED_LOW,
        UNDEREXPOSED_MEAN_MAX,
    )

    if exposure == "under":
        return query.filter(
            (Sample.luminance_mean <= UNDEREXPOSED_MEAN_MAX)
            | (Sample.clipped_low_ratio >= UNDEREXPOSED_CLIPPED_LOW)
        )
    if exposure == "over":
        return query.filter(
            (Sample.luminance_mean >= OVEREXPOSED_MEAN_MIN)
            | (Sample.clipped_high_ratio >= OVEREXPOSED_CLIPPED_HIGH)
        )
    # normal: not under, not over, and we *do* have stats (otherwise we'd
    # accidentally classify un-backfilled rows as 'normal').
    return query.filter(
        Sample.luminance_mean.isnot(None),
        Sample.luminance_mean > UNDEREXPOSED_MEAN_MAX,
        Sample.luminance_mean < OVEREXPOSED_MEAN_MIN,
        (Sample.clipped_low_ratio.is_(None)) | (Sample.clipped_low_ratio < UNDEREXPOSED_CLIPPED_LOW),
        (Sample.clipped_high_ratio.is_(None)) | (Sample.clipped_high_ratio < OVEREXPOSED_CLIPPED_HIGH),
    )


def apply_annotated_filter(query, annotated: str | None):
    """Filter by whether the Hive teacher (Gemini/Perceptron) has already
    re-run on the sample.

    The signal is ``extra_metadata.teacher_rerun`` — that key is set only
    by ``apply_teacher_result_to_sample`` after a successful teacher pass.
    Raw sorter-side detections (the boxes that arrive with the upload)
    are often incomplete or off, so reviewers usually want to wait until
    a teacher has validated them.

    Values:
      - 'teacher' — has a teacher_rerun audit entry (training-ready)
      - 'raw'     — no teacher_rerun yet (likely still needs a pass)
      - anything else / None — no filter

    Uses PostgreSQL JSONB containment (``?`` operator). Live + dev both
    run postgres; this isn't tested on SQLite.
    """

    if annotated not in {"teacher", "raw"}:
        return query
    has_teacher = Sample.extra_metadata.op("?")("teacher_rerun")
    if annotated == "teacher":
        return query.filter(has_teacher)
    return query.filter(~has_teacher | Sample.extra_metadata.is_(None))


def apply_my_review_filter(query, my_review: str | None, viewer_id):
    """Filter samples by the viewer's own review decision.

    Values:
      - 'unreviewed' — viewer hasn't reviewed yet
      - 'reviewed'   — viewer reviewed (either decision)
      - 'accepted'   — viewer accepted
      - 'rejected'   — viewer rejected
      - anything else / None — no filter

    Uses a subquery against sample_reviews so the existing
    (sample_id, reviewer_id) unique index does the work.
    """

    if my_review not in {"unreviewed", "reviewed", "accepted", "rejected"}:
        return query

    from sqlalchemy import select as sa_select
    from app.models.sample_review import SampleReview

    base = sa_select(SampleReview.sample_id).where(
        SampleReview.reviewer_id == viewer_id
    )
    if my_review == "accepted":
        ids = base.where(SampleReview.decision == "accept")
    elif my_review == "rejected":
        ids = base.where(SampleReview.decision == "reject")
    else:
        ids = base  # reviewed or unreviewed both key off the existence subquery

    if my_review == "unreviewed":
        return query.filter(Sample.id.notin_(ids))
    return query.filter(Sample.id.in_(ids))


def attach_my_reviews(items: list, db: Session, viewer_id) -> None:
    """Populate ``my_review_decision`` on each Sample row via one batch lookup.

    Mutates the ORM instances in place so the from-attributes pydantic
    validation picks the value up without a second pass.
    """

    if not items or viewer_id is None:
        for sample in items:
            sample.my_review_decision = None
        return
    from app.models.sample_review import SampleReview

    sample_ids = [s.id for s in items]
    rows = (
        db.query(SampleReview.sample_id, SampleReview.decision)
        .filter(
            SampleReview.reviewer_id == viewer_id,
            SampleReview.sample_id.in_(sample_ids),
        )
        .all()
    )
    by_id = {sample_id: decision for sample_id, decision in rows}
    for sample in items:
        sample.my_review_decision = by_id.get(sample.id)


def _get_sample_for_read(db: Session, sample_id: UUID) -> Sample:
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")
    return sample


def _get_sample_for_write(db: Session, sample_id: UUID, current_user: User) -> Sample:
    """Writes (annotations/classification/delete) require owner or reviewer/admin."""
    sample = _get_sample_for_read(db, sample_id)
    is_owner = sample.machine.owner_id == current_user.id
    is_privileged = current_user.role in {"reviewer", "admin"}
    if not is_owner and not is_privileged:
        raise APIError(403, "Not authorized for this sample", "FORBIDDEN")
    return sample




@router.get("/filter-options")
def get_sample_filter_options(
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    query = _visible_sample_query(db, current_user, scope)
    source_roles = [
        value
        for (value,) in (
            query.with_entities(Sample.source_role)
            .filter(Sample.source_role.isnot(None))
            .distinct()
            .order_by(Sample.source_role.asc())
            .all()
        )
        if isinstance(value, str) and value
    ]
    source_role_counts = {
        value: int(count or 0)
        for value, count in (
            query.with_entities(Sample.source_role, func.count(Sample.id))
            .filter(Sample.source_role.isnot(None))
            .group_by(Sample.source_role)
            .all()
        )
        if isinstance(value, str) and value
    }
    capture_reasons = [
        value
        for (value,) in (
            query.with_entities(Sample.capture_reason)
            .filter(Sample.capture_reason.isnot(None))
            .distinct()
            .order_by(Sample.capture_reason.asc())
            .all()
        )
        if isinstance(value, str) and value
    ]
    return {
        "source_roles": source_roles,
        "source_role_counts": source_role_counts,
        "capture_reasons": capture_reasons,
    }


_DIVERSITY_BUCKET_KEYS = ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9-12", "13+")
_DIVERSITY_TARGET_PER_BUCKET = 50
_DIVERSITY_TREND_POINTS = 24
# Machine-diversity target — how many distinct machines we want contributing samples for a
# given (capture_reason × source_role) before the coverage stops being penalized. A piece
# captured by only one rig overfits the model to that rig's lighting/optics/wear; spreading
# across rigs is a multiplicative factor on top of bucket coverage.
_DIVERSITY_MACHINE_TARGET = 3

_DIVERSITY_TARGETS_DEFAULT: dict[str, int] = {k: _DIVERSITY_TARGET_PER_BUCKET for k in _DIVERSITY_BUCKET_KEYS}

# Per-source overrides. classification_channel only sees individual pieces under the camera —
# anything above 8 is effectively a counting error, 6–8 are rare edge cases. So we exclude 9+
# and weight 6/7/8 with a smaller target so they don't dominate the coverage score.
_DIVERSITY_TARGETS_PER_ROLE: dict[str, dict[str, int]] = {
    "classification_channel": {
        "0": 50, "1": 50, "2": 50, "3": 50, "4": 50, "5": 50,
        "6": 25, "7": 25, "8": 25,
        "9-12": 0, "13+": 0,
    },
}


def _targets_for_role(source_role: str | None) -> dict[str, int]:
    return _DIVERSITY_TARGETS_PER_ROLE.get(source_role or "", _DIVERSITY_TARGETS_DEFAULT)


_PIECE_BUCKET_CASE = case(
    (Sample.detection_count.is_(None), "unknown"),
    (Sample.detection_count == 0, "0"),
    (Sample.detection_count == 1, "1"),
    (Sample.detection_count == 2, "2"),
    (Sample.detection_count == 3, "3"),
    (Sample.detection_count == 4, "4"),
    (Sample.detection_count == 5, "5"),
    (Sample.detection_count == 6, "6"),
    (Sample.detection_count == 7, "7"),
    (Sample.detection_count == 8, "8"),
    (Sample.detection_count <= 12, "9-12"),
    else_="13+",
)


def _piece_bucket_key(count: int | None) -> str | None:
    if count is None:
        return None
    if 0 <= count <= 8:
        return str(count)
    if count <= 12:
        return "9-12"
    return "13+"


def _empty_buckets() -> dict[str, int]:
    return {k: 0 for k in _DIVERSITY_BUCKET_KEYS}


def _bucket_fills(buckets: dict[str, int], targets: dict[str, int]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in _DIVERSITY_BUCKET_KEYS:
        t = targets.get(k, 0)
        if t <= 0:
            out[k] = None  # bucket is not applicable for this role
        else:
            out[k] = min(buckets[k], t) / t
    return out


def _avg_fills(per_role: list[dict[str, float | None]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k in _DIVERSITY_BUCKET_KEYS:
        relevant = [rf[k] for rf in per_role if rf[k] is not None]
        out[k] = sum(relevant) / len(relevant) if relevant else None
    return out


def _coverage_from_fills(fills: dict[str, float | None]) -> float:
    relevant = [v for v in fills.values() if v is not None]
    if not relevant:
        return 0.0
    return sum(relevant) / len(relevant)


def _trend_boundaries(samples: list[tuple[int | None, datetime, UUID | None]]) -> list[datetime]:
    if not samples:
        return []
    t_first = samples[0][1]
    t_last = samples[-1][1]
    if t_first == t_last:
        return [t_last]
    step = (t_last - t_first) / _DIVERSITY_TREND_POINTS
    return [t_first + step * (i + 1) for i in range(_DIVERSITY_TREND_POINTS)]


def _machine_factor(machine_count: int) -> float:
    target = _DIVERSITY_MACHINE_TARGET
    if target <= 0:
        return 1.0
    return min(machine_count, target) / target


def _eta_seconds_from_trend(
    coverage: float,
    trend: list[float],
    boundaries: list[datetime],
) -> float | None:
    """Linearly extrapolate ETA-to-100% from the trend's most recent slope.

    Uses the last quarter of the trend window (min 2 points). Returns None if there is no
    progress in that window — that signals the donut is stalled and a useful ETA can't be
    given without more data.
    """
    if coverage >= 1.0:
        return 0.0
    if len(trend) < 2 or len(boundaries) < 2 or len(trend) != len(boundaries):
        return None
    window = max(2, len(trend) // 4)
    recent_trend = trend[-window:]
    recent_bounds = boundaries[-window:]
    delta_t = (recent_bounds[-1] - recent_bounds[0]).total_seconds()
    delta_c = recent_trend[-1] - recent_trend[0]
    if delta_t <= 0 or delta_c <= 0:
        return None
    slope = delta_c / delta_t
    remaining = 1.0 - coverage
    return remaining / slope


def _trend_on_grid(
    samples: list[tuple[int | None, datetime, UUID | None]],
    boundaries: list[datetime],
    targets: dict[str, int],
) -> list[float]:
    """Cumulative coverage of the role's samples sampled at the group's shared time grid.

    Boundaries come from the *group* timeline so that all roles within a group line up — that
    way the group-level trend can be the mean of role trends without time-axis skew. The
    cumulative machine count at each boundary is folded in so the trend reflects the same
    machine-factor penalty as the live coverage number.
    """
    if not boundaries:
        return []
    counts = _empty_buckets()
    machines: set[UUID] = set()
    trend: list[float] = []
    idx = 0
    for boundary in boundaries:
        while idx < len(samples) and samples[idx][1] <= boundary:
            key = _piece_bucket_key(samples[idx][0])
            if key in counts:
                counts[key] += 1
            machine_id = samples[idx][2]
            if machine_id is not None:
                machines.add(machine_id)
            idx += 1
        base = _coverage_from_fills(_bucket_fills(counts, targets))
        trend.append(base * _machine_factor(len(machines)))
    return trend


@router.get("/diversity")
def get_sample_diversity(
    capture_reason: str | None = None,
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    """Live diversity overview, grouped by capture_reason × source_role × piece-bucket.

    Each piece-count bucket has a target sample count (matches training/_progress targets).
    `coverage` per node is the mean of `min(count, target) / target` across buckets, multiplied
    by ``machine_factor = min(distinct_machines, machine_target) / machine_target`` — so a fully
    bucketed reason that comes from a single rig still scores below 1.0. The frontend renders
    each donut filling toward target with the machine factor surfaced separately.
    """
    base = _visible_sample_query(db, current_user, scope).filter(Sample.capture_reason.isnot(None))
    if capture_reason:
        base = base.filter(Sample.capture_reason == capture_reason)

    rows = (
        base.with_entities(
            Sample.capture_reason,
            Sample.source_role,
            _PIECE_BUCKET_CASE.label("bucket"),
            func.count(Sample.id).label("samples"),
            func.avg(Sample.detection_score).label("avg_score"),
            func.max(Sample.uploaded_at).label("last_uploaded_at"),
        )
        .group_by(Sample.capture_reason, Sample.source_role, "bucket")
        .all()
    )

    timeline_rows = (
        base.with_entities(
            Sample.capture_reason,
            Sample.source_role,
            Sample.machine_id,
            Sample.detection_count,
            Sample.uploaded_at,
        )
        .order_by(Sample.uploaded_at.asc())
        .all()
    )

    machine_rows_by_pair = (
        base.with_entities(
            Sample.capture_reason,
            Sample.source_role,
            func.count(distinct(Sample.machine_id)).label("machine_count"),
        )
        .group_by(Sample.capture_reason, Sample.source_role)
        .all()
    )
    machines_by_pair: dict[tuple[str, str], int] = {
        (reason, role or "unknown"): int(count or 0)
        for reason, role, count in machine_rows_by_pair
        if reason is not None
    }

    machine_rows_by_reason = (
        base.with_entities(
            Sample.capture_reason,
            func.count(distinct(Sample.machine_id)).label("machine_count"),
        )
        .group_by(Sample.capture_reason)
        .all()
    )
    machines_by_reason: dict[str, int] = {
        reason: int(count or 0) for reason, count in machine_rows_by_reason if reason is not None
    }

    timeline_by_pair: dict[tuple[str, str], list[tuple[int | None, datetime, UUID | None]]] = {}
    timeline_by_reason: dict[str, list[tuple[int | None, datetime, UUID | None]]] = {}
    for reason, role, machine_id, count, ts in timeline_rows:
        if reason is None or ts is None:
            continue
        role_key = role or "unknown"
        timeline_by_reason.setdefault(reason, []).append((count, ts, machine_id))
        timeline_by_pair.setdefault((reason, role_key), []).append((count, ts, machine_id))

    groups: dict[str, dict] = {}

    for reason, source_role, bucket, samples, avg_score, last_uploaded_at in rows:
        if reason is None:
            continue
        group = groups.setdefault(
            reason,
            {
                "capture_reason": reason,
                "total": 0,
                "unknown": 0,
                "score_weighted_sum": 0.0,
                "score_weight": 0,
                "buckets": _empty_buckets(),
                "by_source_role": {},
                "last_uploaded_at": None,
            },
        )
        role_key = source_role or "unknown"
        role = group["by_source_role"].setdefault(
            role_key,
            {
                "source_role": role_key,
                "total": 0,
                "unknown": 0,
                "score_weighted_sum": 0.0,
                "score_weight": 0,
                "buckets": _empty_buckets(),
                "last_uploaded_at": None,
            },
        )

        n = int(samples or 0)
        score = float(avg_score) if avg_score is not None else None

        group["total"] += n
        role["total"] += n
        if bucket in _DIVERSITY_BUCKET_KEYS:
            group["buckets"][bucket] += n
            role["buckets"][bucket] += n
        else:
            group["unknown"] += n
            role["unknown"] += n

        if score is not None:
            group["score_weighted_sum"] += score * n
            group["score_weight"] += n
            role["score_weighted_sum"] += score * n
            role["score_weight"] += n

        if last_uploaded_at is not None:
            if group["last_uploaded_at"] is None or last_uploaded_at > group["last_uploaded_at"]:
                group["last_uploaded_at"] = last_uploaded_at
            if role["last_uploaded_at"] is None or last_uploaded_at > role["last_uploaded_at"]:
                role["last_uploaded_at"] = last_uploaded_at

    def _finalize_score(node: dict) -> None:
        weight = node.pop("score_weight")
        weighted = node.pop("score_weighted_sum")
        node["avg_score"] = (weighted / weight) if weight > 0 else None
        if node["last_uploaded_at"] is not None:
            node["last_uploaded_at"] = node["last_uploaded_at"].isoformat()

    output_groups = []
    for group in groups.values():
        reason = group["capture_reason"]
        boundaries = _trend_boundaries(timeline_by_reason.get(reason, []))

        finalized_roles = []
        role_fills: list[dict[str, float | None]] = []
        role_trends: list[list[float]] = []
        group_targets_union = {k: 0 for k in _DIVERSITY_BUCKET_KEYS}
        for role in group["by_source_role"].values():
            role_samples = timeline_by_pair.get((reason, role["source_role"]), [])
            role_targets = _targets_for_role(role["source_role"])
            fills = _bucket_fills(role["buckets"], role_targets)
            role_machine_count = machines_by_pair.get((reason, role["source_role"]), 0)
            role_machine_factor = _machine_factor(role_machine_count)
            role["bucket_fills"] = fills
            role["bucket_targets"] = dict(role_targets)
            base_coverage = _coverage_from_fills(fills)
            role["coverage_base"] = base_coverage
            role["coverage"] = base_coverage * role_machine_factor
            role["machine_count"] = role_machine_count
            role["machine_target"] = _DIVERSITY_MACHINE_TARGET
            role["machine_factor"] = role_machine_factor
            role["coverage_trend"] = _trend_on_grid(role_samples, boundaries, role_targets)
            role["eta_seconds"] = _eta_seconds_from_trend(role["coverage"], role["coverage_trend"], boundaries)
            _finalize_score(role)
            finalized_roles.append(role)
            role_fills.append(fills)
            role_trends.append(role["coverage_trend"])
            for k in _DIVERSITY_BUCKET_KEYS:
                if role_targets.get(k, 0) > group_targets_union[k]:
                    group_targets_union[k] = role_targets[k]

        group["by_source_role"] = sorted(
            finalized_roles, key=lambda r: (-r["total"], r["source_role"])
        )

        # Group view: average per-role fills and trends across roles where the bucket is
        # in scope. A bucket only counts as full when *every* relevant role has it filled
        # — that's the balanced-diversity signal. Machine factor is applied on top of the
        # already-multiplied role trends so the group line stays in sync.
        group_fills = _avg_fills(role_fills)
        group_machine_count = machines_by_reason.get(reason, 0)
        group_machine_factor = _machine_factor(group_machine_count)
        group["bucket_fills"] = group_fills
        group["bucket_targets"] = group_targets_union
        base_group_coverage = _coverage_from_fills(group_fills)
        group["coverage_base"] = base_group_coverage
        group["coverage"] = base_group_coverage * group_machine_factor
        group["machine_count"] = group_machine_count
        group["machine_target"] = _DIVERSITY_MACHINE_TARGET
        group["machine_factor"] = group_machine_factor
        if role_trends and boundaries:
            n_roles = len(role_trends)
            group["coverage_trend"] = [
                sum(rt[i] for rt in role_trends) / n_roles for i in range(len(boundaries))
            ]
        else:
            group["coverage_trend"] = []
        group["eta_seconds"] = _eta_seconds_from_trend(
            group["coverage"], group["coverage_trend"], boundaries
        )
        _finalize_score(group)
        output_groups.append(group)

    output_groups.sort(key=lambda g: (-g["total"], g["capture_reason"]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total": sum(g["total"] for g in output_groups),
        "default_target_per_bucket": _DIVERSITY_TARGET_PER_BUCKET,
        "machine_target": _DIVERSITY_MACHINE_TARGET,
        "bucket_keys": list(_DIVERSITY_BUCKET_KEYS),
        "groups": output_groups,
    }


@router.get("", response_model=SampleListResponse)
def list_samples(
    page: int = Query(1, ge=1),
    page_size: int = Query(36, ge=1, le=100),
    machine_id: UUID | None = None,
    upload_session_id: UUID | None = None,
    source_role: str | None = None,
    capture_reason: str | None = None,
    review_status: str | None = None,
    kind: str | None = Query(None, pattern="^(regular|condition|all)$"),
    my_review: str | None = Query(None, pattern="^(unreviewed|reviewed|accepted|rejected)$"),
    annotated: str | None = Query(None, pattern="^(teacher|raw|all)$"),
    exposure: str | None = Query(None, pattern="^(under|normal|over|all)$"),
    archived: str | None = Query(None, pattern="^(active|archived|all)$"),
    max_age_hours: int | None = Query(None, ge=1, le=24 * 365),
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    # `archived` is admin-only — members never see archived samples regardless
    # of what they pass. Default ('active' or unset) hides them.
    is_admin = current_user.role == "admin"
    include_archived = is_admin and archived in ("archived", "all")
    only_archived = is_admin and archived == "archived"

    query = _visible_sample_query(db, current_user, scope, include_archived=include_archived)
    if only_archived:
        query = query.filter(Sample.archived_at.isnot(None))
    query = apply_kind_filter(query, kind)
    query = apply_my_review_filter(query, my_review, current_user.id)
    # Default-hide raw samples — reviewers shouldn't waste time on boxes
    # the teacher hasn't validated yet. Explicit ?annotated=all opts back
    # in to seeing everything.
    query = apply_annotated_filter(query, annotated or "teacher")
    query = apply_exposure_filter(query, exposure)

    if machine_id:
        query = query.filter(Sample.machine_id == machine_id)
    if upload_session_id:
        query = query.filter(Sample.upload_session_id == upload_session_id)
    if source_role:
        query = query.filter(Sample.source_role == source_role)
    if capture_reason:
        query = query.filter(Sample.capture_reason == capture_reason)
    if review_status:
        query = query.filter(Sample.review_status == review_status)
    if max_age_hours is not None:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        query = query.filter(Sample.uploaded_at >= cutoff)

    query = query.order_by(Sample.uploaded_at.desc())

    total = query.count()
    pages = math.ceil(total / page_size) if total > 0 else 1
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    attach_my_reviews(items, db, current_user.id)

    return SampleListResponse(
        items=[SampleResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{sample_id}/similar", response_model=SampleListResponse)
def get_similar_samples(
    sample_id: UUID,
    limit: int = Query(24, ge=1, le=100),
    max_distance: int = Query(16, ge=0, le=64),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    """Return samples visually similar to ``sample_id``, sorted by Hamming
    distance over the stored 8×8 pHash.

    Excludes the sample itself, archived rows, and anything whose pHash is
    null (un-decodable image, or older sample that hasn't been backfilled).
    Distance is computed in SQL via ``bit_count(phash # :target)`` so the
    server doesn't need to materialize every row.
    """
    from sqlalchemy import text

    target = db.query(Sample).filter(Sample.id == sample_id).first()
    if target is None:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")
    if target.phash is None:
        # No hash to compare against. Return an empty list rather than
        # falling back to "newest samples" — empty is the truthful answer.
        return SampleListResponse(items=[], total=0, page=1, page_size=limit, pages=0)

    # Hamming distance via XOR + popcount inline in SQL. Postgres ``#`` is
    # bitwise XOR on integers and ``bit_count`` (Postgres 14+) counts set
    # bits. We rank by distance, drop self + archived rows + nulls, and
    # cap by ``max_distance`` so a wildly different image doesn't surface.
    bit_distance = text("bit_count(samples.phash # :target_phash)")
    rows = (
        db.query(Sample, bit_distance.label("distance"))
        .filter(Sample.machine.has(Machine.archived_at.is_(None)))
        .filter(Sample.archived_at.is_(None))
        .filter(Sample.phash.isnot(None))
        .filter(Sample.id != target.id)
        .filter(bit_distance <= int(max_distance))
        .order_by(text("distance"))
        .params(target_phash=int(target.phash))
        .limit(limit)
        .all()
    )

    items = [sample for sample, _distance in rows]
    attach_my_reviews(items, db, current_user.id)
    return SampleListResponse(
        items=[SampleResponse.model_validate(s) for s in items],
        total=len(items),
        page=1,
        page_size=limit,
        pages=1 if items else 0,
    )


@router.get("/{sample_id}", response_model=SampleDetailResponse)
def get_sample(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_read(db, sample_id)
    attach_my_reviews([sample], db, current_user.id)

    data = SampleDetailResponse.model_validate(sample)
    data.has_full_frame = sample.full_frame_path is not None
    data.has_overlay = sample.overlay_path is not None
    return data


@router.put("/{sample_id}/annotations", response_model=SaveSampleAnnotationsResponse)
def save_sample_annotations(
    sample_id: UUID,
    data: SaveSampleAnnotationsRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    sample = _get_sample_for_write(db, sample_id, current_user)

    payload = SampleAnnotationsPayload(
        version=data.version,
        updated_at=datetime.now(timezone.utc),
        updated_by_display_name=current_user.display_name or current_user.email,
        annotations=data.annotations,
    )

    extra_metadata = dict(sample.extra_metadata or {})
    extra_metadata["manual_annotations"] = payload.model_dump(mode="json")
    sample.extra_metadata = extra_metadata
    sample.sample_payload = set_manual_annotations(sample.sample_payload, payload.model_dump(mode="json"))

    db.add(sample)
    db.commit()

    return SaveSampleAnnotationsResponse(
        ok=True,
        annotation_count=len(data.annotations),
        data=payload,
    )


@router.put("/{sample_id}/classification", response_model=SaveSampleClassificationResponse)
def save_sample_classification(
    sample_id: UUID,
    data: SaveSampleClassificationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    sample = _get_sample_for_write(db, sample_id, current_user)

    if not _is_classification_sample(sample):
        raise APIError(
            400,
            "Manual classification is only supported for classification chamber samples.",
            "UNSUPPORTED_SAMPLE_TYPE",
        )

    payload = SampleClassificationPayload(
        part_id=_normalized_optional_string(data.part_id),
        item_name=_normalized_optional_string(data.item_name),
        color_id=_normalized_optional_string(data.color_id),
        color_name=_normalized_optional_string(data.color_name),
        updated_at=datetime.now(timezone.utc),
        updated_by_display_name=current_user.display_name or current_user.email,
    )

    extra_metadata = dict(sample.extra_metadata or {})
    if not any([payload.part_id, payload.item_name, payload.color_id, payload.color_name]):
        extra_metadata.pop("manual_classification", None)
        sample.extra_metadata = extra_metadata
        sample.sample_payload = set_manual_classification(sample.sample_payload, None)
        db.add(sample)
        db.commit()
        return SaveSampleClassificationResponse(ok=True, cleared=True, data=None)

    extra_metadata["manual_classification"] = payload.model_dump(mode="json")
    sample.extra_metadata = extra_metadata
    sample.sample_payload = set_manual_classification(sample.sample_payload, payload.model_dump(mode="json"))

    db.add(sample)
    db.commit()

    return SaveSampleClassificationResponse(
        ok=True,
        cleared=False,
        data=payload,
    )


def _apply_archive_filters(query, payload: BatchArchiveSamplesRequest):
    """Shared filter assembly for archive + unarchive endpoints."""

    query = apply_kind_filter(query, payload.kind)
    if payload.machine_id:
        try:
            machine_uuid = UUID(payload.machine_id)
        except ValueError:
            raise APIError(400, "machine_id must be a UUID", "INVALID_MACHINE_ID")
        query = query.filter(Sample.machine_id == machine_uuid)
    if payload.source_role:
        query = query.filter(Sample.source_role == payload.source_role)
    if payload.capture_reason:
        query = query.filter(Sample.capture_reason == payload.capture_reason)
    if payload.review_status:
        query = query.filter(Sample.review_status == payload.review_status)
    if payload.max_age_hours is not None:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=payload.max_age_hours)
        query = query.filter(Sample.uploaded_at >= cutoff)
    return query


@router.post("/batch-archive", response_model=BatchArchiveSamplesResponse)
def batch_archive_samples(
    payload: BatchArchiveSamplesRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    """Admin-only soft-delete: stamp `archived_at` on every active sample
    matching the filter, hiding it from listings + review + training pulls.

    Reversible via POST /api/samples/batch-unarchive with the same filter.
    No file deletion happens — just the flag — so unarchive restores fully.
    """

    # Only operate on currently-active samples (skip those already archived).
    query = (
        db.query(Sample)
        .filter(Sample.machine.has(Machine.archived_at.is_(None)))
        .filter(Sample.archived_at.is_(None))
    )
    query = _apply_archive_filters(query, payload)

    matched = query.count()

    if payload.dry_run:
        return BatchArchiveSamplesResponse(
            ok=True,
            matched=matched,
            archived=0,
            dry_run=True,
            capped=matched > payload.max_archive,
        )

    if matched > payload.max_archive:
        raise APIError(
            400,
            f"Filter matches {matched} samples — narrow the filter or raise max_archive "
            f"(currently {payload.max_archive}). Refusing to archive in one shot.",
            "BATCH_ARCHIVE_TOO_LARGE",
        )

    # Bulk UPDATE is cheaper than row-by-row for large sets and keeps the
    # transaction short — no per-row ORM overhead.
    now = datetime.now(timezone.utc)
    archived = query.update({Sample.archived_at: now}, synchronize_session=False)
    db.commit()
    return BatchArchiveSamplesResponse(
        ok=True,
        matched=matched,
        archived=int(archived or 0),
        dry_run=False,
    )


@router.post("/batch-unarchive", response_model=BatchArchiveSamplesResponse)
def batch_unarchive_samples(
    payload: BatchArchiveSamplesRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role("admin")),
    _csrf: None = Depends(verify_csrf),
):
    """Reverse of batch-archive. Operates only on currently-archived rows."""

    query = (
        db.query(Sample)
        .filter(Sample.machine.has(Machine.archived_at.is_(None)))
        .filter(Sample.archived_at.isnot(None))
    )
    query = _apply_archive_filters(query, payload)

    matched = query.count()

    if payload.dry_run:
        return BatchArchiveSamplesResponse(
            ok=True,
            matched=matched,
            archived=0,
            dry_run=True,
            capped=matched > payload.max_archive,
        )

    if matched > payload.max_archive:
        raise APIError(
            400,
            f"Filter matches {matched} archived samples — narrow the filter or raise "
            f"max_archive (currently {payload.max_archive}).",
            "BATCH_UNARCHIVE_TOO_LARGE",
        )

    unarchived = query.update({Sample.archived_at: None}, synchronize_session=False)
    db.commit()
    return BatchArchiveSamplesResponse(
        ok=True,
        matched=matched,
        archived=int(unarchived or 0),
        dry_run=False,
    )


@router.post("/batch-delete", response_model=BatchDeleteSamplesResponse)
def batch_delete_samples(
    payload: BatchDeleteSamplesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    """Bulk-delete samples matching the given filters, always scoped to
    machines the caller owns.

    The ownership filter is enforced server-side regardless of what the
    client sends — there is intentionally no admin override on this surface
    so a misclick from an admin account can't nuke a member's samples.
    Admins who need to drop someone else's data still go through the
    per-sample DELETE endpoint with explicit intent.
    """

    query = db.query(Sample).filter(Sample.machine.has(owner_id=current_user.id))

    query = apply_kind_filter(query, payload.kind)
    if payload.machine_id:
        try:
            machine_uuid = UUID(payload.machine_id)
        except ValueError:
            raise APIError(400, "machine_id must be a UUID", "INVALID_MACHINE_ID")
        query = query.filter(Sample.machine_id == machine_uuid)
    if payload.source_role:
        query = query.filter(Sample.source_role == payload.source_role)
    if payload.capture_reason:
        query = query.filter(Sample.capture_reason == payload.capture_reason)
    if payload.review_status:
        query = query.filter(Sample.review_status == payload.review_status)
    if payload.max_age_hours is not None:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(hours=payload.max_age_hours)
        query = query.filter(Sample.uploaded_at >= cutoff)

    matched = query.count()

    if payload.dry_run:
        return BatchDeleteSamplesResponse(
            ok=True,
            matched=matched,
            deleted=0,
            dry_run=True,
            capped=matched > payload.max_delete,
        )

    if matched > payload.max_delete:
        raise APIError(
            400,
            f"Filter matches {matched} samples — narrow the filter or raise max_delete "
            f"(currently {payload.max_delete}). Refusing to delete in one shot.",
            "BATCH_DELETE_TOO_LARGE",
        )

    # Materialize once so file deletion can iterate without holding cursors.
    samples = query.all()
    # Track upload sessions so we can decrement their counters in one pass.
    session_decrements: dict[UUID, int] = {}
    deleted = 0
    for sample in samples:
        delete_sample_files(sample)
        if sample.upload_session_id:
            session_decrements[sample.upload_session_id] = (
                session_decrements.get(sample.upload_session_id, 0) + 1
            )
        db.delete(sample)
        deleted += 1

    if session_decrements:
        from app.models.upload_session import UploadSession
        sessions = (
            db.query(UploadSession)
            .filter(UploadSession.id.in_(session_decrements.keys()))
            .all()
        )
        for session in sessions:
            drop = session_decrements.get(session.id, 0)
            session.sample_count = max(0, session.sample_count - drop)

    db.commit()
    return BatchDeleteSamplesResponse(
        ok=True,
        matched=matched,
        deleted=deleted,
        dry_run=False,
    )


@router.delete("/{sample_id}")
def delete_sample(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    sample = _get_sample_for_read(db, sample_id)

    # Deletes need owner or admin — reviewers don't get to drop other people's data.
    is_owner = sample.machine.owner_id == current_user.id
    is_admin = current_user.role == "admin"
    if not is_owner and not is_admin:
        raise APIError(403, "Not authorized to delete this sample", "FORBIDDEN")

    delete_sample_files(sample)

    # Decrement session count
    session = sample.upload_session
    if session:
        session.sample_count = max(0, session.sample_count - 1)

    db.delete(sample)
    db.commit()
    return {"ok": True}


@router.get("/{sample_id}/assets/image")
def get_sample_image(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_read(db, sample_id)

    return serve_stored_file(sample.image_path, headers={"Cache-Control": ASSET_CACHE_CONTROL})


@router.get("/{sample_id}/assets/full-frame")
def get_sample_full_frame(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_read(db, sample_id)
    if not sample.full_frame_path:
        raise APIError(404, "Full frame not found", "ASSET_NOT_FOUND")

    return serve_stored_file(sample.full_frame_path, headers={"Cache-Control": ASSET_CACHE_CONTROL})


@router.get("/{sample_id}/assets/overlay")
def get_sample_overlay(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_read(db, sample_id)
    if not sample.overlay_path:
        raise APIError(404, "Overlay not found", "ASSET_NOT_FOUND")

    return serve_stored_file(sample.overlay_path, headers={"Cache-Control": ASSET_CACHE_CONTROL})
