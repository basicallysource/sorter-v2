import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class SortingProfileAiMessage(Base):
    __tablename__ = "sorting_profile_ai_messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profiles.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    version_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profile_versions.id", ondelete="SET NULL"), nullable=True)
    applied_version_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profile_versions.id", ondelete="SET NULL"), nullable=True)
    selected_rule_id = Column(String, nullable=True)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    model = Column(String, nullable=True)
    usage_json = Column(JSON_VARIANT, nullable=True)
    proposal_json = Column(JSON_VARIANT, nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    profile = relationship("SortingProfile", back_populates="ai_messages")
    user = relationship("User", back_populates="profile_ai_messages")
    version = relationship("SortingProfileVersion", foreign_keys=[version_id])
    applied_version = relationship("SortingProfileVersion", foreign_keys=[applied_version_id])

    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="ck_sorting_profile_ai_messages_role"),
        Index("ix_sorting_profile_ai_messages_profile_id", "profile_id"),
        Index("ix_sorting_profile_ai_messages_user_id", "user_id"),
        Index("ix_sorting_profile_ai_messages_created_at", "created_at"),
    )
