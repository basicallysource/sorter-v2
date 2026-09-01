import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class PieceColorLabel(Base):
    """A human-provided ground-truth color for one synced machine piece.

    Distinct from sample_reviews (which accept/reject part-classification
    training crops). Here a labeler looks at a piece's synced crop(s) and records
    the TRUE Lego color from the BrickLink palette. The piece's own
    color_id/color_name is only the machine's Brickognize prediction (also in
    BrickLink color space), shown for reference — this table is the correction.

    color_id is a BrickLink color id (parts.db is a separate sqlite catalog with
    no BrickLink-colors table of its own; the palette is derived from the
    Rebrickable `colors.extra` external ids — see
    ProfileCatalogService.list_bricklink_colors). No FK, since it's a
    cross-catalog id. One label per (machine, piece, labeler) — mirrors
    sample_reviews so multiple labelers can be aggregated later.
    """

    __tablename__ = "piece_color_labels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    labeler_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # color_id is null exactly when cant_tell is set — the labeler looked and the
    # color is genuinely indeterminate (a real answer, not an absent label).
    color_id = Column(Integer, nullable=True)
    cant_tell = Column(Boolean, nullable=False, default=False)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("machine_id", "piece_uuid", "labeler_id", name="uq_piece_color_labels_piece_labeler"),
        Index("ix_piece_color_labels_machine_piece", "machine_id", "piece_uuid"),
        Index("ix_piece_color_labels_labeler_id", "labeler_id"),
    )
