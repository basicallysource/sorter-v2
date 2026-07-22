import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachinePieceRejectionReason(Base):
    """A capture issue the MACHINE OPERATOR flagged on a piece, one row per
    (machine, piece, reason) so the flags are queryable — "how many pieces were
    flagged blurry this week" is a GROUP BY, not a scan over JSON.

    Synced from the machine's piece_corrections stream, which carries the whole
    reason set per edit and is applied replace-all here. Reason codes are
    free-form slugs; most ("no_piece" / "multiple_pieces" / "not_lego" /
    "assembly" / "pieces_entangled") match the piece_rejections vocabulary, so an
    operator's verdict and a Hive labeler's verdict mean the same thing
    ("blurry" is Sorter-only). Distinct from PieceRejection: that one is
    per-labeler and set on Hive.
    """

    __tablename__ = "machine_piece_rejection_reasons"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint(
            "machine_id", "piece_uuid", "reason", name="uq_machine_piece_rejection_reasons_piece_reason"
        ),
        Index("ix_machine_piece_rejection_reasons_machine_piece", "machine_id", "piece_uuid"),
        Index("ix_machine_piece_rejection_reasons_reason", "reason"),
    )
