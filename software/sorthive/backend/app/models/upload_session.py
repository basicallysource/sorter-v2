import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    source_session_id = Column(String, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    last_upload_at = Column(DateTime(timezone=True), nullable=True)
    sample_count = Column(Integer, nullable=False, default=0)

    machine = relationship("Machine", back_populates="upload_sessions")
    samples = relationship("Sample", back_populates="upload_session", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("machine_id", "source_session_id", name="uq_upload_sessions_machine_source"),
        Index("ix_upload_sessions_machine_id", "machine_id"),
    )
