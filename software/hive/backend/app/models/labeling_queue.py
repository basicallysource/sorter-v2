from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class LabelingQueueEntry(Base):
    """One piece a person can label, with what the piece grid filters and sorts on.

    A piece belongs here when its record is not dead and at least one of its
    crops is in storage. The grid also waits until it arrived 15 minutes ago
    (its upstream channel crops take that long to sync), which it checks on
    ``arrival_at`` at read time. Kept by ``app.services.labeling_queue``; no
    request writes it.

    Narrow on purpose: every grid request walks one of its indexes in order and
    stops at the page size, instead of joining and sorting the whole of
    machine_pieces. ``arrival_at`` is the piece's ``coalesce(seen_at,
    recorded_at, created_at)``: the grid's "newest" order, the 15-minute rule
    and the same-piece window all use it. ``unidentified``, ``color_id`` and
    ``color_confidence`` are copies of the piece's prediction for the
    "unidentified" and "rare color" sorts; the daily reconcile refreshes them.
    """

    __tablename__ = "labeling_queue"

    machine_id = Column(UUID(as_uuid=True), primary_key=True)
    piece_uuid = Column(String, primary_key=True)
    arrival_at = Column(DateTime(timezone=True), nullable=False)
    # A channel crop sits in the piece's arrival window (the time/angle
    # heuristic's lookback and slop), so the same-piece task has something to show.
    has_candidates = Column(Boolean, nullable=False, default=False)
    unidentified = Column(Boolean, nullable=False, default=False)
    color_id = Column(String, nullable=True)
    color_confidence = Column(Float, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["machine_id", "piece_uuid"],
            ["machine_pieces.machine_id", "machine_pieces.piece_uuid"],
            ondelete="CASCADE",
            name="fk_labeling_queue_piece",
        ),
        Index("ix_labeling_queue_arrival", "arrival_at", "machine_id", "piece_uuid"),
        Index("ix_labeling_queue_machine_arrival", "machine_id", "arrival_at", "piece_uuid"),
    )


# The "likely a rare color" sort: least confident colour prediction first, then
# newest. Mixed directions, so it is declared outside the class.
Index(
    "ix_labeling_queue_color_confidence",
    LabelingQueueEntry.color_confidence,
    LabelingQueueEntry.arrival_at.desc(),
    LabelingQueueEntry.machine_id.desc(),
    LabelingQueueEntry.piece_uuid.desc(),
    postgresql_where=LabelingQueueEntry.color_confidence.isnot(None),
    sqlite_where=LabelingQueueEntry.color_confidence.isnot(None),
)


class LabelingQueueCount(Base):
    """How many queue pieces each machine has that are old enough to label.

    Recounted by the queue worker every pass, so the labeling page's "of N
    pieces" is a sum over these rows instead of a count over the fleet.
    """

    __tablename__ = "labeling_queue_counts"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    labelable = Column(BigInteger, nullable=False, default=0)
    computed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class LabelingQueueState(Base):
    """The queue worker's progress: one row, id 1.

    ``last_pass_at`` is when the last pass STARTED; the next pass looks at rows
    that reached Hive since then (less an overlap). ``reconciled_at`` is when
    the last full re-evaluation started; null until the first one, which is
    what fills the queue after a fresh deploy.
    """

    __tablename__ = "labeling_queue_state"

    id = Column(Integer, primary_key=True, default=1)
    last_pass_at = Column(DateTime(timezone=True), nullable=True)
    reconciled_at = Column(DateTime(timezone=True), nullable=True)
