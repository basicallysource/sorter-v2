import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, false
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class MachineTrainingRun(Base):
    """A training run on a sorter: a stretch of sorting in which every piece
    the machine saw counts as what the run was for. In a colour run
    (``mode`` "color") the operator fed pieces of ``color_ids`` only, so each
    piece of the run is labelled with one of them (``machine_pieces.training_*``).

    Synced from the machine (data type ``training_runs``) and never written by
    Hive, except the counts: ``piece_count``, ``labeled_count`` (a colour and
    not excluded) and ``excluded_count`` over the run's pieces, recounted when
    a batch of piece records touches the run and when the run itself syncs, so
    no request counts the pieces of a run."""

    __tablename__ = "machine_training_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    # The machine's own id for the run: the natural key, and what its pieces
    # carry as machine_pieces.training_run_uuid.
    run_uuid = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    # BrickLink colour ids, as strings of digits: every colour its segments used.
    color_ids = Column(JSON_VARIANT, nullable=False, default=list)
    # The run's segments, oldest first: the operator changes the colours fed
    # without ending the run, and each change starts a segment. Each is
    # {segment_uuid, color_ids, started_at, ended_at (null while open)}, the
    # times as ISO 8601 in UTC; a piece names its own (training_segment_uuid).
    segments = Column(JSON_VARIANT, nullable=False, default=list)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    # The operator excluded the whole run: none of its labels count.
    excluded = Column(Boolean, nullable=False, default=False, server_default=false())
    # When the machine last changed the run (its clock).
    updated_at = Column(DateTime(timezone=True), nullable=True)
    piece_count = Column(Integer, nullable=False, default=0, server_default="0")
    labeled_count = Column(Integer, nullable=False, default=0, server_default="0")
    excluded_count = Column(Integer, nullable=False, default=0, server_default="0")
    # When Hive first and last received the run.
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    received_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("machine_id", "run_uuid", name="uq_machine_training_runs_machine_run"),
        # A machine's runs newest first (its page lists them by keyset).
        Index("ix_machine_training_runs_machine_started", "machine_id", "started_at", "id"),
    )
