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
from app.models.upload_session import UploadSession
from app.schemas.sample import SampleResponse
from app.schemas.upload import UploadMetadata
from app.services.storage import save_upload_file, validate_image

router = APIRouter(prefix="/api/machine", tags=["upload"])
limiter = Limiter(key_func=get_remote_address)


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
    try:
        meta = UploadMetadata.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, Exception) as e:
        raise APIError(400, f"Invalid metadata: {e}", "INVALID_METADATA")

    # Find or create upload session
    session = (
        db.query(UploadSession)
        .filter(
            UploadSession.machine_id == machine.id,
            UploadSession.source_session_id == meta.source_session_id,
        )
        .first()
    )
    if not session:
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
            if not session:
                raise

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

    # Validate and save image
    ext = validate_image(image)
    image_path = save_upload_file(
        str(machine.id), str(session.id), meta.local_sample_id, image, ext
    )

    # Save optional files
    full_frame_path = None
    if full_frame and full_frame.filename:
        ff_ext = validate_image(full_frame)
        full_frame_path = save_upload_file(
            str(machine.id), str(session.id), meta.local_sample_id, full_frame, f"_full{ff_ext}"
        )

    overlay_path = None
    if overlay and overlay.filename:
        ov_ext = validate_image(overlay)
        overlay_path = save_upload_file(
            str(machine.id), str(session.id), meta.local_sample_id, overlay, f"_overlay{ov_ext}"
        )

    # Parse captured_at
    captured_at = None
    if meta.captured_at:
        try:
            captured_at = datetime.fromisoformat(meta.captured_at)
        except ValueError:
            pass

    # Collect extra fields (explicit extra_metadata + any additional pydantic extras)
    extra = dict(meta.extra_metadata or {})
    if hasattr(meta, "model_extra") and meta.model_extra:
        extra.update(meta.model_extra)

    sample = Sample(
        machine_id=machine.id,
        upload_session_id=session.id,
        local_sample_id=meta.local_sample_id,
        source_role=meta.source_role,
        capture_reason=meta.capture_reason,
        captured_at=captured_at,
        image_path=image_path,
        full_frame_path=full_frame_path,
        overlay_path=overlay_path,
        image_width=None,
        image_height=None,
        detection_algorithm=meta.detection_algorithm,
        detection_bboxes=meta.detection_bboxes,
        detection_count=meta.detection_count,
        detection_score=meta.detection_score,
        extra_metadata=extra or None,
    )
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
