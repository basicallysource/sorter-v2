import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class Device(Base):
    """A physical sorter as known to the main hive's hosted-services layer.

    Distinct from Machine on purpose. A Machine is an account object — an
    owner's registration of their sorter on some hive, of which there can be
    many. A Device is the sorter itself, enrolled silently the first time it
    uses a hosted service (color prediction today, possibly more later),
    whether or not any account exists. Device rows are admin-only and are
    never surfaced to regular users.

    Merge points, both nullable and unused at enroll time:
    - machine_id: set if/when the operator registers this sorter with an
      account on this hive, so service telemetry can join account data. Signup
      stays a normal fresh flow; adoption is silent.
    - install_id: the anonymous fleet row (installs table), if we ever decide
      to link the two systems. Plain string, no FK — installs are wiped via the
      public /forget endpoint and that deletion must never touch devices.
    """

    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Sorter-generated opaque key, persisted in the machine's local state. Lets a
    # re-enroll (lost token) find its existing row instead of minting a new
    # device and fragmenting the logged images.
    device_key = Column(String(128), nullable=False, unique=True)
    token_hash = Column(String, nullable=False)
    token_prefix = Column(String(8), nullable=False)
    hardware_info = Column(JSON_VARIANT, nullable=True)
    last_seen_ip = Column(String, nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="SET NULL"), nullable=True)
    install_id = Column(String, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_devices_machine_id", "machine_id"),
    )
