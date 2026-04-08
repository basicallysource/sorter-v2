import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class Machine(Base):
    __tablename__ = "machines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String, nullable=False)
    token_prefix = Column(String(8), nullable=False)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    hardware_info = Column(JSON_VARIANT, nullable=True)
    last_seen_ip = Column(String, nullable=True)
    local_ui_port = Column(String, nullable=True, default="8000")
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="machines")
    upload_sessions = relationship("UploadSession", back_populates="machine", cascade="all, delete-orphan")
    samples = relationship("Sample", back_populates="machine", cascade="all, delete-orphan")
    profile_assignment = relationship(
        "MachineProfileAssignment",
        back_populates="machine",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        Index("ix_machines_owner_id", "owner_id"),
    )
