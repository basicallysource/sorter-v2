import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base, JSON_VARIANT


class MachineTelemetryRecord(Base):
    """One telemetry record from a sorter: how it is set up or how it ran.

    Not shown to the machine's owner: it is how the fleet's normal behaviour
    becomes known (agent-docs/telemetry.md). A sorter writes three forms:
    `snapshot` (its state, when it changed: the machine specs), `window` (a
    distribution over up to an hour of sorting: stepper load, camera readings)
    and `event` (something rare, with its context: a stall). `kind` says what
    the record describes and `schema` the version of its data's shape, so old
    and new records read side by side. Records never change on the machine, so
    they are keyed and synced by its local id.
    """

    __tablename__ = "machine_telemetry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    local_id = Column(BigInteger, nullable=False)
    kind = Column(String(64), nullable=False)
    form = Column(String(16), nullable=False)
    schema = Column(Integer, nullable=False, default=1)
    started_at = Column(DateTime(timezone=True), nullable=False)
    ended_at = Column(DateTime(timezone=True), nullable=False)
    data = Column(JSON_VARIANT, nullable=False)
    received_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("machine_id", "local_id", name="uq_machine_telemetry_machine_local"),
        # One machine's records of a kind over time, and the fleet's.
        Index("ix_machine_telemetry_machine_kind_started", "machine_id", "kind", "started_at"),
        Index("ix_machine_telemetry_kind_started", "kind", "started_at"),
    )
