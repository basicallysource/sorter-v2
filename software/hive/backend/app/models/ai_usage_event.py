import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class AiUsageEvent(Base):
    __tablename__ = "ai_usage_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    profile_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profiles.id", ondelete="SET NULL"), nullable=True)
    message_id = Column(UUID(as_uuid=True), ForeignKey("sorting_profile_ai_messages.id", ondelete="SET NULL"), nullable=True)
    # what the spend was for: profile_chat, change_note, ...
    purpose = Column(String, nullable=False)
    model = Column(String, nullable=True)
    # one chat turn can be several OpenRouter calls, hence a list
    generation_ids = Column(JSON_VARIANT, nullable=True)
    call_count = Column(Integer, nullable=False, default=1)
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, nullable=False, default=0)
    cache_write_tokens = Column(Integer, nullable=False, default=0)
    # OpenRouter credits, which are USD. Null when the provider did not report a
    # price (some free models, or a call that failed after being billed nothing).
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    user = relationship("User")
    profile = relationship("SortingProfile")
    message = relationship("SortingProfileAiMessage")

    __table_args__ = (
        Index("ix_ai_usage_events_user_id", "user_id"),
        Index("ix_ai_usage_events_profile_id", "profile_id"),
        Index("ix_ai_usage_events_created_at", "created_at"),
        Index("ix_ai_usage_events_user_created", "user_id", "created_at"),
    )
