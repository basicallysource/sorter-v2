import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class PieceCropLink(Base):
    """A human's assertion of which upstream C2/C3 crops are the SAME physical
    piece as one classified piece — training data for a future cross-channel
    piece-tracking model.

    On the color-labeling page a labeler is shown the classified piece and the
    time/angle heuristic's ranked "possibly the same piece" candidates (from
    machine_channel_crops). They keep, drop, and add crops, then accept. This
    parent row is one such decision; its members carry the per-crop verdict.

    Independent of piece_color_labels (color is a separate save). One decision
    per (machine, piece, labeler) so multiple labelers can be aggregated later,
    mirroring piece_color_labels / sample_reviews. arrival_ts is the C4 arrival
    time the candidates were scored against, kept for provenance.
    """

    __tablename__ = "piece_crop_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    labeler_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    # Epoch seconds of the piece's classification-channel arrival (the anchor the
    # candidates' dt was measured from). Provenance for re-deriving negatives.
    arrival_ts = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("machine_id", "piece_uuid", "labeler_id", name="uq_piece_crop_links_piece_labeler"),
        Index("ix_piece_crop_links_machine_piece", "machine_id", "piece_uuid"),
        Index("ix_piece_crop_links_labeler_id", "labeler_id"),
    )


class PieceCropLinkMember(Base):
    """One presented crop within a PieceCropLink, with the labeler's verdict.

    We store every candidate the labeler was SHOWN (not just the positives) so
    the decision is self-contained: is_same=true are positives (same piece),
    is_same=false are hard negatives (a crop a human looked at and rejected).
    was_predicted records whether the heuristic pre-selected it, so we can score
    the heuristic's precision/recall against human ground truth. crop_local_id
    references machine_channel_crops.local_id for this link's machine (a
    cross-table natural key, like piece_uuid — no FK).
    """

    __tablename__ = "piece_crop_link_members"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id = Column(UUID(as_uuid=True), ForeignKey("piece_crop_links.id", ondelete="CASCADE"), nullable=False)
    crop_local_id = Column(BigInteger, nullable=False)
    is_same = Column(Boolean, nullable=False)
    was_predicted = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("link_id", "crop_local_id", name="uq_piece_crop_link_members_link_crop"),
        Index("ix_piece_crop_link_members_link_id", "link_id"),
    )
