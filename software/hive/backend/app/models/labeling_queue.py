from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, false, text
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
    ``has_palette``: a classification frame of the machine near the piece's
    arrival showed the colour reference palette (``app.services.piece_palette``),
    for the grid's palette badge and filter. ``has_training_label``: the piece
    has a colour from a training run that counts (``app.services.training_runs``),
    so the grid treats it as colour-labelled; kept by the worker and by the
    sync endpoints when a piece's or a run's training state changes.
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
    has_palette = Column(Boolean, nullable=False, default=False, server_default=false())
    has_training_label = Column(Boolean, nullable=False, default=False, server_default=false())

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

# The grid's walks when it shows only pieces with same-piece candidates (its
# default): pieces from before channel crops synced, or from a machine without
# C2/C3 cameras, have none, and a walk of every piece read all of them first.
Index(
    "ix_labeling_queue_candidates_arrival",
    LabelingQueueEntry.arrival_at,
    LabelingQueueEntry.machine_id,
    LabelingQueueEntry.piece_uuid,
    postgresql_where=text("has_candidates IS true"),
)
Index(
    "ix_labeling_queue_machine_candidates_arrival",
    LabelingQueueEntry.machine_id,
    LabelingQueueEntry.arrival_at,
    LabelingQueueEntry.piece_uuid,
    postgresql_where=text("has_candidates IS true"),
)

# The palette filter: the walks of the two arrival indexes over only the pieces
# with the palette in view near them. The predicate is written the way
# services/review_queue.py filters (has_palette IS true), so the planner can
# match it.
Index(
    "ix_labeling_queue_palette_arrival",
    LabelingQueueEntry.arrival_at,
    LabelingQueueEntry.machine_id,
    LabelingQueueEntry.piece_uuid,
    postgresql_where=LabelingQueueEntry.has_palette.is_(True),
    sqlite_where=LabelingQueueEntry.has_palette.is_(True),
)
Index(
    "ix_labeling_queue_palette_machine_arrival",
    LabelingQueueEntry.machine_id,
    LabelingQueueEntry.arrival_at,
    LabelingQueueEntry.piece_uuid,
    postgresql_where=LabelingQueueEntry.has_palette.is_(True),
    sqlite_where=LabelingQueueEntry.has_palette.is_(True),
)


# The colour sorts' walk of the pieces a training run labelled and no person
# has (services/review_queue.py): the two arrival walks over only those pieces,
# the predicate written as the queue's query writes it.
Index(
    "ix_labeling_queue_training_arrival",
    LabelingQueueEntry.arrival_at,
    LabelingQueueEntry.machine_id,
    LabelingQueueEntry.piece_uuid,
    postgresql_where=LabelingQueueEntry.has_training_label.is_(True),
    sqlite_where=LabelingQueueEntry.has_training_label.is_(True),
)
Index(
    "ix_labeling_queue_training_machine_arrival",
    LabelingQueueEntry.machine_id,
    LabelingQueueEntry.arrival_at,
    LabelingQueueEntry.piece_uuid,
    postgresql_where=LabelingQueueEntry.has_training_label.is_(True),
    sqlite_where=LabelingQueueEntry.has_training_label.is_(True),
)


class LabelingQueueCount(Base):
    """How many queue pieces each machine has that are old enough to label,
    and how many pieces its training runs labelled with a colour that counts.

    Recounted by the queue worker every pass, so the labeling page's "of N
    pieces" is a sum over these rows instead of a count over the fleet.
    ``training_labeled`` sums the counts kept on the machine's runs that are
    not excluded (machine_training_runs.labeled_count).
    """

    __tablename__ = "labeling_queue_counts"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    labelable = Column(BigInteger, nullable=False, default=0)
    training_labeled = Column(BigInteger, nullable=False, default=0, server_default="0")
    computed_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class LabelingQueueState(Base):
    """The queue worker's progress: one row, id 1.

    ``last_pass_at`` is when the last pass STARTED; the next pass looks at rows
    that reached Hive since then (less an overlap). ``reconciled_at`` is when
    the last full re-evaluation started; null until the first one, which is
    what fills the queue after a fresh deploy. ``palette_model_sha256`` is the
    swatch model whose calls ``has_palette`` was worked out from; when the
    model the palette filter reads changes, the next pass re-evaluates all.
    """

    __tablename__ = "labeling_queue_state"

    id = Column(Integer, primary_key=True, default=1)
    last_pass_at = Column(DateTime(timezone=True), nullable=True)
    reconciled_at = Column(DateTime(timezone=True), nullable=True)
    palette_model_sha256 = Column(String(64), nullable=True)
