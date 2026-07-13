import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class PieceRejection(Base):
    """A labeler's rejection of a piece's bbox sample — the crop is unusable for
    labeling. Distinct from a color label or same-piece link: it flags the sample
    itself. `reasons` is a list of reason codes (currently "no_piece" /
    "multiple_pieces"), so multiple can apply and more can be added later. One
    rejection per (machine, piece, labeler), mirroring the other label tables.
    """

    __tablename__ = "piece_rejections"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    labeler_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    reasons = Column(JSON_VARIANT, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("machine_id", "piece_uuid", "labeler_id", name="uq_piece_rejections_piece_labeler"),
        Index("ix_piece_rejections_machine_piece", "machine_id", "piece_uuid"),
        Index("ix_piece_rejections_labeler_id", "labeler_id"),
    )
