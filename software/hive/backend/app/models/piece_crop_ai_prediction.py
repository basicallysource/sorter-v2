import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class PieceCropAiPrediction(Base):
    """A vision model's "which upstream crops are the same physical piece" guess
    for one classified piece — the AI analog of the time/angle heuristic.

    Populated out-of-band (scripts/run_piece_crop_ai_match.py): the model is shown
    the piece's C4 anchor image plus a numbered contact-sheet grid of the
    heuristic's candidate C2/C3 crops and returns which cells match. We store the
    candidate set it was shown (candidate_local_ids) and the ones it picked
    (same_local_ids) so the labeling page can pre-select the AI's picks instead of
    the heuristic's when a prediction exists. One row per (machine, piece); a
    re-run overwrites it. Kept separate from piece_crop_links (human labels) — this
    is a machine suggestion, not ground truth, and must not be confused with the
    was_predicted heuristic-accuracy signal stored on human links.
    """

    __tablename__ = "piece_crop_ai_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    model = Column(String, nullable=False)
    reasoning = Column(String, nullable=True)
    # Crop local_ids (machine_channel_crops.local_id) the model was shown, and the
    # subset it judged to be the same piece. JSONB lists of ints.
    candidate_local_ids = Column(JSON_VARIANT, nullable=False)
    same_local_ids = Column(JSON_VARIANT, nullable=False)
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("machine_id", "piece_uuid", name="uq_piece_crop_ai_predictions_machine_piece"),
        Index("ix_piece_crop_ai_predictions_machine_piece", "machine_id", "piece_uuid"),
    )
