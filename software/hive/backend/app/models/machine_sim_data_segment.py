import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineSimDataSegment(Base):
    """A feeder-dynamics ("sim data") capture segment synced up from a machine.

    Each segment is a gzipped JSONL file of timestamped records — perception
    piece states (bboxes/COM positions from the vision model), stepper
    commands, config changes, dispense events — captured while the machine was
    actively sorting. The first record inside the file is a full meta snapshot
    of the machine context (setup, feeder/classification modes, tuning
    configs, polygons, code version); the columns here are just the summary
    needed to filter segments without opening files. Training data for feeder
    control / simulation models.
    """

    __tablename__ = "machine_sim_data_segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    # The machine's sqlite autoincrement segment id — drives the per-target
    # sync watermark and is the natural key for a (machine, segment) row.
    local_id = Column(BigInteger, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    ended_at = Column(DateTime(timezone=True), nullable=True)
    records = Column(Integer, nullable=True)
    bytes = Column(BigInteger, nullable=True)
    machine_setup = Column(String, nullable=True)
    feeder_mode = Column(String, nullable=True)
    classification_mode = Column(String, nullable=True)
    # "session" / "background" when the pulse-perception auto-tuner was varying
    # params during capture (richer excitation), NULL for plain sorting.
    autotune_mode = Column(String, nullable=True)
    # Object-storage key of the gzipped JSONL file. NULL when the segment was
    # evicted from the machine's local store before it could be synced.
    data_key = Column(String, nullable=True)
    evicted_locally = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("machine_id", "local_id", name="uq_machine_sim_data_segments_machine_local"),
        Index("ix_machine_sim_data_segments_machine_local_id", "machine_id", "local_id"),
        Index("ix_machine_sim_data_segments_machine_started", "machine_id", "started_at"),
    )
