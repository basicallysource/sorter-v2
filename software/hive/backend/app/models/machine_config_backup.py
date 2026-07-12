import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class MachineConfigBackup(Base):
    """A versioned snapshot of a machine's settings, pushed by the sorter.

    The sorter content-hashes its config (machine_params.toml + curated
    local_state) before sending; a new row is only created when the hash differs
    from the machine's latest backup, so ``version`` increments on real changes
    only. ``payload`` holds the full snapshot so a machine can restore any
    version verbatim.
    """

    __tablename__ = "machine_config_backups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)
    content_hash = Column(String, nullable=False)
    payload = Column(JSON_VARIANT, nullable=False)
    # What prompted the backup: "config_change" (write hook), "heartbeat"
    # (drift safety net), or "manual".
    trigger = Column(String, nullable=False, default="config_change")
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    machine = relationship("Machine")

    __table_args__ = (
        UniqueConstraint("machine_id", "version", name="uq_machine_config_backups_machine_version"),
        Index("ix_machine_config_backups_machine_id", "machine_id"),
        Index("ix_machine_config_backups_created_at", "created_at"),
    )
