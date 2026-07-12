import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


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
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("machine_id", "piece_uuid", name="uq_machine_pieces_machine_piece"),
        Index("ix_machine_pieces_machine_local_id", "machine_id", "local_id"),
        Index("ix_machine_pieces_machine_seen_at", "machine_id", "seen_at"),
    )
