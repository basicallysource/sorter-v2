import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class SortingProfileVersion(Base):
    __tablename__ = "sorting_profile_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profiles.id", ondelete="CASCADE"), nullable=False)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    version_number = Column(Integer, nullable=False)
    label = Column(String, nullable=True)
    change_note = Column(Text, nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    default_category_id = Column(String, nullable=False, default="misc")
    rules_json = Column(JSON_VARIANT, nullable=False)
    fallback_mode_json = Column(JSON_VARIANT, nullable=False)
    compiled_artifact_json = Column(JSON_VARIANT, nullable=False)
    compiled_stats_json = Column(JSON_VARIANT, nullable=True)
    compiled_hash = Column(String, nullable=False)
    compiled_part_count = Column(Integer, nullable=False, default=0)
    coverage_ratio = Column(Float, nullable=True)
    is_published = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    profile = relationship("SortingProfile", back_populates="versions", foreign_keys=[profile_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    desired_assignments = relationship(
        "MachineProfileAssignment",
        back_populates="desired_version",
        foreign_keys="MachineProfileAssignment.desired_version_id",
    )
    active_assignments = relationship(
        "MachineProfileAssignment",
        back_populates="active_version",
        foreign_keys="MachineProfileAssignment.active_version_id",
    )

    __table_args__ = (
        UniqueConstraint("profile_id", "version_number", name="uq_sorting_profile_versions_profile_version"),
        Index("ix_sorting_profile_versions_profile_id", "profile_id"),
        Index("ix_sorting_profile_versions_created_at", "created_at"),
        Index("ix_sorting_profile_versions_is_published", "is_published"),
    )
