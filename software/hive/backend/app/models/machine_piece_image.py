import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachinePieceImage(Base):
    __tablename__ = "machine_piece_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    seq = Column(Integer, nullable=False)
    # The machine's sqlite autoincrement id — drives the per-target sync watermark.
    local_id = Column(BigInteger, nullable=False)
    source = Column(String, nullable=True)
    channel = Column(Integer, nullable=True)
    ts = Column(DateTime(timezone=True), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    sharpness = Column(Float, nullable=True)
    bytes = Column(Integer, nullable=True)
    used = Column(Boolean, nullable=False, default=False)
    excluded_from_result = Column(Boolean, nullable=False, default=False)
    score = Column(Float, nullable=True)
    # Object-storage key. NULL when the crop was already evicted from the
    # machine's 500 MB local store before it could be synced — the row still
    # rides up so Hive's record of "this piece had N crops" stays complete.
    image_key = Column(String, nullable=True)
    evicted_locally = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("machine_id", "piece_uuid", "seq", name="uq_machine_piece_images_machine_piece_seq"),
        Index("ix_machine_piece_images_machine_local_id", "machine_id", "local_id"),
        Index("ix_machine_piece_images_machine_piece", "machine_id", "piece_uuid"),
    )
