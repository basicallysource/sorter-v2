import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base


class MachineSetProgress(Base):
    __tablename__ = "machine_set_progress"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    assignment_id = Column(UUID(as_uuid=True), ForeignKey("machine_profile_assignments.id", ondelete="CASCADE"), nullable=False)
    set_num = Column(String, nullable=False)
    part_num = Column(String, nullable=False)
    color_id = Column(Integer, nullable=False)
    quantity_needed = Column(Integer, nullable=False)
    quantity_found = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    machine = relationship("Machine")
    assignment = relationship("MachineProfileAssignment")

    __table_args__ = (
        UniqueConstraint("assignment_id", "set_num", "part_num", "color_id", name="uq_machine_set_progress_assignment_part"),
        Index("ix_machine_set_progress_machine_id", "machine_id"),
        Index("ix_machine_set_progress_assignment_id", "assignment_id"),
    )
