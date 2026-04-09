import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class Sample(Base):
    __tablename__ = "samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("upload_sessions.id", ondelete="CASCADE"), nullable=False)
    local_sample_id = Column(String, nullable=False)
    source_role = Column(String, nullable=True)
    capture_reason = Column(String, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    image_path = Column(String, nullable=False)
    full_frame_path = Column(String, nullable=True)
    overlay_path = Column(String, nullable=True)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    detection_algorithm = Column(String, nullable=True)
    detection_bboxes = Column(JSON_VARIANT, nullable=True)
    detection_count = Column(Integer, nullable=True)
    detection_score = Column(Float, nullable=True)
    extra_metadata = Column(JSON_VARIANT, nullable=True)
    review_status = Column(String, nullable=False, default="unreviewed")
    review_count = Column(Integer, nullable=False, default=0)
    accepted_count = Column(Integer, nullable=False, default=0)
    rejected_count = Column(Integer, nullable=False, default=0)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    machine = relationship("Machine", back_populates="samples")
    upload_session = relationship("UploadSession", back_populates="samples")
    reviews = relationship("SampleReview", back_populates="sample", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('unreviewed', 'in_review', 'accepted', 'rejected', 'conflict')",
            name="ck_samples_review_status",
        ),
        UniqueConstraint("upload_session_id", "local_sample_id", name="uq_samples_session_local"),
        Index("ix_samples_review_status", "review_status"),
        Index("ix_samples_machine_id", "machine_id"),
        Index("ix_samples_upload_session_id", "upload_session_id"),
        Index("ix_samples_source_role", "source_role"),
        Index("ix_samples_uploaded_at", "uploaded_at"),
    )
