import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class PiecePartLabel(Base):
    """A human-provided ground-truth part (mold) for one synced machine piece.

    The part sibling of piece_color_labels: there a labeler corrects the color,
    here they correct WHICH MOLD it is — either fixing a wrong Brickognize
    identification or filling one in for a piece that came back unidentified
    (part_id NULL on machine_pieces, the "Unidentified" case in the UI).

    part_num is a Rebrickable part_num — the primary key of the parts.db catalog
    (ProfileCatalogService / profile_engine.db), which is also the namespace
    MachinePiece.part_id is in and what part_bricklink_ids maps to a BrickLink
    item_no. Storing it here is what lets a corrected piece light up the
    "Sold on BrickLink" column that an unidentified piece can't show. No FK:
    parts.db is a separate sqlite catalog, not a Postgres table.

    One label per (machine, piece, labeler) — mirrors piece_color_labels and
    sample_reviews so multiple independent labels per piece can be aggregated.
    """

    __tablename__ = "piece_part_labels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    labeler_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # part_num is null exactly when cant_tell is set — the labeler looked and
    # couldn't identify the mold (a real answer, not an absent label).
    part_num = Column(String, nullable=True)
    cant_tell = Column(Boolean, nullable=False, default=False)
    # What the machine had predicted when this correction was made, so a label
    # can be read as "human disagreed with X" without re-deriving it from a piece
    # row that may since have been re-synced. Null when the piece was
    # unidentified — the fill-in-a-missing-part case.
    predicted_part_num = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("machine_id", "piece_uuid", "labeler_id", name="uq_piece_part_labels_piece_labeler"),
        Index("ix_piece_part_labels_machine_piece", "machine_id", "piece_uuid"),
        Index("ix_piece_part_labels_labeler_id", "labeler_id"),
        Index("ix_piece_part_labels_part_num", "part_num"),
    )
