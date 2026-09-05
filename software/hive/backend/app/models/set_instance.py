import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base

SET_INSTANCE_STATUSES = ("open", "complete", "archived")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SetInstance(Base):
    """One physical copy of a LEGO set a user is extracting.

    Progress lives here, not on a machine's profile assignment: the same copy
    is worked on across runs, machines and profile versions, and a user may
    own the same set several times.
    """

    __tablename__ = "set_instances"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    set_source = Column(String, nullable=False, default="rebrickable")
    set_num = Column(String, nullable=False)
    label = Column(String, nullable=False)
    status = Column(String, nullable=False, default="open")
    include_spares = Column(Boolean, nullable=False, default=False)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    user = relationship("User")
    progress = relationship(
        "SetInstanceProgress",
        back_populates="instance",
        cascade="all, delete-orphan",
        order_by="(SetInstanceProgress.part_num, SetInstanceProgress.color_id)",
    )

    __table_args__ = (
        CheckConstraint("status IN ('open', 'complete', 'archived')", name="ck_set_instances_status"),
        Index("ix_set_instances_user_id", "user_id"),
    )


class SetInstanceProgress(Base):
    """Needed vs found per BrickLink part/colour of one set instance."""

    __tablename__ = "set_instance_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    set_instance_id = Column(UUID(as_uuid=True), ForeignKey("set_instances.id", ondelete="CASCADE"), nullable=False)
    part_num = Column(String, nullable=False)
    color_id = Column(Integer, nullable=False)
    quantity_needed = Column(Integer, nullable=False)
    quantity_found = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    instance = relationship("SetInstance", back_populates="progress")

    __table_args__ = (
        UniqueConstraint("set_instance_id", "part_num", "color_id", name="uq_set_instance_progress_part"),
        Index("ix_set_instance_progress_set_instance_id", "set_instance_id"),
    )


class SetInstanceMachineCount(Base):
    """The count a machine last reported for one part of one set instance.

    A sorter counts from zero per tracker session and reports absolute counts;
    the difference to the previous report is what it contributed since. Keeping
    that cursor per machine lets several machines, manual adjustments and a
    tracker restart all add up on the instance instead of overwriting it.
    """

    __tablename__ = "set_instance_machine_counts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    set_instance_id = Column(UUID(as_uuid=True), ForeignKey("set_instances.id", ondelete="CASCADE"), nullable=False)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    part_num = Column(String, nullable=False)
    color_id = Column(Integer, nullable=False)
    quantity_reported = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint("set_instance_id", "machine_id", "part_num", "color_id", name="uq_set_instance_machine_counts_part"),
        Index("ix_set_instance_machine_counts_set_instance_id", "set_instance_id"),
    )
