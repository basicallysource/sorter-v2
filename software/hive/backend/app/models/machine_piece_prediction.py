import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base

# The source of the predictions a machine made while sorting; any other source
# is a later run over the piece's stored images, by its label.
SOURCE_LIVE = "live"


class MachinePiecePrediction(Base):
    """One ranked answer a piece got, kept as the machine stored it, from any
    source: the machine's own classification while sorting (`source` "live":
    each Brickognize request's parts and colours with their scores, the
    hosted colour model's top three; `applied` marks the one part and the one
    colour the piece took) or a later run of a model over the piece's stored
    images, by the run's label (e.g. "colorpred-v4 rerun, 13 Oct").

    Synced from the machine's piece_predictions table (data type
    piece_predictions, cursor local_id). Rows never change on the machine;
    re-sends upsert by (machine, piece, source, request, kind, rank). A later
    run can also be imported on Hive directly (POST
    /api/records/machines/{id}/predictions), for pieces the machine no longer
    keeps.
    """

    __tablename__ = "machine_piece_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    piece_uuid = Column(String, nullable=False)
    # The machine's piece_predictions id: the sync cursor. 0 for a prediction
    # imported on Hive itself (the records API), which no machine row backs.
    local_id = Column(BigInteger, nullable=False)
    # "live", or a later run's label. Sorters older than sources send none:
    # theirs are all live.
    source = Column(String, nullable=False, default=SOURCE_LIVE, server_default=SOURCE_LIVE)
    # Which of the source's requests: combined / single_burst (a Brickognize
    # request's label) or hosted, live; a later run's model name.
    request = Column(String, nullable=False)
    # brickognize / hive_basically / the provider a later run names.
    provider = Column(String, nullable=False)
    # The model's identity when there is one (its sha256).
    model = Column(String, nullable=True)
    # The model's name as the machine knew it (None from older sorters).
    model_name = Column(String, nullable=True)
    # The piece's images the prediction was made from, as the machine keeps
    # them: [{"set": "burst" | "link", "seq", "channel"}], "burst" seqs being
    # machine_piece_images seqs. None when not recorded.
    images = Column(JSON_VARIANT, nullable=True)
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
            "machine_id", "piece_uuid", "source", "request", "kind", "rank",
            name="uq_machine_piece_predictions_piece_source_request_kind_rank",
        ),
        # Each piece's top colour from a later run (the records API reads a
        # page of pieces' at a time).
        Index(
            "ix_machine_piece_predictions_later_colors",
            "machine_id",
            "piece_uuid",
            postgresql_where=text("source <> 'live' AND kind = 'color' AND rank = 0"),
        ),
    )
