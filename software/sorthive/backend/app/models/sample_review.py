import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base


class SampleReview(Base):
    __tablename__ = "sample_reviews"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sample_id = Column(UUID(as_uuid=True), ForeignKey("samples.id", ondelete="CASCADE"), nullable=False)
    reviewer_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    decision = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    sample = relationship("Sample", back_populates="reviews")
    reviewer = relationship("User", back_populates="reviews")

    __table_args__ = (
        CheckConstraint("decision IN ('accept', 'reject')", name="ck_sample_reviews_decision"),
        UniqueConstraint("sample_id", "reviewer_id", name="uq_sample_reviews_sample_reviewer"),
        Index("ix_sample_reviews_sample_id", "sample_id"),
        Index("ix_sample_reviews_reviewer_id", "reviewer_id"),
    )
