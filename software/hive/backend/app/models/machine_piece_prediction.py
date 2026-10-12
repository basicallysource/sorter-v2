import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachinePiecePrediction(Base):
    """One ranked answer the machine got for a piece, kept as the machine
    stored it: each classification request's parts and colours with their
    scores (Brickognize's combined and single-burst requests, the hosted colour
    model's top three), applied or not. `applied` marks the one part and the
    one colour the piece took.

    Synced from the machine's piece_predictions table (data type
    piece_predictions, cursor local_id). Rows never change on the machine;
    re-sends upsert by (machine, piece, request, kind, rank).
    """

    __tablename__ = "machine_piece_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    # The machine's piece_predictions id: the sync cursor.
    local_id = Column(BigInteger, nullable=False)
    # combined / single_burst (a Brickognize request's label) or hosted.
    request = Column(String, nullable=False)
    # brickognize / hive_basically.
    provider = Column(String, nullable=False)
    # The model's identity when the provider reports one (the hosted model's sha256).
    model = Column(String, nullable=True)
    # part / color.
    kind = Column(String, nullable=False)
    # 0-based, in the provider's own order (Brickognize's rank in its response).
    rank = Column(Integer, nullable=False)
    # A BrickLink colour id as text for a colour, a part number for a part.
    value_id = Column(String, nullable=False)
    value_name = Column(String, nullable=True)
    score = Column(Float, nullable=True)
    applied = Column(Boolean, nullable=False, default=False)
    # When the machine made the prediction.
    predicted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        # Also serves every lookup of one piece's predictions (its leading columns).
        UniqueConstraint(
            "machine_id", "piece_uuid", "request", "kind", "rank",
            name="uq_machine_piece_predictions_piece_request_kind_rank",
        ),
    )
