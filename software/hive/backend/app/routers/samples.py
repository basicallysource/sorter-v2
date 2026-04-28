import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.deps import (
    API_KEY_SCOPE_SAMPLES_READ,
    API_KEY_SCOPE_SAMPLES_WRITE,
    get_db,
    require_api_key_scopes,
    verify_csrf,
)
from app.errors import APIError
from app.models.sample import Sample
from app.models.user import User
from app.schemas.sample import (
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
from app.services.storage import delete_sample_files, get_file_path
from app.services.sample_payloads import (
    is_classification_payload,
    set_manual_annotations,
    set_manual_classification,
)

router = APIRouter(prefix="/api/samples", tags=["samples"])


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


def _sample_query_for_user(db: Session, current_user: User):
    query = db.query(Sample)
    if current_user.role in {"reviewer", "admin"}:
        return query
    return query.filter(Sample.machine.has(owner_id=current_user.id))


def _get_sample_for_user(db: Session, sample_id: UUID, current_user: User) -> Sample:
    sample = _sample_query_for_user(db, current_user).filter(Sample.id == sample_id).first()
    if not sample:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")
    return sample


@router.get("/filter-options")
def get_sample_filter_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    query = _sample_query_for_user(db, current_user)
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


def _trend_boundaries(samples: list[tuple[int | None, datetime]]) -> list[datetime]:
    if not samples:
        return []
    t_first = samples[0][1]
    t_last = samples[-1][1]
    if t_first == t_last:
        return [t_last]
    step = (t_last - t_first) / _DIVERSITY_TREND_POINTS
    return [t_first + step * (i + 1) for i in range(_DIVERSITY_TREND_POINTS)]


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
    samples: list[tuple[int | None, datetime]],
    boundaries: list[datetime],
    targets: dict[str, int],
) -> list[float]:
    """Cumulative coverage of the role's samples sampled at the group's shared time grid.

    Boundaries come from the *group* timeline so that all roles within a group line up — that
    way the group-level trend can be the mean of role trends without time-axis skew.
    """
    if not boundaries:
        return []
    counts = _empty_buckets()
    trend: list[float] = []
    idx = 0
    for boundary in boundaries:
        while idx < len(samples) and samples[idx][1] <= boundary:
            key = _piece_bucket_key(samples[idx][0])
            if key in counts:
                counts[key] += 1
            idx += 1
        trend.append(_coverage_from_fills(_bucket_fills(counts, targets)))
    return trend


@router.get("/diversity")
def get_sample_diversity(
    capture_reason: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    """Live diversity overview, grouped by capture_reason × source_role × piece-bucket.

    Each piece-count bucket has a target sample count (matches training/_progress targets).
    `coverage` per node is the mean of `min(count, target) / target` across buckets — 1.0 == full
    diversity. The frontend renders this as a donut where each wedge fills toward target.
    """
    base = _sample_query_for_user(db, current_user).filter(Sample.capture_reason.isnot(None))
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
            Sample.detection_count,
            Sample.uploaded_at,
        )
        .order_by(Sample.uploaded_at.asc())
        .all()
    )

    timeline_by_pair: dict[tuple[str, str], list[tuple[int | None, datetime]]] = {}
    timeline_by_reason: dict[str, list[tuple[int | None, datetime]]] = {}
    for reason, role, count, ts in timeline_rows:
        if reason is None or ts is None:
            continue
        role_key = role or "unknown"
        timeline_by_reason.setdefault(reason, []).append((count, ts))
        timeline_by_pair.setdefault((reason, role_key), []).append((count, ts))

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
            role["bucket_fills"] = fills
            role["bucket_targets"] = dict(role_targets)
            role["coverage"] = _coverage_from_fills(fills)
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
        # — that's the balanced-diversity signal.
        group_fills = _avg_fills(role_fills)
        group["bucket_fills"] = group_fills
        group["bucket_targets"] = group_targets_union
        group["coverage"] = _coverage_from_fills(group_fills)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    query = _sample_query_for_user(db, current_user)

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

    query = query.order_by(Sample.uploaded_at.desc())

    total = query.count()
    pages = math.ceil(total / page_size) if total > 0 else 1
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    return SampleListResponse(
        items=[SampleResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/{sample_id}", response_model=SampleDetailResponse)
def get_sample(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_user(db, sample_id, current_user)

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
    sample = _get_sample_for_user(db, sample_id, current_user)

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
    sample = _get_sample_for_user(db, sample_id, current_user)

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


@router.delete("/{sample_id}")
def delete_sample(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_WRITE)),
    _csrf: None = Depends(verify_csrf),
):
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")

    # Only owner of the machine or admin can delete
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
    sample = _get_sample_for_user(db, sample_id, current_user)

    path = get_file_path(sample.image_path)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{sample_id}/assets/full-frame")
def get_sample_full_frame(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_user(db, sample_id, current_user)
    if not sample or not sample.full_frame_path:
        raise APIError(404, "Full frame not found", "ASSET_NOT_FOUND")

    path = get_file_path(sample.full_frame_path)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{sample_id}/assets/overlay")
def get_sample_overlay(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_user(db, sample_id, current_user)
    if not sample or not sample.overlay_path:
        raise APIError(404, "Overlay not found", "ASSET_NOT_FOUND")

    path = get_file_path(sample.overlay_path)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=86400"})
