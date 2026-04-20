import math
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, Query
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
from app.services.storage import delete_sample_files, serve_stored_file
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
        "capture_reasons": capture_reasons,
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

    return serve_stored_file(sample.image_path, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{sample_id}/assets/full-frame")
def get_sample_full_frame(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_user(db, sample_id, current_user)
    if not sample or not sample.full_frame_path:
        raise APIError(404, "Full frame not found", "ASSET_NOT_FOUND")

    return serve_stored_file(sample.full_frame_path, headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{sample_id}/assets/overlay")
def get_sample_overlay(
    sample_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_api_key_scopes(API_KEY_SCOPE_SAMPLES_READ)),
):
    sample = _get_sample_for_user(db, sample_id, current_user)
    if not sample or not sample.overlay_path:
        raise APIError(404, "Overlay not found", "ASSET_NOT_FOUND")

    return serve_stored_file(sample.overlay_path, headers={"Cache-Control": "public, max-age=86400"})
