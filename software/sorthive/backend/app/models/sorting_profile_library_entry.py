import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base


class SortingProfileLibraryEntry(Base):
    __tablename__ = "sorting_profile_library_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profiles.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="profile_library_entries")
    profile = relationship("SortingProfile", back_populates="library_entries")

    __table_args__ = (
        UniqueConstraint("user_id", "profile_id", name="uq_sorting_profile_library_entries_user_profile"),
        Index("ix_sorting_profile_library_entries_user_id", "user_id"),
        Index("ix_sorting_profile_library_entries_profile_id", "profile_id"),
    )
