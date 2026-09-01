import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class MachineHardwareReport(Base):
    """Append-only log of a machine's hardware/software specs over time.

    The sorter attaches a specs snapshot to its heartbeat; a new row is written
    only when the machine reboots (``boot_id`` changes) or the specs content
    changes (``content_hash`` differs from the latest row), so the log grows on
    real events, not on every keep-alive. ``specs`` holds the full snapshot the
    machine sent; a compact summary of it lives on ``machines.hardware_info``
    for the dashboard.
    """

    __tablename__ = "machine_hardware_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    boot_id = Column(String, nullable=True)
    content_hash = Column(String, nullable=False)
    specs = Column(JSON_VARIANT, nullable=False)
    reported_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    machine = relationship("Machine")

    __table_args__ = (
        Index("ix_machine_hardware_reports_machine_reported", "machine_id", "reported_at"),
    )
