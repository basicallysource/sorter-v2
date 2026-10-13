from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import cast, func
from sqlalchemy.dialects.postgresql import BIT
from sqlalchemy.orm import Session

from app.deps import (
    API_KEY_SCOPE_SAMPLES_READ,
    API_KEY_SCOPE_SAMPLES_WRITE,
    get_db,
    require_api_key_scopes,
    require_role,
    statement_timeout,
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
    SamplePageResponse,
    SampleResponse,
    SampleAnnotationsPayload,
    SampleClassificationPayload,
    SaveSampleAnnotationsRequest,
    SaveSampleAnnotationsResponse,
    SaveSampleClassificationRequest,
    SaveSampleClassificationResponse,
)
from app.services import sample_diversity
from app.services.access_window import api_key_machine_ids, apply_sample_access, sample_access_visible
from app.services.review_queue import sample_counts, sample_page, thumb_url
from app.services.sample_filters import SampleFilters, apply_sample_filters, attach_my_reviews, sample_filters_query
from app.services.channel_crop_render import render_channel_crop
from app.services.storage import delete_sample_files, serve_stored_file
from app.services.storage_backend import get_backend
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


def _get_sample_for_read(db: Session, sample_id: UUID) -> Sample:
    sample = db.query(Sample).filter(Sample.id == sample_id).first()
    if not sample:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")
    return sample


def _get_sample_for_read_scoped(db: Session, sample_id: UUID, current_user: User) -> Sample:
    """Single-sample read gated by access: members only their own machines'
    samples (404 otherwise, so they can't probe existence); reviewers/admins any."""
    sample = _get_sample_for_read(db, sample_id)
    if not sample_access_visible(db, current_user, sample):
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
    """The sources and capture reasons the filters offer, with counts: summed
    from the per-machine counts the stats worker keeps (hourly), not counted
    over the samples table on every page load."""
    counts = sample_counts(db, current_user, mine_only=scope == "mine", machine_ids=None)
    sources = counts["source_role_counts"]
    reasons = counts["capture_reason_counts"]
    return {
        "source_roles": sorted(sources),
        "source_role_counts": sources,
        "capture_reasons": sorted(reasons),
    }


@router.get("/diversity")
def get_sample_diversity(
    capture_reason: str | None = None,
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    """Diversity overview, grouped by capture_reason × source_role × piece-bucket.

    Each piece-count bucket has a target sample count (matches training/_progress targets).
    `coverage` per node is the mean of `min(count, target) / target` across buckets, multiplied
    by ``machine_factor = min(distinct_machines, machine_target) / machine_target`` — so a fully
    bucketed reason that comes from a single rig still scores below 1.0. The frontend renders
    each donut filling toward target with the machine factor surfaced separately.

    Added up from the weekly rows the stats worker keeps (services.sample_diversity,
    hourly) for the machines the caller may see, not counted over the samples table.
    """
    machines = db.query(Machine.id).filter(Machine.archived_at.is_(None))
    if scope == "mine" or current_user.role not in ("admin", "reviewer"):
        machines = machines.filter(Machine.owner_id == current_user.id)
    key_machines = api_key_machine_ids(current_user)
    if key_machines is not None:
        machines = machines.filter(Machine.id.in_(key_machines))
    return sample_diversity.overview(db, [mid for (mid,) in machines], capture_reason)


@router.get("", response_model=SamplePageResponse)
def list_samples(
    cursor: str | None = None,
    limit: int = Query(36, ge=1, le=100),
    filters: SampleFilters = Depends(sample_filters_query),
    archived: str | None = Query(None, pattern="^(active|archived|all)$"),
    scope: str | None = Query(None, pattern="^(mine|all)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    """One page of the samples the filters show, newest first, keyset-paged
    (pass next_cursor back as cursor). machine_id may be given several times.
    needs_review keeps the review queue's fresh work: samples the caller has
    not reviewed that still need reviews to reach consensus.

    A page looks at a bounded stretch of samples (review_queue.sample_page),
    so with rare filters it can come back short, or empty, with a next_cursor:
    the list goes on until next_cursor is null.

    Unless asked otherwise this shows teacher-validated samples in good light:
    raw sorter boxes are usually incomplete, and under- or overexposed frames
    are rarely worth reviewing (annotated=all and exposure=under|over opt in)."""
    # `archived` is admin-only — members never see archived samples regardless
    # of what they pass. Default ('active' or unset) hides them.
    is_admin = current_user.role == "admin"
    archived_view = archived if is_admin and archived in ("archived", "all") else "active"
    filters = filters.model_copy(
        update={"annotated": filters.annotated or "teacher", "exposure": filters.exposure or "normal"}
    )
    items, next_cursor = sample_page(
        db, current_user, filters, limit=limit, cursor=cursor, mine_only=scope == "mine", archived=archived_view
    )
    attach_my_reviews(items, db, current_user.id)
    for sample in items:
        sample.thumb_url = thumb_url(sample.image_path)
    return SamplePageResponse(
        items=[SampleResponse.model_validate(s) for s in items],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
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

    Hamming distance has no index to narrow it, so this compares the target
    against every active sample's hash, but only through
    ``ix_samples_phash_active``, which holds the hash, id and machine of each
    and nothing else: an index-only scan computing ``bit_count(phash # t)``,
    never a read of the samples table. Only the hits' rows are then loaded.
    """
    target = db.query(Sample).filter(Sample.id == sample_id).first()
    if target is None or not sample_access_visible(db, current_user, target):
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")
    if target.phash is None:
        # No hash to compare against. Return an empty list rather than
        # falling back to "newest samples" — empty is the truthful answer.
        return SampleListResponse(items=[], total=0, page=1, page_size=limit, pages=0)

    # Postgres ``#`` is bitwise XOR on integers; ``bit_count`` (14+) counts the
    # bits of a bit string, so the XOR is cast to bit(64) first.
    distance = func.bit_count(cast(Sample.phash.op("#")(int(target.phash)), BIT(64)))
    hits = (
        db.query(Sample.id)
        .filter(Sample.machine.has(Machine.archived_at.is_(None)))
        .filter(Sample.archived_at.is_(None))
        .filter(Sample.phash.isnot(None))
        .filter(Sample.id != target.id)
        .filter(distance <= int(max_distance))
    )
    # Members only get similar hits among their own machines' samples.
    hits = apply_sample_access(db, hits, current_user)
    ids = [sample_id for (sample_id,) in hits.order_by(distance, Sample.id).limit(limit)]
    by_id = {s.id: s for s in db.query(Sample).filter(Sample.id.in_(ids))} if ids else {}
    items = [by_id[i] for i in ids if i in by_id]
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
    sample = _get_sample_for_read_scoped(db, sample_id, current_user)
    attach_my_reviews([sample], db, current_user.id)

    data = SampleDetailResponse.model_validate(sample)
    data.has_full_frame = sample.full_frame_path is not None
    data.has_overlay = sample.overlay_path is not None
    data.has_channel_geometry = bool(
        sample.full_frame_path is not None
        and sample.channel_geometry is not None
        and sample.channel_geometry.polygon_x
    )
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


@router.post("/batch-archive", response_model=BatchArchiveSamplesResponse)
# Counts and then updates every sample a filter matches, up to max_archive.
@statement_timeout(seconds=60)
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
    query = apply_sample_filters(query, payload, admin.id)

    # Counted only as far as the cap: past it the answer is "too many" anyway.
    # Newest first, so the count walks the index of what the filters show
    # rather than the table from its oldest rows.
    matched = query.order_by(Sample.uploaded_at.desc(), Sample.id.desc()).limit(payload.max_archive + 1).count()

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
            f"Filter matches more than {payload.max_archive} samples — narrow the filter or raise "
            f"max_archive. Refusing to archive in one shot.",
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
# The same walk as batch-archive, over the archived ones.
@statement_timeout(seconds=60)
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
    query = apply_sample_filters(query, payload, admin.id)

    matched = query.order_by(Sample.uploaded_at.desc(), Sample.id.desc()).limit(payload.max_archive + 1).count()

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
            f"Filter matches more than {payload.max_archive} archived samples — narrow the filter "
            f"or raise max_archive.",
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
# Counts, loads and deletes every sample a filter matches, up to max_delete.
@statement_timeout(seconds=60)
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

    # The same filters as the list, through the same function: what the
    # operator sees on the page is what the destructive action operates on.
    query = apply_sample_filters(query, payload, current_user.id)

    # Counted only as far as the cap: past it the answer is "too many" anyway.
    matched = query.limit(payload.max_delete + 1).count()

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
            f"Filter matches more than {payload.max_delete} samples — narrow the filter or raise "
            f"max_delete. Refusing to delete in one shot.",
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
    sample = _get_sample_for_read_scoped(db, sample_id, current_user)

    return serve_stored_file(sample.image_path, headers={"Cache-Control": ASSET_CACHE_CONTROL})


@router.get("/{sample_id}/assets/full-frame")
def get_sample_full_frame(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_read_scoped(db, sample_id, current_user)
    if not sample.full_frame_path:
        raise APIError(404, "Full frame not found", "ASSET_NOT_FOUND")

    return serve_stored_file(sample.full_frame_path, headers={"Cache-Control": ASSET_CACHE_CONTROL})


@router.get("/{sample_id}/assets/overlay")
def get_sample_overlay(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_read_scoped(db, sample_id, current_user)
    if not sample.overlay_path:
        raise APIError(404, "Overlay not found", "ASSET_NOT_FOUND")

    return serve_stored_file(sample.overlay_path, headers={"Cache-Control": ASSET_CACHE_CONTROL})


@router.get("/{sample_id}/assets/channel-crop")
def get_sample_channel_crop(
    sample_id: UUID,
    mask: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    # Derived on demand from the retained full frame + the sample's channel
    # geometry. mask=true white-fills outside the channel polygon (distillation
    # view); mask=false keeps the raw crop rectangle.
    sample = _get_sample_for_read_scoped(db, sample_id, current_user)
    if not sample.full_frame_path:
        raise APIError(404, "Full frame not found", "ASSET_NOT_FOUND")
    geom = sample.channel_geometry
    if geom is None or not geom.polygon_x:
        raise APIError(404, "No channel geometry for this sample", "GEOMETRY_NOT_FOUND")

    raw = get_backend().read_bytes(sample.full_frame_path)
    rendered = render_channel_crop(raw, geom, mask_outside=mask)
    if rendered is None:
        raise APIError(422, "Could not render channel crop from geometry", "RENDER_FAILED")

    return Response(
        content=rendered,
        media_type="image/jpeg",
        headers={"Cache-Control": ASSET_CACHE_CONTROL},
    )
