from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKeyConstraint, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class PieceLinkScore(Base):
    """The active link model's same-piece score for each candidate crop of a
    piece, so opening the piece again is a row read instead of ~40 crop reads
    from storage and a model run.

    Keyed by the model's combined sha256: a new model (or a replaced file)
    scores afresh. ``scores`` maps a channel crop's local_id (as a string, it is
    JSON) to its probability. Crops that synced after the first open are scored
    and merged in on the next open. The pick threshold is not stored: it is the
    model's, read when serving, so changing it never needs a rescore.
    """

    __tablename__ = "piece_link_scores"

    machine_id = Column(UUID(as_uuid=True), primary_key=True)
    piece_uuid = Column(String, primary_key=True)
    model_sha256 = Column(String(64), primary_key=True)
    model_name = Column(String, nullable=True)
    scores = Column(JSON_VARIANT, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        ForeignKeyConstraint(
            ["machine_id", "piece_uuid"],
            ["machine_pieces.machine_id", "machine_pieces.piece_uuid"],
            ondelete="CASCADE",
            name="fk_piece_link_scores_piece",
        ),
    )


class PieceColorGuess(Base):
    """A piece's pixel-average colour and the active colour model's prediction,
    worked out from its crops once and then served from here.

    ``model_sha256`` is the colour model's sha256, or '' when no model was
    active. ``seqs`` lists the crops the guess was made from; when the piece's
    usable crops change, the guess is made again.
    """

    __tablename__ = "piece_color_guesses"

    machine_id = Column(UUID(as_uuid=True), primary_key=True)
    piece_uuid = Column(String, primary_key=True)
    model_sha256 = Column(String(64), primary_key=True)
    seqs = Column(JSON_VARIANT, nullable=False, default=list)
    pixel_guess = Column(JSON_VARIANT, nullable=True)
    model_prediction = Column(JSON_VARIANT, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        ForeignKeyConstraint(
            ["machine_id", "piece_uuid"],
            ["machine_pieces.machine_id", "machine_pieces.piece_uuid"],
            ondelete="CASCADE",
            name="fk_piece_color_guesses_piece",
        ),
    )
