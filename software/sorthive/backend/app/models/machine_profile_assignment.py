import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base


class MachineProfileAssignment(Base):
    __tablename__ = "machine_profile_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False, unique=True)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profiles.id", ondelete="CASCADE"), nullable=False)
    desired_version_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profile_versions.id", ondelete="SET NULL"), nullable=True)
    active_version_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profile_versions.id", ondelete="SET NULL"), nullable=True)
    assigned_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    artifact_hash = Column(String, nullable=True)
    last_error = Column(String, nullable=True)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    last_activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    machine = relationship("Machine", back_populates="profile_assignment")
    profile = relationship("SortingProfile", back_populates="machine_assignments")
    desired_version = relationship(
        "SortingProfileVersion",
        back_populates="desired_assignments",
        foreign_keys=[desired_version_id],
    )
    active_version = relationship(
        "SortingProfileVersion",
        back_populates="active_assignments",
        foreign_keys=[active_version_id],
    )
    assigned_by = relationship(
        "User",
        back_populates="machine_profile_assignments",
        foreign_keys=[assigned_by_id],
    )

    __table_args__ = (
        Index("ix_machine_profile_assignments_machine_id", "machine_id"),
        Index("ix_machine_profile_assignments_profile_id", "profile_id"),
    )
