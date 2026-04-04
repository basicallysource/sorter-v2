import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class SortingProfile(Base):
    __tablename__ = "sorting_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    source_profile_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profiles.id", ondelete="SET NULL"), nullable=True)
    source_version_number = Column(Integer, nullable=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    visibility = Column(String, nullable=False, default="private")
    tags = Column(JSON_VARIANT, nullable=True)
    latest_version_number = Column(Integer, nullable=False, default=0)
    latest_published_version_number = Column(Integer, nullable=True)
    library_count = Column(Integer, nullable=False, default=0)
    fork_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    owner = relationship("User", back_populates="sorting_profiles", foreign_keys=[owner_id])
    source_profile = relationship(
        "SortingProfile",
        remote_side=[id],
        back_populates="forks",
        foreign_keys=[source_profile_id],
    )
    forks = relationship("SortingProfile", back_populates="source_profile")
    versions = relationship(
        "SortingProfileVersion",
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="SortingProfileVersion.version_number",
    )
    library_entries = relationship(
        "SortingProfileLibraryEntry",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    ai_messages = relationship(
        "SortingProfileAiMessage",
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    machine_assignments = relationship("MachineProfileAssignment", back_populates="profile")

    __table_args__ = (
        CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="ck_sorting_profiles_visibility",
        ),
        Index("ix_sorting_profiles_owner_id", "owner_id"),
        Index("ix_sorting_profiles_visibility", "visibility"),
    )
