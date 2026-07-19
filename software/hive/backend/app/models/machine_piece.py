import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class MachinePiece(Base):
    __tablename__ = "machine_pieces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    # The machine's local piece uuid — natural key for idempotent upserts.
    piece_uuid = Column(String, nullable=False)
    # The machine's sqlite autoincrement id — drives the per-target sync watermark.
    local_id = Column(BigInteger, nullable=False)
    run_id = Column(String, nullable=True)
    seen_at = Column(DateTime(timezone=True), nullable=True)
    recorded_at = Column(DateTime(timezone=True), nullable=True)
    classification_status = Column(String, nullable=True)
    part_id = Column(String, nullable=True)
    part_name = Column(String, nullable=True)
    color_id = Column(String, nullable=True)
    color_name = Column(String, nullable=True)
    category_id = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    bin_x = Column(Integer, nullable=True)
    bin_y = Column(Integer, nullable=True)
    bin_z = Column(Integer, nullable=True)
    dead = Column(Boolean, nullable=False, default=False)
    brickognize_preview_url = Column(String, nullable=True)
    # Correction provenance from the applied Brickognize request, synced from the
    # machine alongside the prediction. Needed to address a correction to
    # Brickognize's feedback API (which keys on the listing id + result rank).
    brickognize_listing_id = Column(String, nullable=True)
    brickognize_item_rank = Column(Integer, nullable=True)
    brickognize_item_type = Column(String, nullable=True)
    brickognize_color_rank = Column(Integer, nullable=True)
    # Which service actually produced the applied color / mold on the machine
    # (see the sorter's classification.providers). Records what ANSWERED, not
    # what was configured, so provider accuracy can be scored against the
    # corrections below. NULL on rows synced before providers were selectable.
    color_provider = Column(String, nullable=True)
    mold_provider = Column(String, nullable=True)
    # User correction, synced from the machine (piece_corrections stream) and/or
    # set here on Hive. part_correct is NULL (unreviewed) / true / false;
    # color_corrected_id is the picked true BrickLink color id; the *_submitted
    # flags record whether the correction was sent to Brickognize.
    part_correct = Column(Boolean, nullable=True)
    color_corrected_id = Column(String, nullable=True)
    part_feedback_submitted = Column(Boolean, nullable=False, default=False)
    color_feedback_submitted = Column(Boolean, nullable=False, default=False)
    correction_updated_at = Column(DateTime(timezone=True), nullable=True)
    # Operator-flagged capture issues, synced from the machine alongside the
    # correction above. A JSON list of reason codes (no_piece / multiple_pieces /
    # not_lego) — the same vocabulary as piece_rejections.reasons, so a machine
    # operator's verdict and a Hive labeler's verdict mean the same thing.
    rejection_reasons = Column(JSON_VARIANT, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("machine_id", "piece_uuid", name="uq_machine_pieces_machine_piece"),
        Index("ix_machine_pieces_machine_local_id", "machine_id", "local_id"),
        Index("ix_machine_pieces_machine_seen_at", "machine_id", "seen_at"),
    )
