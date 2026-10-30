import io
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from PIL import Image
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from sqlalchemy import bindparam, case, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.deps import get_current_machine, get_db
from app.errors import APIError
from app.models.machine import Machine
from app.models.machine_piece import MachinePiece
from app.models.machine_piece_image import MachinePieceImage
from app.models.machine_piece_prediction import SOURCE_LIVE, MachinePiecePrediction
from app.models.machine_piece_rejection_reason import MachinePieceRejectionReason
from app.models.machine_channel_crop import MachineChannelCrop
from app.models.machine_control_data_segment import MachineControlDataSegment
from app.models.machine_sync_state import MachineSyncState
from app.models.machine_telemetry import MachineTelemetryRecord
from app.models.machine_sorting_run import MachineLot, MachineSortingRun
from app.models.machine_training_run import MachineTrainingRun
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
from app.services.storage_backend import ranged_key
from app.services import swatch_jobs, training_runs
from app.services.storage import (
    JPEG_MAGIC,
    MAX_CROP_BATCH_BYTES,
    MAX_CROP_BATCH_ITEMS,
    save_channel_crop_batch_file,
    save_channel_crop_file,
    save_piece_image_file,
    save_control_data_file,
    save_sample_frame_file,
    validate_gzip,
    validate_image,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/machine/sync", tags=["machine-sync"])
# Keyed per machine token, not per address; shared with the upload routes.
limiter = machine_limiter

DATA_TYPE_PIECE_RECORDS = "piece_records"
DATA_TYPE_PIECE_IMAGES = "piece_images"
DATA_TYPE_CHANNEL_CROPS = "channel_crops"
DATA_TYPE_PIECE_CORRECTIONS = "piece_corrections"
DATA_TYPE_PIECE_PREDICTIONS = "piece_predictions"
DATA_TYPE_CONTROL_DATA = "control_data_segments"
DATA_TYPE_SAMPLES = "samples"
DATA_TYPE_TRAINING_RUNS = "training_runs"
# Lots and sorting runs, sent whole when they change; its state is the
# version of the last set kept, not a cursor.
DATA_TYPE_SORTING_RUNS = "sorting_runs"
DATA_TYPE_TELEMETRY = "telemetry"
DATA_TYPES = (
    DATA_TYPE_PIECE_RECORDS,
    DATA_TYPE_PIECE_IMAGES,
    DATA_TYPE_CHANNEL_CROPS,
    DATA_TYPE_PIECE_CORRECTIONS,
    DATA_TYPE_PIECE_PREDICTIONS,
    DATA_TYPE_CONTROL_DATA,
    DATA_TYPE_SAMPLES,
    DATA_TYPE_TRAINING_RUNS,
    DATA_TYPE_SORTING_RUNS,
    DATA_TYPE_TELEMETRY,
)

# The watermark rule (the sorter's sync_seq.py): a row that changes on the
# machine carries sync_seq, a value from one machine-wide counter taken each
# time the row changes, and the data type's watermark advances by it; a row
# from an older sorter, or one that never changes, advances it by local_id.
# Either way the watermark is the highest value accepted, kept in
# machine_sync_state.max_local_id.

# Columns updated on conflict — everything except the identity/immutable set
# (id, machine_id, piece_uuid[, seq], created_at) and the machine operator's
# verdict, which only a record carrying sync_seq updates (_VERDICT_COLS): an
# older sorter sends the verdict on its piece_corrections stream instead.
_PIECE_UPDATE_COLS = (
    "local_id", "run_id", "seen_at", "recorded_at", "classification_status",
    "part_id", "part_name", "color_id", "color_name", "category_id", "confidence",
    "color_confidence", "bin_x", "bin_y", "bin_z", "dead", "brickognize_preview_url",
    "brickognize_listing_id", "brickognize_item_rank", "brickognize_item_type",
    "brickognize_color_rank", "color_provider", "mold_provider",
    # The piece's training run and label: the sorter owns them, so every
    # record overwrites them (a record from a sorter without training mode
    # clears them, which is what it means).
    "training_run_uuid", "training_segment_uuid", "training_color_id", "training_label_source",
    "training_excluded", "training_updated_at",
)
_VERDICT_COLS = ("part_correct", "color_corrected_id", "correction_updated_at")
_FEEDBACK_FLAG_COLS = ("part_feedback_submitted", "color_feedback_submitted")
_PREDICTION_UPDATE_COLS = (
    "local_id", "provider", "model", "model_name", "images", "value_id", "value_name", "score", "applied",
    "predicted_at",
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
_TRAINING_RUN_UPDATE_COLS = (
    "mode", "color_ids", "segments", "started_at", "ended_at", "excluded", "updated_at", "received_at",
)
_TELEMETRY_UPDATE_COLS = ("kind", "form", "schema", "started_at", "ended_at", "data", "received_at")
# A telemetry record's data is at most this large (the sorter keeps none larger).
MAX_TELEMETRY_DATA_BYTES = 64 * 1024
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


def _end_read_before_storage(db: Session) -> None:
    """End the transaction the machine-token lookup began, so no connection
    sits idle in it while a file travels to storage (a round trip to the
    object store, or a large segment). The writes that follow make a short
    transaction of their own. A commit, not a rollback: a rollback expires
    the machine loaded with the token, and reading it again is a query."""
    db.commit()


def _insert(db: Session):
    return pg_insert if db.bind.dialect.name == "postgresql" else sqlite_insert


def _upsert(
    db: Session,
    model,
    rows: list[dict[str, Any]],
    index_elements: list[str],
    update_cols,
    or_cols: tuple[str, ...] = (),
    extra_set=None,
) -> None:
    """Insert rows, updating update_cols on a natural-key conflict; or_cols are
    flags that only ever turn on (the stored value OR the new one); extra_set
    (the insert statement -> {column: expression}) adds more."""
    if not rows:
        return
    stmt = _insert(db)(model).values(rows)
    set_ = {col: getattr(stmt.excluded, col) for col in update_cols}
    for col in or_cols:
        set_[col] = or_(getattr(model, col), getattr(stmt.excluded, col))
    if extra_set is not None:
        set_.update(extra_set(stmt))
    stmt = stmt.on_conflict_do_update(index_elements=index_elements, set_=set_)
    db.execute(stmt)


# The upsert of one row (a crop, a piece image, a segment: several a second)
# as plain SQL, built once per table and set of columns and then cached by
# SQLAlchemy like any text(). Its own upsert constructs are never cached, and
# for one crop, compiling the statement and building its "excluded" columns
# took about a fifth of the request's time.
_ONE_ROW_UPSERTS: dict[tuple, Any] = {}


def _upsert_one(
    db: Session, model, row: dict[str, Any], index_elements: tuple[str, ...], update_cols: tuple[str, ...]
) -> None:
    """Insert one row, updating update_cols on a natural-key conflict."""
    shape = (model.__tablename__, tuple(row), index_elements, update_cols)
    stmt = _ONE_ROW_UPSERTS.get(shape)
    if stmt is None:
        table = model.__table__
        quoted = '"{}"'.format
        stmt = text(
            f"INSERT INTO {quoted(table.name)} ({', '.join(map(quoted, row))}) "
            f"VALUES ({', '.join(':' + name for name in row)}) "
            f"ON CONFLICT ({', '.join(map(quoted, index_elements))}) DO UPDATE SET "
            + ", ".join(f"{quoted(name)} = excluded.{quoted(name)}" for name in update_cols)
        ).bindparams(*(bindparam(name, type_=table.c[name].type) for name in row))
        _ONE_ROW_UPSERTS[shape] = stmt
    db.execute(stmt, row)


# local_id of a machine_pieces row a correction created before its record
# arrived (older sorters; see sync_piece_corrections). Sorter ids start at 1.
_STUB_LOCAL_ID = 0


def _stub_takes_record_time(stmt) -> dict:
    # Hive learns of the piece when its record lands, not when the stub was
    # made: created_at is what workers count new pieces forward from.
    return {
        "created_at": case(
            (MachinePiece.local_id == _STUB_LOCAL_ID, stmt.excluded.created_at),
            else_=MachinePiece.created_at,
        )
    }


def _row_key(raw: Any) -> int | None:
    """A batch row's cursor value (sync_seq, else local_id), read before
    validation so a row that fails it still moves the watermark past it."""
    if not isinstance(raw, dict):
        return None
    for field in ("sync_seq", "local_id"):
        value = raw.get(field)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _validate_rows(model, raw_rows: list[Any], machine: Machine, data_type: str) -> tuple[list[Any], int, int]:
    """Validate a batch row by row: (the valid rows, how many were skipped, the
    highest cursor value seen). A bad row is logged and skipped, never allowed
    to stall the machine's sync."""
    valid: list[Any] = []
    skipped = 0
    key_max = 0
    for raw in raw_rows:
        key = _row_key(raw)
        if key is not None:
            key_max = max(key_max, key)
        try:
            valid.append(model.model_validate(raw))
        except ValidationError as exc:
            skipped += 1
            log.warning(
                "machine %s: skipped a bad %s row (key %s): %s",
                machine.id, data_type, key, exc.errors(include_url=False)[:3],
            )
    return valid, skipped, key_max


def _write_rows(db: Session, write, rows: list[Any], machine: Machine, data_type: str) -> int:
    """Run write(rows) in a savepoint; if the database refuses the batch, run
    it row by row and skip the rows it refuses (logged). Returns how many
    rows were skipped."""
    if not rows:
        return 0
    try:
        with db.begin_nested():
            write(rows)
        return 0
    except SQLAlchemyError:
        pass
    skipped = 0
    for row in rows:
        try:
            with db.begin_nested():
                write([row])
        except SQLAlchemyError as exc:
            skipped += 1
            log.warning("machine %s: skipped a %s row the database refused: %s", machine.id, data_type, exc)
    return skipped


def _replace_rejection_reasons(
    db: Session, machine_id: UUID, reasons_by_piece: dict[str, list[str]], now: datetime
) -> None:
    """Set each piece's operator-flagged reasons to exactly the given set.
    Idempotent: a re-send, or the same piece twice in one batch, never trips
    the unique constraint (the pieces' rows are deleted first, the inserts are
    de-duplicated and skip any row already there)."""
    if not reasons_by_piece:
        return
    db.query(MachinePieceRejectionReason).filter(
        MachinePieceRejectionReason.machine_id == machine_id,
        MachinePieceRejectionReason.piece_uuid.in_(list(reasons_by_piece)),
    ).delete(synchronize_session=False)
    rows = [
        {"id": uuid4(), "machine_id": machine_id, "piece_uuid": piece_uuid, "reason": reason, "created_at": now}
        for piece_uuid, reasons in reasons_by_piece.items()
        for reason in dict.fromkeys(str(r) for r in reasons)
    ]
    if rows:
        db.execute(
            _insert(db)(MachinePieceRejectionReason)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["machine_id", "piece_uuid", "reason"])
        )


# Raise a (machine, data type) watermark to a new value if that is higher, and
# return it: one statement, where reading the row and writing it back took
# two. Plain SQL both Postgres and SQLite run, so SQLAlchemy compiles it once:
# its own upsert constructs are never cached and compile on every request.
_ADVANCE_WATERMARK = text(
    "INSERT INTO machine_sync_state (machine_id, data_type, max_local_id, updated_at) "
    "VALUES (:machine_id, :data_type, :max_local_id, :updated_at) "
    "ON CONFLICT (machine_id, data_type) DO UPDATE SET "
    "max_local_id = CASE WHEN excluded.max_local_id > machine_sync_state.max_local_id "
    "THEN excluded.max_local_id ELSE machine_sync_state.max_local_id END, "
    "updated_at = excluded.updated_at "
    "RETURNING max_local_id"
).bindparams(
    bindparam("machine_id", type_=MachineSyncState.__table__.c.machine_id.type),
    bindparam("updated_at", type_=MachineSyncState.__table__.c.updated_at.type),
)


def _advance_watermark(db: Session, machine_id: UUID, data_type: str, new_max: int) -> int:
    params = {"machine_id": machine_id, "data_type": data_type, "max_local_id": new_max, "updated_at": _now()}
    return int(db.execute(_ADVANCE_WATERMARK, params).scalar_one())


class PieceRecordIn(BaseModel):
    piece_uuid: str
    local_id: int
    # Present from sorters that sync records by sync_seq; such a record carries
    # the machine operator's whole verdict (below).
    sync_seq: int | None = None
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
    part_correct: bool | None = None
    color_corrected_id: str | None = None
    part_feedback_submitted: bool = False
    color_feedback_submitted: bool = False
    correction_updated_at: float | None = None
    # Operator-flagged capture issues (no_piece / multiple_pieces / not_lego /
    # assembly / pieces_entangled / blurry), the complete set.
    rejection_reasons: list[str] | None = None
    # The training run the piece was seen in and the segment of it, the colour
    # it labels the piece with ("run" / "prediction" / "nearest": how it was
    # decided) and the operator's exclusion. Absent from sorters without
    # training mode (and the segment from those before runs had segments).
    training_run_uuid: str | None = None
    training_segment_uuid: str | None = None
    training_color_id: str | None = None
    training_label_source: str | None = None
    training_excluded: bool | None = None
    training_updated_at: float | None = None


class TrainingSegmentIn(BaseModel):
    """A stretch of a training run with the colours fed during it."""

    segment_uuid: str
    color_ids: list[str] = Field(default_factory=list)
    started_at: float
    ended_at: float | None = None


class TrainingRunIn(BaseModel):
    """A training run (the sorter's training mode): while it was open every
    piece the machine saw counts as what the run was for. Changes on the
    machine (it ends, it is excluded), so it carries sync_seq."""

    run_uuid: str
    sync_seq: int
    mode: str
    # Every colour the run's segments used.
    color_ids: list[str] = Field(default_factory=list)
    # Oldest first; absent from sorters before runs had segments.
    segments: list[TrainingSegmentIn] | None = None
    started_at: float
    ended_at: float | None = None
    excluded: bool = False
    updated_at: float | None = None

    @field_validator("run_uuid")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("started_at")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be a time")
        return value


class SyncBatch(BaseModel):
    # Validated row by row (see _validate_rows), so one bad row is skipped
    # instead of failing the batch.
    records: list[Any]


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


class PredictionImageIn(BaseModel):
    # One of the piece's images a prediction was made from, as the machine
    # keeps it: "burst" (a classification channel crop; seq is the
    # machine_piece_images seq) or "link" (an upstream crop the piece-link
    # model matched).
    set: str = Field(max_length=16)
    seq: int
    channel: int | None = None


class PiecePredictionIn(BaseModel):
    local_id: int
    piece_uuid: str
    # "live" (the machine's classification while sorting) or a later run's
    # label; sorters older than sources send none.
    source: str = Field(default=SOURCE_LIVE, min_length=1, max_length=120)
    request: str
    provider: str
    # The model's identity (its sha256) and its name.
    model: str | None = None
    model_name: str | None = None
    # None from sorters that did not record them.
    images: list[PredictionImageIn] | None = Field(default=None, max_length=64)
    kind: str
    rank: int
    value_id: str
    value_name: str | None = None
    score: float | None = None
    applied: bool = False
    created_at: float | None = None


class LotIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    created_at: float | None = None


class SortingRunIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    lot_id: str | None = Field(default=None, max_length=64)
    adds_to_lot: bool = False
    started_at: float
    created_at: float | None = None


class SortingRunsIn(BaseModel):
    """Every lot and sorting run the machine keeps, as one set. ``version``
    names the set (a number the machine derives from its content), so the
    machine can tell from /state whether Hive has it."""

    version: int
    lots: list[LotIn] = Field(default_factory=list, max_length=1000)
    runs: list[SortingRunIn] = Field(default_factory=list, max_length=10000)


class PieceImageMeta(BaseModel):
    piece_uuid: str
    seq: int
    local_id: int
    # Present from sorters that sync images by sync_seq (an image goes once
    # its piece's record exists, with its final flags).
    sync_seq: int | None = None
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


class ChannelCropBatchItem(ChannelCropMeta):
    # The crop's JPEG in the batch file; absent for a crop sent metadata-only.
    offset: int | None = None
    length: int | None = None


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
    return {data_type: {"max_local_id": by_type.get(data_type, 0)} for data_type in DATA_TYPES}


def _watermark(db: Session, machine_id: UUID, data_type: str) -> int:
    row = (
        db.query(MachineSyncState)
        .filter(MachineSyncState.machine_id == machine_id, MachineSyncState.data_type == data_type)
        .first()
    )
    return row.max_local_id if row else 0


def _latest_per_key(rows: list[Any], key, order) -> list[Any]:
    """One row per natural key, the latest by `order` (a batch may carry the
    same piece twice; one upsert statement must not touch a row twice)."""
    latest: dict[Any, Any] = {}
    for row in rows:
        k = key(row)
        if k not in latest or order(row) >= order(latest[k]):
            latest[k] = row
    return list(latest.values())


def _piece_row(machine_id: UUID, rec: PieceRecordIn, now: datetime) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "machine_id": machine_id,
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
        "part_correct": rec.part_correct,
        "color_corrected_id": rec.color_corrected_id,
        "part_feedback_submitted": rec.part_feedback_submitted,
        "color_feedback_submitted": rec.color_feedback_submitted,
        "correction_updated_at": _ts(rec.correction_updated_at),
        "training_run_uuid": rec.training_run_uuid,
        "training_segment_uuid": rec.training_segment_uuid,
        "training_color_id": rec.training_color_id,
        "training_label_source": rec.training_label_source,
        "training_excluded": bool(rec.training_excluded),
        "training_updated_at": _ts(rec.training_updated_at),
        "created_at": now,
    }


@router.post("/piece-records")
@limiter.limit("300/minute")
def sync_piece_records(
    request: Request,
    payload: SyncBatch,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, int]:
    """Upsert piece records by (machine, piece_uuid). A record with sync_seq is
    the machine's whole state for the piece, the operator's verdict and
    rejection reasons included; an older sorter's record leaves the verdict to
    its piece_corrections stream. The training runs the batch touches are
    recounted, and its pieces' labeling-queue flags follow their training
    labels (services/training_runs.py)."""
    records, skipped, key_max = _validate_rows(PieceRecordIn, payload.records, machine, DATA_TYPE_PIECE_RECORDS)
    if not payload.records:
        return {"max_local_id": _watermark(db, machine.id, DATA_TYPE_PIECE_RECORDS), "upserted": 0, "skipped": 0}

    now = _now()
    machine_id = machine.id
    records = _latest_per_key(
        records, key=lambda r: r.piece_uuid, order=lambda r: r.sync_seq if r.sync_seq is not None else r.local_id
    )

    def write(batch: list[PieceRecordIn]) -> None:
        # The runs these pieces were in before this batch: a piece that left
        # a run changes that run's counts too.
        previous = training_runs.runs_of(db, machine_id, [r.piece_uuid for r in batch])
        current = [r for r in batch if r.sync_seq is not None]
        older = [r for r in batch if r.sync_seq is None]
        _upsert(
            db, MachinePiece, [_piece_row(machine_id, r, now) for r in current],
            ["machine_id", "piece_uuid"], _PIECE_UPDATE_COLS + _VERDICT_COLS, or_cols=_FEEDBACK_FLAG_COLS,
            extra_set=_stub_takes_record_time,
        )
        _upsert(
            db, MachinePiece,
            [{k: v for k, v in _piece_row(machine_id, r, now).items() if k not in _VERDICT_COLS + _FEEDBACK_FLAG_COLS}
             for r in older],
            ["machine_id", "piece_uuid"], _PIECE_UPDATE_COLS, extra_set=_stub_takes_record_time,
        )
        _replace_rejection_reasons(
            db, machine_id,
            {r.piece_uuid: r.rejection_reasons for r in current if r.rejection_reasons is not None},
            now,
        )
        training_runs.after_piece_records(db, machine_id, batch, previous)

    skipped += _write_rows(db, write, records, machine, DATA_TYPE_PIECE_RECORDS)
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_PIECE_RECORDS, key_max)
    mark_machine_seen(machine, now)
    db.commit()
    return {"max_local_id": new_max, "upserted": len(payload.records) - skipped, "skipped": skipped}


def _iso(value: float | None) -> str | None:
    dt = _ts(value)
    return dt.isoformat() if dt is not None else None


def _training_run_row(machine_id: UUID, rec: TrainingRunIn, now: datetime) -> dict[str, Any]:
    return {
        "id": uuid4(),
        "machine_id": machine_id,
        "run_uuid": rec.run_uuid,
        "mode": rec.mode,
        "color_ids": [str(c) for c in rec.color_ids],
        "segments": [
            {
                "segment_uuid": seg.segment_uuid,
                "color_ids": [str(c) for c in seg.color_ids],
                "started_at": _iso(seg.started_at),
                "ended_at": _iso(seg.ended_at),
            }
            for seg in rec.segments or []
        ],
        "started_at": _ts(rec.started_at),
        "ended_at": _ts(rec.ended_at),
        "excluded": rec.excluded,
        "updated_at": _ts(rec.updated_at),
        "piece_count": 0,
        "labeled_count": 0,
        "excluded_count": 0,
        "created_at": now,
        "received_at": now,
    }


@router.post("/training-runs")
@limiter.limit("300/minute")
def sync_training_runs(
    request: Request,
    payload: SyncBatch,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, int]:
    """Upsert training runs by (machine, run_uuid), then count each run's
    pieces into its row (its pieces may have come first) and set its pieces'
    labeling-queue flags (an excluded run's labels stop counting). The counts
    are Hive's; everything else on the row is the machine's."""
    runs, skipped, key_max = _validate_rows(TrainingRunIn, payload.records, machine, DATA_TYPE_TRAINING_RUNS)
    if not payload.records:
        return {"max_local_id": _watermark(db, machine.id, DATA_TYPE_TRAINING_RUNS), "upserted": 0, "skipped": 0}

    now = _now()
    machine_id = machine.id
    runs = _latest_per_key(runs, key=lambda r: r.run_uuid, order=lambda r: r.sync_seq)

    def write(batch: list[TrainingRunIn]) -> None:
        _upsert(
            db, MachineTrainingRun, [_training_run_row(machine_id, r, now) for r in batch],
            ["machine_id", "run_uuid"], _TRAINING_RUN_UPDATE_COLS,
        )
        training_runs.after_runs(db, machine_id, [r.run_uuid for r in batch])

    skipped += _write_rows(db, write, runs, machine, DATA_TYPE_TRAINING_RUNS)
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_TRAINING_RUNS, key_max)
    mark_machine_seen(machine, now)
    db.commit()
    return {"max_local_id": new_max, "upserted": len(payload.records) - skipped, "skipped": skipped}


@router.post("/sorting-runs")
@limiter.limit("60/minute")
def sync_sorting_runs(
    request: Request,
    payload: SortingRunsIn,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, int]:
    """Replace the machine's lots and sorting runs with the set it sends (it
    can rename a run or move it to another lot, and delete one), and keep the
    set's version as this data type's state."""
    now = _now()
    machine_id = machine.id
    lots = {lot.id: lot for lot in payload.lots}
    runs = {run.id: run for run in payload.runs}
    db.query(MachineSortingRun).filter(
        MachineSortingRun.machine_id == machine_id, MachineSortingRun.run_id.notin_(list(runs) or [""])
    ).delete(synchronize_session=False)
    db.query(MachineLot).filter(
        MachineLot.machine_id == machine_id, MachineLot.lot_id.notin_(list(lots) or [""])
    ).delete(synchronize_session=False)
    if lots:
        _upsert(
            db, MachineLot,
            [
                {
                    "machine_id": machine_id,
                    "lot_id": lot.id,
                    "name": lot.name,
                    "description": lot.description,
                    "created_at": _ts(lot.created_at),
                }
                for lot in lots.values()
            ],
            ["machine_id", "lot_id"], ("name", "description", "created_at"),
        )
    if runs:
        _upsert(
            db, MachineSortingRun,
            [
                {
                    "machine_id": machine_id,
                    "run_id": run.id,
                    "name": run.name,
                    "note": run.note,
                    "lot_id": run.lot_id,
                    "adds_to_lot": run.adds_to_lot,
                    "started_at": _ts(run.started_at),
                    "created_at": _ts(run.created_at),
                }
                for run in runs.values()
            ],
            ["machine_id", "run_id"], ("name", "note", "lot_id", "adds_to_lot", "started_at", "created_at"),
        )
    state = (
        db.query(MachineSyncState)
        .filter(MachineSyncState.machine_id == machine_id, MachineSyncState.data_type == DATA_TYPE_SORTING_RUNS)
        .first()
    )
    if state is None:
        db.add(MachineSyncState(machine_id=machine_id, data_type=DATA_TYPE_SORTING_RUNS, max_local_id=payload.version, updated_at=now))
    else:
        state.max_local_id = payload.version
        state.updated_at = now
    mark_machine_seen(machine, now)
    db.commit()
    return {"max_local_id": payload.version, "lots": len(lots), "runs": len(runs)}


@router.post("/piece-corrections")
@limiter.limit("300/minute")
def sync_piece_corrections(
    request: Request,
    payload: SyncBatch,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, int]:
    """The machine operator's verdict from sorters older than the sync_seq
    protocol (newer ones send it with the record). A correction for a piece
    whose record has not arrived yet creates the piece's row, which the record
    fills in when it comes. The submitted flags are OR'd, never cleared."""
    corrections, skipped, key_max = _validate_rows(
        PieceCorrectionIn, payload.records, machine, DATA_TYPE_PIECE_CORRECTIONS
    )
    if not payload.records:
        return {"max_local_id": _watermark(db, machine.id, DATA_TYPE_PIECE_CORRECTIONS), "upserted": 0, "skipped": 0}

    now = _now()
    machine_id = machine.id
    # The journal holds a full snapshot per edit; the latest one per piece wins.
    corrections = _latest_per_key(corrections, key=lambda r: r.piece_uuid, order=lambda r: r.local_id)

    def write(batch: list[PieceCorrectionIn]) -> None:
        _upsert(
            db, MachinePiece,
            [
                {
                    "id": uuid4(),
                    "machine_id": machine_id,
                    "piece_uuid": r.piece_uuid,
                    # A placeholder until the piece's record arrives.
                    "local_id": _STUB_LOCAL_ID,
                    "dead": False,
                    "part_correct": r.part_correct,
                    "color_corrected_id": r.color_corrected_id,
                    "part_feedback_submitted": r.part_feedback_submitted,
                    "color_feedback_submitted": r.color_feedback_submitted,
                    "correction_updated_at": _ts(r.updated_at) or now,
                    "created_at": now,
                }
                for r in batch
            ],
            ["machine_id", "piece_uuid"], _VERDICT_COLS, or_cols=_FEEDBACK_FLAG_COLS,
        )
        # None means the machine predates the field and isn't reporting flags:
        # leave what is there rather than reading it as "operator cleared them".
        _replace_rejection_reasons(
            db, machine_id,
            {r.piece_uuid: r.rejection_reasons for r in batch if r.rejection_reasons is not None},
            now,
        )

    skipped += _write_rows(db, write, corrections, machine, DATA_TYPE_PIECE_CORRECTIONS)
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_PIECE_CORRECTIONS, key_max)
    mark_machine_seen(machine, now)
    db.commit()
    return {"max_local_id": new_max, "upserted": len(payload.records) - skipped, "skipped": skipped}


@router.post("/piece-predictions")
@limiter.limit("300/minute")
def sync_piece_predictions(
    request: Request,
    payload: SyncBatch,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, int]:
    """Every ranked part and colour answer the machine got for its pieces,
    from any source (MachinePiecePrediction), upserted by (machine, piece,
    source, request, kind, rank)."""
    predictions, skipped, key_max = _validate_rows(
        PiecePredictionIn, payload.records, machine, DATA_TYPE_PIECE_PREDICTIONS
    )
    if not payload.records:
        return {"max_local_id": _watermark(db, machine.id, DATA_TYPE_PIECE_PREDICTIONS), "upserted": 0, "skipped": 0}

    now = _now()
    machine_id = machine.id
    predictions = _latest_per_key(
        predictions, key=lambda r: (r.piece_uuid, r.source, r.request, r.kind, r.rank), order=lambda r: r.local_id
    )

    def write(batch: list[PiecePredictionIn]) -> None:
        _upsert(
            db, MachinePiecePrediction,
            [
                {
                    "id": uuid4(),
                    "machine_id": machine_id,
                    "piece_uuid": r.piece_uuid,
                    "local_id": r.local_id,
                    "source": r.source,
                    "request": r.request,
                    "provider": r.provider,
                    "model": r.model,
                    "model_name": r.model_name,
                    "images": [i.model_dump() for i in r.images] if r.images is not None else None,
                    "kind": r.kind,
                    "rank": r.rank,
                    "value_id": r.value_id,
                    "value_name": r.value_name,
                    "score": r.score if r.score is None or math.isfinite(r.score) else None,
                    "applied": r.applied,
                    "predicted_at": _ts(r.created_at),
                    "created_at": now,
                }
                for r in batch
            ],
            ["machine_id", "piece_uuid", "source", "request", "kind", "rank"], _PREDICTION_UPDATE_COLS,
        )

    skipped += _write_rows(db, write, predictions, machine, DATA_TYPE_PIECE_PREDICTIONS)
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_PIECE_PREDICTIONS, key_max)
    mark_machine_seen(machine, now)
    db.commit()
    return {"max_local_id": new_max, "upserted": len(payload.records) - skipped, "skipped": skipped}


class TelemetryRecordIn(BaseModel):
    local_id: int = Field(ge=1)
    kind: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    form: Literal["snapshot", "window", "event"]
    # Named for the wire; BaseModel has a `schema` of its own.
    data_schema: int = Field(default=1, ge=1, alias="schema")
    started_at: float = Field(allow_inf_nan=False)
    ended_at: float = Field(allow_inf_nan=False)
    data: dict[str, Any]

    @model_validator(mode="after")
    def _sane(self) -> "TelemetryRecordIn":
        if self.ended_at < self.started_at:
            raise ValueError("ended_at is before started_at")
        if len(json.dumps(self.data, separators=(",", ":"))) > MAX_TELEMETRY_DATA_BYTES:
            raise ValueError(f"data is over {MAX_TELEMETRY_DATA_BYTES} bytes")
        return self


@router.post("/telemetry")
@limiter.limit("60/minute")
def sync_telemetry(
    request: Request,
    payload: SyncBatch,
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, int]:
    """How the machine is set up and how it runs (MachineTelemetryRecord),
    upserted by (machine, local_id). The newest machine_specs snapshot in the
    batch also becomes the machine's hardware summary and history, as specs
    on a heartbeat do."""
    records, skipped, key_max = _validate_rows(TelemetryRecordIn, payload.records, machine, DATA_TYPE_TELEMETRY)
    if not payload.records:
        return {"max_local_id": _watermark(db, machine.id, DATA_TYPE_TELEMETRY), "upserted": 0, "skipped": 0}

    now = _now()
    machine_id = machine.id
    records = _latest_per_key(records, key=lambda r: r.local_id, order=lambda r: r.local_id)

    def write(batch: list[TelemetryRecordIn]) -> None:
        _upsert(
            db, MachineTelemetryRecord,
            [
                {
                    "id": uuid4(),
                    "machine_id": machine_id,
                    "local_id": r.local_id,
                    "kind": r.kind,
                    "form": r.form,
                    "schema": r.data_schema,
                    "started_at": _ts(r.started_at),
                    "ended_at": _ts(r.ended_at),
                    "data": r.data,
                    "received_at": now,
                }
                for r in batch
            ],
            ["machine_id", "local_id"], _TELEMETRY_UPDATE_COLS,
        )

    skipped += _write_rows(db, write, records, machine, DATA_TYPE_TELEMETRY)
    specs = [r for r in records if r.kind == "machine_specs" and r.form == "snapshot"]
    if specs:
        from app.machine_hardware import record_hardware_report

        try:
            with db.begin_nested():
                record_hardware_report(db, machine, max(specs, key=lambda r: r.local_id).data)
        except SQLAlchemyError as exc:
            log.warning("machine %s: its specs did not become its hardware report: %s", machine_id, exc)
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_TELEMETRY, key_max)
    mark_machine_seen(machine, now)
    db.commit()
    return {"max_local_id": new_max, "upserted": len(payload.records) - skipped, "skipped": skipped}


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
    key = meta.sync_seq if meta.sync_seq is not None else meta.local_id
    machine_id = machine.id
    if meta.source == "link_match":
        new_max = _advance_watermark(db, machine_id, DATA_TYPE_PIECE_IMAGES, key)
        mark_machine_seen(machine, _now())
        db.commit()
        return {"max_local_id": new_max, "image_stored": False, "rejected_source": "link_match"}

    image_key: str | None = None
    evicted_locally = image is None
    if image is not None:
        suffix = validate_image(image)
        _end_read_before_storage(db)
        image_key = save_piece_image_file(str(machine_id), meta.piece_uuid, meta.seq, meta.source, image, suffix)

    now = _now()
    row = {
        "id": uuid4(),
        "machine_id": machine_id,
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
    _upsert_one(db, MachinePieceImage, row, ("machine_id", "piece_uuid", "seq"), update_cols)
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_PIECE_IMAGES, key)
    mark_machine_seen(machine, now)
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

    machine_id = machine.id
    image_key: str | None = None
    evicted_locally = image is None
    if image is not None:
        suffix = validate_image(image)
        _end_read_before_storage(db)
        image_key = save_channel_crop_file(str(machine_id), meta.local_id, meta.channel, image, suffix)

    bbox = meta.bbox if (meta.bbox and len(meta.bbox) == 4) else [None, None, None, None]
    now = _now()
    row = {
        "id": uuid4(),
        "machine_id": machine_id,
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
    _upsert_one(db, MachineChannelCrop, row, ("machine_id", "local_id"), update_cols)
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_CHANNEL_CROPS, meta.local_id)
    mark_machine_seen(machine, now)
    db.commit()
    return {"max_local_id": new_max, "image_stored": image is not None}


@router.post("/channel-crop-batch")
@limiter.limit("120/minute")
def sync_channel_crop_batch(
    request: Request,
    metadata: str = Form(...),
    crops: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    machine: Machine = Depends(get_current_machine),
) -> dict[str, Any]:
    """Many channel crops in one upload: their JPEGs back to back in one file
    (stored once), each crop's metadata naming its range in it. A crop whose
    range or metadata is bad is skipped or kept without its picture, never the
    whole batch, and the watermark still moves past it."""
    try:
        raw = json.loads(metadata)["crops"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise APIError(400, f"Invalid metadata: {exc}", "INVALID_METADATA") from exc
    if not isinstance(raw, list) or len(raw) > MAX_CROP_BATCH_ITEMS:
        raise APIError(400, f"A batch is a list of at most {MAX_CROP_BATCH_ITEMS} crops", "INVALID_METADATA")
    data = b""
    if crops is not None:
        data = crops.file.read(MAX_CROP_BATCH_BYTES + 1)
        if len(data) > MAX_CROP_BATCH_BYTES:
            raise APIError(413, f"A batch file is at most {MAX_CROP_BATCH_BYTES} bytes", "BATCH_TOO_LARGE")

    machine_id = machine.id
    max_key = 0
    items: dict[int, tuple[ChannelCropBatchItem, bool]] = {}
    for entry in raw:
        key = _row_key(entry)
        if key is not None:
            max_key = max(max_key, key)
        try:
            item = ChannelCropBatchItem.model_validate(entry)
        except ValidationError as exc:
            log.warning("channel crop batch from %s: skipped crop %s: %s", machine_id, key, exc)
            continue
        offset, length = item.offset, item.length
        has_image = (
            offset is not None
            and length is not None
            and offset >= 0
            and length > 0
            and offset + length <= len(data)
            and data[offset : offset + len(JPEG_MAGIC)] == JPEG_MAGIC
        )
        items[item.local_id] = (item, has_image)

    file_key: str | None = None
    if any(has_image for _, has_image in items.values()):
        _end_read_before_storage(db)
        file_key = save_channel_crop_batch_file(str(machine_id), min(items), max(items), data)

    now = _now()
    with_image: list[dict[str, Any]] = []
    without_image: list[dict[str, Any]] = []
    for item, has_image in items.values():
        bbox = item.bbox if (item.bbox and len(item.bbox) == 4) else [None, None, None, None]
        row = {
            "id": uuid4(),
            "machine_id": machine_id,
            "local_id": item.local_id,
            "channel": item.channel,
            "ts": _ts(item.ts),
            "captured_at": _ts(item.captured_at),
            "track_id": item.track_id,
            "com_forward_to_exit_deg": item.com_forward_to_exit_deg,
            "com_section": item.com_section,
            "zone_code": item.zone_code,
            "sharpness": item.sharpness,
            "bbox_x1": bbox[0],
            "bbox_y1": bbox[1],
            "bbox_x2": bbox[2],
            "bbox_y2": bbox[3],
            "bytes": item.bytes,
            "image_key": ranged_key(file_key, item.offset, item.length) if has_image and file_key else None,
            "evicted_locally": not has_image,
            "created_at": now,
        }
        (with_image if has_image else without_image).append(row)
    index = ["machine_id", "local_id"]
    _upsert(db, MachineChannelCrop, with_image, index, _CHANNEL_CROP_UPDATE_COLS)
    # A crop sent without its picture must not wipe one stored before.
    _upsert(db, MachineChannelCrop, without_image, index, tuple(c for c in _CHANNEL_CROP_UPDATE_COLS if c != "image_key"))
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_CHANNEL_CROPS, max_key)
    mark_machine_seen(machine, now)
    db.commit()
    return {"max_local_id": new_max, "stored": len(with_image), "without_image": len(without_image)}


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

    machine_id = machine.id
    data_key: str | None = None
    evicted_locally = data is None
    if data is not None:
        validate_gzip(data)
        _end_read_before_storage(db)
        data_key = save_control_data_file(str(machine_id), meta.local_id, data)

    now = _now()
    row = {
        "id": uuid4(),
        "machine_id": machine_id,
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
    _upsert_one(db, MachineControlDataSegment, row, ("machine_id", "local_id"), update_cols)
    new_max = _advance_watermark(db, machine_id, DATA_TYPE_CONTROL_DATA, meta.local_id)
    mark_machine_seen(machine, now)
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

    # The frame's key needs nothing from the database, so it is written
    # before the one transaction below.
    machine_id = machine.id
    _end_read_before_storage(db)
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
    if created:
        swatch_jobs.enqueue_for_new_sample(db, sample_id, upload_meta.source_role)
    return {"max_local_id": new_max, "sample_id": str(sample_id), "created": created}
