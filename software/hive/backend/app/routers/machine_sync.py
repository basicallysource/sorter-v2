import io
import json
import math
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from PIL import Image
from pydantic import BaseModel, field_validator
from sqlalchemy import or_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_db
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.machine_piece_rejection_reason import MachinePieceRejectionReason
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_control_data_segment import MachineControlDataSegment
from app.models.machine_sync_state import MachineSyncState
from app.models.sample import Sample
from app.rate_limiting import machine_limiter
from app.routers.upload import (
    _apply_payload_to_sample,
    _attach_uploaded_assets,
    _build_channel_geometry,
    _build_payload_from_meta,
    _count_sample_in_session,
    _find_sample,
    _find_upload_session,
    _get_or_create_upload_session,
)
from app.schemas.upload import UploadMetadata
from app.services.image_hashing import compute_phash_bytes
from app.services.image_stats import compute_exposure_stats_bytes
from app.services.machine_presence import mark_machine_seen
from app.services.storage import (
    save_channel_crop_file,
    save_piece_image_file,
    save_control_data_file,
    save_sample_frame_file,
    validate_gzip,
    validate_image,
)

router = APIRouter(prefix="/api/machine/sync", tags=["machine-sync"])
# Keyed per machine token, not per address; shared with the upload routes.
limiter = machine_limiter

DATA_TYPE_PIECE_RECORDS = "piece_records"
DATA_TYPE_PIECE_IMAGES = "piece_images"
DATA_TYPE_CHANNEL_CROPS = "channel_crops"
DATA_TYPE_PIECE_CORRECTIONS = "piece_corrections"
DATA_TYPE_CONTROL_DATA = "control_data_segments"
DATA_TYPE_SAMPLES = "samples"

# Columns updated on conflict — everything except the identity/immutable set
# (id, machine_id, piece_uuid[, seq], created_at). The correction columns
# (part_correct, color_corrected_id, *_feedback_submitted, correction_updated_at)
# are intentionally NOT here: they arrive on the separate piece_corrections
# stream, so a plain piece_records re-sync must not clobber them.
_PIECE_UPDATE_COLS = (
    "local_id", "run_id", "seen_at", "recorded_at", "classification_status",
    "part_id", "part_name", "color_id", "color_name", "category_id", "confidence",
    "color_confidence", "bin_x", "bin_y", "bin_z", "dead", "brickognize_preview_url",
    "brickognize_listing_id", "brickognize_item_rank", "brickognize_item_type",
    "brickognize_color_rank", "color_provider", "mold_provider",
)
_IMAGE_UPDATE_COLS = (
    "local_id", "source", "channel", "ts", "captured_at", "sharpness", "bytes",
    "used", "excluded_from_result", "score", "image_key", "evicted_locally",
)
_CHANNEL_CROP_UPDATE_COLS = (
    "channel", "ts", "captured_at", "track_id", "com_forward_to_exit_deg",
    "com_section", "zone_code", "sharpness", "bbox_x1", "bbox_y1", "bbox_x2",
    "bbox_y2", "bytes", "image_key", "evicted_locally",
)
_CONTROL_DATA_UPDATE_COLS = (
    "started_at", "ended_at", "records", "bytes", "machine_setup",
    "feeder_mode", "classification_mode", "autotune_mode", "data_key",
    "evicted_locally",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: float | int | None) -> datetime | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return datetime.fromtimestamp(f, tz=timezone.utc)


def _upsert(db: Session, model, rows: list[dict[str, Any]], index_elements: list[str], update_cols) -> None:
    if not rows:
        return
    ins = pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    stmt = ins(model).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=index_elements,
        set_={col: getattr(stmt.excluded, col) for col in update_cols},
    )
    db.execute(stmt)


def _advance_watermark(db: Session, machine_id: UUID, data_type: str, new_max: int) -> int:
    row = (
        db.query(MachineSyncState)
        .filter(MachineSyncState.machine_id == machine_id, MachineSyncState.data_type == data_type)
        .first()
    )
    if row is None:
        row = MachineSyncState(machine_id=machine_id, data_type=data_type, max_local_id=new_max, updated_at=_now())
        db.add(row)
    else:
        if new_max > row.max_local_id:
            row.max_local_id = new_max
        row.updated_at = _now()
    return row.max_local_id


class PieceRecordIn(BaseModel):
    piece_uuid: str
    local_id: int
    run_id: str | None = None
    seen_at: float | None = None
    recorded_at: float | None = None
    classification_status: str | None = None
    part_id: str | None = None
    part_name: str | None = None
    color_id: str | None = None
    color_name: str | None = None
    category_id: str | None = None
    # Mold score and the applied color's own score — separate providers can
    # produce them, so they are never interchangeable.
    confidence: float | None = None
    color_confidence: float | None = None
    bin_x: int | None = None
    bin_y: int | None = None
    bin_z: int | None = None
    dead: bool = False
    brickognize_preview_url: str | None = None
    brickognize_listing_id: str | None = None
    brickognize_item_rank: int | None = None
    brickognize_item_type: str | None = None
    brickognize_color_rank: int | None = None
    color_provider: str | None = None
    mold_provider: str | None = None


class PieceRecordsBatch(BaseModel):
    records: list[PieceRecordIn]


class PieceCorrectionIn(BaseModel):
    piece_uuid: str
    local_id: int
    part_correct: bool | None = None
    color_corrected_id: str | None = None
    part_feedback_submitted: bool = False
    color_feedback_submitted: bool = False
    updated_at: float | None = None
    # Operator-flagged sample attributes (no_piece / multiple_pieces / not_lego /
    # assembly / pieces_entangled / blurry) — same codes as piece_rejections.reasons.
    rejection_reasons: list[str] | None = None


class PieceCorrectionsBatch(BaseModel):
    records: list[PieceCorrectionIn]


class PieceImageMeta(BaseModel):
    piece_uuid: str
    seq: int
    local_id: int
    source: str | None = None
    channel: int | None = None
    ts: float | None = None
    captured_at: float | None = None
    sharpness: float | None = None
    bytes: int | None = None
    used: bool = False
    excluded_from_result: bool = False
    score: float | None = None


class ControlDataSegmentMeta(BaseModel):
    local_id: int
    created_at: float | None = None
    started_at: float | None = None
    ended_at: float | None = None
    records: int | None = None
    bytes: int | None = None
    machine_setup: str | None = None
    feeder_mode: str | None = None
    classification_mode: str | None = None
    autotune_mode: str | None = None


class ChannelCropMeta(BaseModel):
    local_id: int
    channel: int | None = None
    ts: float | None = None
    captured_at: float | None = None
    track_id: int | None = None
    com_forward_to_exit_deg: float | None = None
    com_section: int | None = None
    zone_code: int | None = None
    sharpness: float | None = None
    bbox: list[int] | None = None
    bytes: int | None = None


class SampleMeta(BaseModel):
    """One training sample: a full camera frame plus what the machine knew
    about it when it was captured."""

    local_id: int
    source_session_id: str
    local_sample_id: str
    source_role: str
    # Epoch seconds, or an ISO 8601 string.
    captured_at: float | str
    capture_reason: str
    session_name: str | None = None
    detection_algorithm: str | None = None
    detection_bboxes: list | None = None
    detection_count: int | None = None
    detection_score: float | None = None
    # The channel-region geometry for this frame, in the same shape the upload
    # route accepts (see routers.upload._build_channel_geometry).
    channel_geometry: dict | None = None
    # Free-form: camera settings, lamp state, and software versions at capture
    # time. Each lands in the sample's extra_metadata under its own key.
    camera: dict | None = None
    lamp: dict | None = None
    software: dict | None = None
    extra_metadata: dict | None = None

    @field_validator("source_session_id", "local_sample_id")
    @classmethod
    def _single_path_segment(cls, value: str) -> str:
        # Both name the stored file, so neither may climb out of its folder.
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty")
        if normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
            raise ValueError("must be a single path segment")
        return normalized


@router.get("/state")
def get_sync_state(
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, dict[str, int]]:
    rows = db.query(MachineSyncState).filter(MachineSyncState.machine_id == machine.id).all()
    by_type = {r.data_type: r.max_local_id for r in rows}
    return {
        DATA_TYPE_PIECE_RECORDS: {"max_local_id": by_type.get(DATA_TYPE_PIECE_RECORDS, 0)},
        DATA_TYPE_PIECE_IMAGES: {"max_local_id": by_type.get(DATA_TYPE_PIECE_IMAGES, 0)},
        DATA_TYPE_CHANNEL_CROPS: {"max_local_id": by_type.get(DATA_TYPE_CHANNEL_CROPS, 0)},
        DATA_TYPE_PIECE_CORRECTIONS: {"max_local_id": by_type.get(DATA_TYPE_PIECE_CORRECTIONS, 0)},
        DATA_TYPE_CONTROL_DATA: {"max_local_id": by_type.get(DATA_TYPE_CONTROL_DATA, 0)},
        DATA_TYPE_SAMPLES: {"max_local_id": by_type.get(DATA_TYPE_SAMPLES, 0)},
    }


@router.post("/piece-records")
@limiter.limit("300/minute")
def sync_piece_records(
    request: Request,
    payload: PieceRecordsBatch,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, int]:
    if not payload.records:
        row = (
            db.query(MachineSyncState)
            .filter(MachineSyncState.machine_id == machine.id, MachineSyncState.data_type == DATA_TYPE_PIECE_RECORDS)
            .first()
        )
        return {"max_local_id": row.max_local_id if row else 0, "upserted": 0}

    now = _now()
    rows: list[dict[str, Any]] = []
    batch_max = 0
    for rec in payload.records:
        batch_max = max(batch_max, rec.local_id)
        rows.append(
            {
                "id": uuid4(),
                "machine_id": machine.id,
                "piece_uuid": rec.piece_uuid,
                "local_id": rec.local_id,
                "run_id": rec.run_id,
                "seen_at": _ts(rec.seen_at),
                "recorded_at": _ts(rec.recorded_at),
                "classification_status": rec.classification_status,
                "part_id": rec.part_id,
                "part_name": rec.part_name,
                "color_id": rec.color_id,
                "color_name": rec.color_name,
                "category_id": rec.category_id,
                "confidence": rec.confidence,
                "color_confidence": rec.color_confidence,
                "bin_x": rec.bin_x,
                "bin_y": rec.bin_y,
                "bin_z": rec.bin_z,
                "dead": rec.dead,
                "brickognize_preview_url": rec.brickognize_preview_url,
                "brickognize_listing_id": rec.brickognize_listing_id,
                "brickognize_item_rank": rec.brickognize_item_rank,
                "brickognize_item_type": rec.brickognize_item_type,
                "brickognize_color_rank": rec.brickognize_color_rank,
                "color_provider": rec.color_provider,
                "mold_provider": rec.mold_provider,
                "created_at": now,
            }
        )

    _upsert(db, MachinePiece, rows, ["machine_id", "piece_uuid"], _PIECE_UPDATE_COLS)
    new_max = _advance_watermark(db, machine.id, DATA_TYPE_PIECE_RECORDS, batch_max)
    machine.last_seen_at = now
    db.commit()
    return {"max_local_id": new_max, "upserted": len(rows)}


@router.post("/piece-corrections")
@limiter.limit("300/minute")
def sync_piece_corrections(
    request: Request,
    payload: PieceCorrectionsBatch,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, int]:
    if not payload.records:
        row = (
            db.query(MachineSyncState)
            .filter(
                MachineSyncState.machine_id == machine.id,
                MachineSyncState.data_type == DATA_TYPE_PIECE_CORRECTIONS,
            )
            .first()
        )
        return {"max_local_id": row.max_local_id if row else 0, "upserted": 0}

    now = _now()
    batch_max = 0
    upserted = 0
    # Update-only onto the existing machine_pieces row (the correction stream
    # carries no piece identity beyond the uuid). The piece is always classified
    # and synced before it can be corrected, so the row exists. The submitted
    # flags are OR'd, never overwritten, so a correction already submitted on Hive
    # is not un-marked by a later machine re-sync (one-way sync, no flag regress).
    for rec in payload.records:
        batch_max = max(batch_max, rec.local_id)
        result = db.execute(
            update(MachinePiece)
            .where(
                MachinePiece.machine_id == machine.id,
                MachinePiece.piece_uuid == rec.piece_uuid,
            )
            .values(
                part_correct=rec.part_correct,
                color_corrected_id=rec.color_corrected_id,
                part_feedback_submitted=or_(
                    MachinePiece.part_feedback_submitted, rec.part_feedback_submitted
                ),
                color_feedback_submitted=or_(
                    MachinePiece.color_feedback_submitted, rec.color_feedback_submitted
                ),
                correction_updated_at=_ts(rec.updated_at) or now,
            )
        )
        upserted += int(result.rowcount or 0)
        # Capture-issue flags: replace-all per piece, since the machine sends the
        # complete set it wants on every edit. None means the machine predates the
        # field and isn't reporting flags — leave whatever is already there rather
        # than reading "not reported" as "operator cleared them".
        if result.rowcount and rec.rejection_reasons is not None:
            db.query(MachinePieceRejectionReason).filter(
                MachinePieceRejectionReason.machine_id == machine.id,
                MachinePieceRejectionReason.piece_uuid == rec.piece_uuid,
            ).delete(synchronize_session=False)
            for reason in dict.fromkeys(rec.rejection_reasons):
                db.add(
                    MachinePieceRejectionReason(
                        machine_id=machine.id,
                        piece_uuid=rec.piece_uuid,
                        reason=reason,
                        created_at=now,
                    )
                )

    new_max = _advance_watermark(db, machine.id, DATA_TYPE_PIECE_CORRECTIONS, batch_max)
    machine.last_seen_at = now
    db.commit()
    return {"max_local_id": new_max, "upserted": upserted}


@router.post("/piece-image")
@limiter.limit("600/minute")
def sync_piece_image(
    request: Request,
    metadata: str = Form(...),
    image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, Any]:
    try:
        meta = PieceImageMeta.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        raise APIError(400, f"Invalid metadata: {exc}", "INVALID_METADATA") from exc

    # Piece images are ground truth ("these pixels ARE the piece") and feed the
    # labeling galleries and training exports. Piece-link model GUESSES must
    # never enter that pipeline — refuse them here regardless of what the
    # machine's software version sends, but ack with an advanced watermark so an
    # un-updated sorter drains past them instead of retrying forever.
    if meta.source == "link_match":
        new_max = _advance_watermark(db, machine.id, DATA_TYPE_PIECE_IMAGES, meta.local_id)
        machine.last_seen_at = _now()
        db.commit()
        return {"max_local_id": new_max, "image_stored": False, "rejected_source": "link_match"}

    image_key: str | None = None
    evicted_locally = image is None
    if image is not None:
        suffix = validate_image(image)
        image_key = save_piece_image_file(str(machine.id), meta.piece_uuid, meta.seq, meta.source, image, suffix)

    now = _now()
    row = {
        "id": uuid4(),
        "machine_id": machine.id,
        "piece_uuid": meta.piece_uuid,
        "seq": meta.seq,
        "local_id": meta.local_id,
        "source": meta.source,
        "channel": meta.channel,
        "ts": _ts(meta.ts),
        "captured_at": _ts(meta.captured_at),
        "sharpness": meta.sharpness,
        "bytes": meta.bytes,
        "used": meta.used,
        "excluded_from_result": meta.excluded_from_result,
        "score": meta.score,
        "image_key": image_key,
        "evicted_locally": evicted_locally,
        "created_at": now,
    }
    # Metadata-only re-sends must not wipe a previously stored image_key.
    update_cols = _IMAGE_UPDATE_COLS if image is not None else tuple(c for c in _IMAGE_UPDATE_COLS if c != "image_key")
    _upsert(db, MachinePieceImage, [row], ["machine_id", "piece_uuid", "seq"], update_cols)
    new_max = _advance_watermark(db, machine.id, DATA_TYPE_PIECE_IMAGES, meta.local_id)
    machine.last_seen_at = now
    db.commit()
    return {"max_local_id": new_max, "image_stored": image is not None}


@router.post("/channel-crop")
@limiter.limit("1200/minute")
def sync_channel_crop(
    request: Request,
    metadata: str = Form(...),
    image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, Any]:
    try:
        meta = ChannelCropMeta.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        raise APIError(400, f"Invalid metadata: {exc}", "INVALID_METADATA") from exc

    image_key: str | None = None
    evicted_locally = image is None
    if image is not None:
        suffix = validate_image(image)
        image_key = save_channel_crop_file(str(machine.id), meta.local_id, meta.channel, image, suffix)

    bbox = meta.bbox if (meta.bbox and len(meta.bbox) == 4) else [None, None, None, None]
    now = _now()
    row = {
        "id": uuid4(),
        "machine_id": machine.id,
        "local_id": meta.local_id,
        "channel": meta.channel,
        "ts": _ts(meta.ts),
        "captured_at": _ts(meta.captured_at),
        "track_id": meta.track_id,
        "com_forward_to_exit_deg": meta.com_forward_to_exit_deg,
        "com_section": meta.com_section,
        "zone_code": meta.zone_code,
        "sharpness": meta.sharpness,
        "bbox_x1": bbox[0],
        "bbox_y1": bbox[1],
        "bbox_x2": bbox[2],
        "bbox_y2": bbox[3],
        "bytes": meta.bytes,
        "image_key": image_key,
        "evicted_locally": evicted_locally,
        "created_at": now,
    }
    # Metadata-only re-sends must not wipe a previously stored image_key.
    update_cols = _CHANNEL_CROP_UPDATE_COLS if image is not None else tuple(c for c in _CHANNEL_CROP_UPDATE_COLS if c != "image_key")
    _upsert(db, MachineChannelCrop, [row], ["machine_id", "local_id"], update_cols)
    new_max = _advance_watermark(db, machine.id, DATA_TYPE_CHANNEL_CROPS, meta.local_id)
    machine.last_seen_at = now
    db.commit()
    return {"max_local_id": new_max, "image_stored": image is not None}


@router.post("/control-data-segment")
@limiter.limit("120/minute")
def sync_control_data_segment(
    request: Request,
    metadata: str = Form(...),
    data: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, Any]:
    try:
        meta = ControlDataSegmentMeta.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        raise APIError(400, f"Invalid metadata: {exc}", "INVALID_METADATA") from exc

    data_key: str | None = None
    evicted_locally = data is None
    if data is not None:
        validate_gzip(data)
        data_key = save_control_data_file(str(machine.id), meta.local_id, data)

    now = _now()
    row = {
        "id": uuid4(),
        "machine_id": machine.id,
        "local_id": meta.local_id,
        "started_at": _ts(meta.started_at),
        "ended_at": _ts(meta.ended_at),
        "records": meta.records,
        "bytes": meta.bytes,
        "machine_setup": meta.machine_setup,
        "feeder_mode": meta.feeder_mode,
        "classification_mode": meta.classification_mode,
        "autotune_mode": meta.autotune_mode,
        "data_key": data_key,
        "evicted_locally": evicted_locally,
        "created_at": now,
    }
    # Metadata-only re-sends must not wipe a previously stored data_key.
    update_cols = _CONTROL_DATA_UPDATE_COLS if data is not None else tuple(c for c in _CONTROL_DATA_UPDATE_COLS if c != "data_key")
    _upsert(db, MachineControlDataSegment, [row], ["machine_id", "local_id"], update_cols)
    new_max = _advance_watermark(db, machine.id, DATA_TYPE_CONTROL_DATA, meta.local_id)
    machine.last_seen_at = now
    db.commit()
    return {"max_local_id": new_max, "data_stored": data is not None}


def _captured_at_iso(value: float | str) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    moment = _ts(value)
    return moment.isoformat() if moment else None


def _sample_extra_metadata(meta: SampleMeta) -> dict[str, Any]:
    extra = dict(meta.extra_metadata or {})
    for key in ("camera", "lamp", "software"):
        value = getattr(meta, key)
        if value is None:
            continue
        current = extra.get(key)
        extra[key] = {**current, **value} if isinstance(current, dict) else dict(value)
    return extra


def _image_size(image_bytes: bytes) -> tuple[int | None, int | None]:
    # Reads the header only; the pixels are not decoded.
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
    except Exception:
        return None, None
    return int(width), int(height)


@router.post("/sample")
@limiter.limit("120/minute")
def sync_sample(
    request: Request,
    metadata: str = Form(...),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, Any]:
    """A training sample: one full camera frame (JPEG) and its metadata.

    Stored as a sample the review and teacher pipelines read like any other.
    The one image is the full frame, so it is both the sample's image and its
    full frame, which is what lets Hive cut the channel crop out of it with the
    sample's channel geometry. A re-send of a stored sample (same session and
    local_sample_id) changes nothing and still advances the watermark.
    """
    try:
        meta = SampleMeta.model_validate(json.loads(metadata))
    except (json.JSONDecodeError, ValueError) as exc:
        raise APIError(400, f"Invalid metadata: {exc}", "INVALID_METADATA") from exc

    if validate_image(image) != ".jpg":
        raise APIError(400, "A sample image must be a JPEG.", "INVALID_IMAGE_FORMAT")
    image.file.seek(0)
    image_bytes = image.file.read()
    image.file.seek(0)
    phash = compute_phash_bytes(image_bytes)
    exposure = compute_exposure_stats_bytes(image_bytes)
    width, height = _image_size(image_bytes)

    # No transaction may stay open while the frame travels to storage: end the
    # read the machine-token lookup began, then write the file under a key that
    # needs nothing from the database.
    machine_id = machine.id
    db.commit()
    image_path = save_sample_frame_file(str(machine_id), meta.source_session_id, meta.local_sample_id, image)

    extra = _sample_extra_metadata(meta)
    upload_meta = UploadMetadata(
        source_session_id=meta.source_session_id,
        local_sample_id=meta.local_sample_id,
        source_role=meta.source_role,
        capture_reason=meta.capture_reason,
        captured_at=_captured_at_iso(meta.captured_at),
        session_name=meta.session_name,
        detection_algorithm=meta.detection_algorithm,
        detection_bboxes=meta.detection_bboxes,
        detection_count=meta.detection_count,
        detection_score=meta.detection_score,
        extra_metadata=extra or None,
        channel_geometry=meta.channel_geometry,
    )
    payload = _build_payload_from_meta(upload_meta, extra)
    payload = _attach_uploaded_assets(
        payload,
        image_path=image_path,
        image_content_type="image/jpeg",
        full_frame_path=image_path,
        full_frame_content_type="image/jpeg",
        primary_kind="full_frame",
    )

    # The one short transaction: session, sample, count, watermark.
    now = _now()
    session = _get_or_create_upload_session(db, machine, upload_meta)
    session_id = session.id
    existing = _find_sample(db, session_id, meta.local_sample_id)
    created = existing is None
    if existing is None:
        sample = Sample(
            id=uuid4(),
            machine_id=machine_id,
            upload_session_id=session_id,
            local_sample_id=meta.local_sample_id,
            image_path=image_path,
            full_frame_path=image_path,
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
            full_frame_path=image_path,
            overlay_path=None,
            fallback={
                "source_role": upload_meta.source_role,
                "capture_reason": upload_meta.capture_reason,
                "captured_at": upload_meta.captured_at,
                "detection_algorithm": upload_meta.detection_algorithm,
                "detection_bboxes": upload_meta.detection_bboxes,
                "detection_count": upload_meta.detection_count,
                "detection_score": upload_meta.detection_score,
            },
        )
        sample.image_width = width
        sample.image_height = height
        sample.channel_geometry = _build_channel_geometry(upload_meta)
        db.add(sample)
        _count_sample_in_session(db, session_id, now)
        sample_id = sample.id
    else:
        sample_id = existing.id
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_SAMPLES, meta.local_id)
    mark_machine_seen(machine, now)
    try:
        db.commit()
    except IntegrityError:
        # The same sample arrived twice at once and the other request stored
        # it first: answer like a re-send.
        db.rollback()
        session = _find_upload_session(db, machine_id, meta.source_session_id)
        existing = _find_sample(db, session.id, meta.local_sample_id) if session else None
        if existing is None:
            raise
        sample_id = existing.id
        new_max = _advance_watermark(db, machine_id, DATA_TYPE_SAMPLES, meta.local_id)
        db.commit()
        created = False
    return {"max_local_id": new_max, "sample_id": str(sample_id), "created": created}
