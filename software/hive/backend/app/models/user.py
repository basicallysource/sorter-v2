import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=True)
    github_id = Column(String, unique=True, nullable=True, index=True)
    github_login = Column(String, nullable=True)
    avatar_url = Column(String, nullable=True)
    display_name = Column(String, nullable=True)
    openrouter_api_key_encrypted = Column(String, nullable=True)
    preferred_ai_model = Column(String, nullable=True)
    role = Column(String, nullable=False, default="member")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    machines = relationship("Machine", back_populates="owner", cascade="all, delete-orphan")
    reviews = relationship("SampleReview", back_populates="reviewer", cascade="all, delete-orphan")
    sorting_profiles = relationship(
        "SortingProfile",
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="SortingProfile.owner_id",
    )
    profile_library_entries = relationship(
        "SortingProfileLibraryEntry",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    profile_ai_messages = relationship(
        "SortingProfileAiMessage",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    machine_profile_assignments = relationship(
        "MachineProfileAssignment",
        back_populates="assigned_by",
        foreign_keys="MachineProfileAssignment.assigned_by_id",
    )

    __table_args__ = (
        CheckConstraint("role IN ('member', 'reviewer', 'admin')", name="ck_users_role"),
    )

    @property
    def has_password(self) -> bool:
        return bool(self.password_hash)

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key_encrypted)
