from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base, JSON_VARIANT


class MachineDefaultOverride(Base):
    """One default every sorter is served, set by an admin over the one in
    Hive's code (services/machine_defaults.py). `path` names the leaf
    (`steppers.chute.sgthrs`)."""

    __tablename__ = "machine_default_overrides"

    path = Column(String, primary_key=True)
    value = Column(JSON_VARIANT, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
