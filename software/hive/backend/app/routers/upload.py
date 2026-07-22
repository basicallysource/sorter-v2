import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_db
from app.errors import APIError
from app.models.machine import Machine
from app.models.sample import Sample
from app.models.sample_channel_geometry import SampleChannelGeometry
from app.models.upload_session import UploadSession
from app.schemas.sample import SampleResponse
from app.schemas.upload import UploadMetadata
from app.services.sample_payloads import (
    FULL_FRAME_ASSET_ID,
    OVERLAY_ASSET_ID,
    PRIMARY_IMAGE_ASSET_ID,
    build_legacy_sample_payload,
    derive_denormalized_fields,
    merge_sample_payload,
    normalize_sample_payload,
    upsert_asset,
)
from app.services.image_hashing import compute_phash_bytes
from app.services.image_stats import compute_exposure_stats_bytes
from app.services.storage import save_upload_file, validate_image

router = APIRouter(prefix="/api/machine", tags=["upload"])
limiter = Limiter(key_func=get_remote_address)


def _parse_upload_metadata(metadata: str) -> UploadMetadata:
    try:
        return UploadMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, Exception) as exc:
        raise APIError(400, f"Invalid metadata: {exc}", "INVALID_METADATA") from exc


def _num(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _build_channel_geometry(meta: UploadMetadata) -> SampleChannelGeometry | None:
    """Parse the machine's per-sample channel geometry into typed columns. The
    wire shape mirrors the sorter's channel_polygons blob for one source_role:
    polygon as a list of [x, y] points, center as [cx, cy], radii/angles flat,
    and arc_zones as a list of {zone_type, start/end outer+inner angles}.
    Returns None when the payload carries no usable geometry.
    """
    geom = meta.channel_geometry
    if not isinstance(geom, dict):
        return None

    polygon_x: list[float] | None = None
    polygon_y: list[float] | None = None
    polygon = geom.get("polygon")
    if isinstance(polygon, list) and polygon:
        xs: list[float] = []
        ys: list[float] = []
        for point in polygon:
            if isinstance(point, (list, tuple)) and len(point) >= 2:
                x = _num(point[0])
                y = _num(point[1])
                if x is not None and y is not None:
                    xs.append(x)
                    ys.append(y)
        if xs:
            polygon_x, polygon_y = xs, ys

    center = geom.get("center")
    center_x = center_y = None
    if isinstance(center, (list, tuple)) and len(center) >= 2:
        center_x = _num(center[0])
        center_y = _num(center[1])

    source_role = geom.get("source_role")
    reverse = geom.get("reverse")
    row = SampleChannelGeometry(
        source_role=source_role if isinstance(source_role, str) else meta.source_role,
        frame_width=_int(geom.get("frame_width")),
        frame_height=_int(geom.get("frame_height")),
        polygon_x=polygon_x,
        polygon_y=polygon_y,
        center_x=center_x,
        center_y=center_y,
        inner_radius=_num(geom.get("inner_radius")),
        outer_radius=_num(geom.get("outer_radius")),
        exit_outer_radius=_num(geom.get("exit_outer_radius")),
        section_zero_angle_deg=_num(geom.get("section_zero_angle_deg")),
        reverse=reverse if isinstance(reverse, bool) else None,
    )

    arc_zones = geom.get("arc_zones")
    if isinstance(arc_zones, list):
        for zone in arc_zones:
            if not isinstance(zone, dict):
                continue
            zone_type = zone.get("zone_type")
            if zone_type not in ("drop", "exit", "precise"):
                continue
            setattr(row, f"{zone_type}_start_outer_angle", _num(zone.get("start_outer_angle")))
            setattr(row, f"{zone_type}_end_outer_angle", _num(zone.get("end_outer_angle")))
            setattr(row, f"{zone_type}_start_inner_angle", _num(zone.get("start_inner_angle")))
            setattr(row, f"{zone_type}_end_inner_angle", _num(zone.get("end_inner_angle")))

    if polygon_x is None and center_x is None and row.outer_radius is None:
        return None
    return row


def _get_or_create_upload_session(db: Session, machine: Machine, meta: UploadMetadata) -> UploadSession:
    session = (
        db.query(UploadSession)
        .filter(
            UploadSession.machine_id == machine.id,
            UploadSession.source_session_id == meta.source_session_id,
        )
        .first()
    )
    if session:
        return session

    session = UploadSession(
        machine_id=machine.id,
        source_session_id=meta.source_session_id,
        name=meta.session_name,
    )
    db.add(session)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        session = (
            db.query(UploadSession)
            .filter(
                UploadSession.machine_id == machine.id,
                UploadSession.source_session_id == meta.source_session_id,
            )
            .first()
        )
        if session is None:
            raise
    return session


def _parse_captured_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _collect_extra_metadata(meta: UploadMetadata) -> dict:
    extra = dict(meta.extra_metadata or {})
    if hasattr(meta, "model_extra") and meta.model_extra:
        extra.update(meta.model_extra)
    return extra


def _build_payload_from_meta(meta: UploadMetadata, extra_metadata: dict) -> dict:
    if isinstance(meta.sample_payload, dict):
        return normalize_sample_payload(
            meta.sample_payload,
            source_session_id=meta.source_session_id,
            local_sample_id=meta.local_sample_id,
        )
    return build_legacy_sample_payload(
        source_session_id=meta.source_session_id,
        local_sample_id=meta.local_sample_id,
        source_role=meta.source_role,
        capture_reason=meta.capture_reason,
        captured_at=meta.captured_at,
        detection_algorithm=meta.detection_algorithm,
        detection_bboxes=meta.detection_bboxes,
        detection_count=meta.detection_count,
        detection_score=meta.detection_score,
        extra_metadata=extra_metadata or None,
    )


def _upload_optional_file(
    *,
    machine: Machine,
    session: UploadSession,
    sample_id: str,
    file: UploadFile | None,
    suffix: str,
) -> tuple[str | None, str | None]:
    if file is None or not file.filename:
        return None, None
    ext = validate_image(file)
    stored_path = save_upload_file(str(machine.id), str(session.id), sample_id, file, f"{suffix}{ext}")
    return stored_path, file.content_type or None


def _attach_uploaded_assets(
    payload: dict,
    *,
    image_path: str,
    image_content_type: str | None,
    full_frame_path: str | None = None,
    full_frame_content_type: str | None = None,
    overlay_path: str | None = None,
    overlay_content_type: str | None = None,
) -> dict:
    preferred_view = payload.get("sample", {}).get("preferred_view")
    payload = upsert_asset(
        payload,
        asset_id=PRIMARY_IMAGE_ASSET_ID,
        stored_path=image_path,
        kind="crop",
        role="primary",
        mime_type=image_content_type,
        view=preferred_view if isinstance(preferred_view, str) else None,
    )
    if full_frame_path:
        payload = upsert_asset(
            payload,
            asset_id=FULL_FRAME_ASSET_ID,
            stored_path=full_frame_path,
            kind="full_frame",
            role="context",
            mime_type=full_frame_content_type,
            view=preferred_view if isinstance(preferred_view, str) else None,
        )
    if overlay_path:
        payload = upsert_asset(
            payload,
            asset_id=OVERLAY_ASSET_ID,
            stored_path=overlay_path,
            kind="overlay",
            role="analysis_artifact",
            mime_type=overlay_content_type,
            view=preferred_view if isinstance(preferred_view, str) else None,
            derived_from_asset_id=PRIMARY_IMAGE_ASSET_ID,
        )
    return payload


def _apply_payload_to_sample(
    sample: Sample,
    *,
    payload: dict,
    extra_metadata: dict | None,
    image_path: str,
    full_frame_path: str | None,
    overlay_path: str | None,
    fallback: dict,
) -> None:
    derived = derive_denormalized_fields(payload, fallback=fallback)
    sample.source_role = derived.get("source_role")
    sample.capture_reason = derived.get("capture_reason")
    sample.captured_at = _parse_captured_at(derived.get("captured_at"))
    sample.image_path = image_path
    sample.full_frame_path = full_frame_path
    sample.overlay_path = overlay_path
    sample.image_width = None
    sample.image_height = None
    sample.detection_algorithm = derived.get("detection_algorithm")
    sample.detection_bboxes = derived.get("detection_bboxes")
    sample.detection_count = derived.get("detection_count")
    sample.detection_score = derived.get("detection_score")
    sample.sample_payload = payload
    sample.extra_metadata = extra_metadata or None


@router.post("/upload", response_model=SampleResponse)
@limiter.limit("200/minute")
def upload_sample(
    request: Request,
    metadata: str = Form(...),
    image: UploadFile = File(...),
    full_frame: UploadFile | None = File(default=None),
    overlay: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    meta = _parse_upload_metadata(metadata)
    session = _get_or_create_upload_session(db, machine, meta)

    # Idempotency check
    existing = (
        db.query(Sample)
        .filter(
            Sample.upload_session_id == session.id,
            Sample.local_sample_id == meta.local_sample_id,
        )
        .first()
    )
    if existing:
        db.commit()
        return existing

    ext = validate_image(image)
    # Read the upload bytes once, compute pHash + exposure stats from the
    # same buffer, then hand the rewound stream to save_upload_file. Saves
    # one decode pass vs. running each helper independently.
    image.file.seek(0)
    image_bytes = image.file.read()
    image.file.seek(0)
    phash = compute_phash_bytes(image_bytes)
    exposure = compute_exposure_stats_bytes(image_bytes)
    image_path = save_upload_file(
        str(machine.id), str(session.id), meta.local_sample_id, image, ext
    )
    image_content_type = image.content_type or None

    full_frame_path, full_frame_content_type = _upload_optional_file(
        machine=machine,
        session=session,
        sample_id=meta.local_sample_id,
        file=full_frame,
        suffix="_full",
    )
    overlay_path, overlay_content_type = _upload_optional_file(
        machine=machine,
        session=session,
        sample_id=meta.local_sample_id,
        file=overlay,
        suffix="_overlay",
    )

    extra = _collect_extra_metadata(meta)
    payload = _build_payload_from_meta(meta, extra)
    payload = _attach_uploaded_assets(
        payload,
        image_path=image_path,
        image_content_type=image_content_type,
        full_frame_path=full_frame_path,
        full_frame_content_type=full_frame_content_type,
        overlay_path=overlay_path,
        overlay_content_type=overlay_content_type,
    )

    sample = Sample(
        machine_id=machine.id,
        upload_session_id=session.id,
        local_sample_id=meta.local_sample_id,
        image_path=image_path,
        full_frame_path=full_frame_path,
        overlay_path=overlay_path,
        phash=phash,
        luminance_mean=exposure.luminance_mean if exposure else None,
        luminance_p05=exposure.luminance_p05 if exposure else None,
        luminance_p95=exposure.luminance_p95 if exposure else None,
        clipped_low_ratio=exposure.clipped_low_ratio if exposure else None,
        clipped_high_ratio=exposure.clipped_high_ratio if exposure else None,
    )
    _apply_payload_to_sample(
        sample,
        payload=payload,
        extra_metadata=extra or None,
        image_path=image_path,
        full_frame_path=full_frame_path,
        overlay_path=overlay_path,
        fallback={
            "source_role": meta.source_role,
            "capture_reason": meta.capture_reason,
            "captured_at": meta.captured_at,
            "detection_algorithm": meta.detection_algorithm,
            "detection_bboxes": meta.detection_bboxes,
            "detection_count": meta.detection_count,
            "detection_score": meta.detection_score,
        },
    )
    sample.channel_geometry = _build_channel_geometry(meta)
    db.add(sample)

    session.sample_count += 1
    session.last_upload_at = datetime.now(timezone.utc)
    machine.last_seen_at = datetime.now(timezone.utc)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Sample)
            .filter(
                Sample.upload_session_id == session.id,
                Sample.local_sample_id == meta.local_sample_id,
            )
            .first()
        )
        if existing:
            return existing
        raise
    db.refresh(sample)
    return sample


@router.patch("/upload/{source_session_id}/{local_sample_id}", response_model=SampleResponse)
@limiter.limit("200/minute")
def patch_sample(
    request: Request,
    source_session_id: str,
    local_sample_id: str,
    metadata: str = Form(...),
    image: UploadFile | None = File(default=None),
    full_frame: UploadFile | None = File(default=None),
    overlay: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
):
    meta = _parse_upload_metadata(metadata)
    if meta.source_session_id != source_session_id or meta.local_sample_id != local_sample_id:
        raise APIError(400, "Route and metadata sample identifiers do not match.", "SAMPLE_ID_MISMATCH")

    session = _get_or_create_upload_session(db, machine, meta)
    sample = (
        db.query(Sample)
        .filter(
            Sample.upload_session_id == session.id,
            Sample.local_sample_id == local_sample_id,
        )
        .first()
    )
    if sample is None:
        raise APIError(404, "Sample not found", "SAMPLE_NOT_FOUND")

    extra_patch = _collect_extra_metadata(meta)
    merged_extra = dict(sample.extra_metadata or {})
    merged_extra.update(extra_patch)

    payload_patch = _build_payload_from_meta(meta, extra_patch)
    payload = merge_sample_payload(sample.sample_payload, payload_patch)

    image_path = sample.image_path
    full_frame_path = sample.full_frame_path
    overlay_path = sample.overlay_path

    image_content_type = None
    if image and image.filename:
        ext = validate_image(image)
        image.file.seek(0)
        new_image_bytes = image.file.read()
        image.file.seek(0)
        sample.phash = compute_phash_bytes(new_image_bytes)
        new_exposure = compute_exposure_stats_bytes(new_image_bytes)
        if new_exposure is not None:
            sample.luminance_mean = new_exposure.luminance_mean
            sample.luminance_p05 = new_exposure.luminance_p05
            sample.luminance_p95 = new_exposure.luminance_p95
            sample.clipped_low_ratio = new_exposure.clipped_low_ratio
            sample.clipped_high_ratio = new_exposure.clipped_high_ratio
        image_path = save_upload_file(str(machine.id), str(session.id), local_sample_id, image, ext)
        image_content_type = image.content_type or None

    uploaded_full_frame_path, full_frame_content_type = _upload_optional_file(
        machine=machine,
        session=session,
        sample_id=local_sample_id,
        file=full_frame,
        suffix="_full",
    )
    if uploaded_full_frame_path:
        full_frame_path = uploaded_full_frame_path

    uploaded_overlay_path, overlay_content_type = _upload_optional_file(
        machine=machine,
        session=session,
        sample_id=local_sample_id,
        file=overlay,
        suffix="_overlay",
    )
    if uploaded_overlay_path:
        overlay_path = uploaded_overlay_path

    payload = _attach_uploaded_assets(
        payload,
        image_path=image_path,
        image_content_type=image_content_type,
        full_frame_path=full_frame_path,
        full_frame_content_type=full_frame_content_type,
        overlay_path=overlay_path,
        overlay_content_type=overlay_content_type,
    )

    _apply_payload_to_sample(
        sample,
        payload=payload,
        extra_metadata=merged_extra or None,
        image_path=image_path,
        full_frame_path=full_frame_path,
        overlay_path=overlay_path,
        fallback={
            "source_role": sample.source_role or meta.source_role,
            "capture_reason": sample.capture_reason or meta.capture_reason,
            "captured_at": meta.captured_at or (sample.captured_at.isoformat() if sample.captured_at else None),
            "detection_algorithm": meta.detection_algorithm or sample.detection_algorithm,
            "detection_bboxes": meta.detection_bboxes or sample.detection_bboxes,
            "detection_count": meta.detection_count if meta.detection_count is not None else sample.detection_count,
            "detection_score": meta.detection_score if meta.detection_score is not None else sample.detection_score,
        },
    )
    db.add(sample)
    session.last_upload_at = datetime.now(timezone.utc)
    machine.last_seen_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(sample)
    return sample
