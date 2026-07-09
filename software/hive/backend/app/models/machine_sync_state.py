from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineSyncState(Base):
    __tablename__ = "machine_sync_state"

    # Server-held high-water mark: the max local_id this Hive has durably
    # accepted for (machine, data_type). Advanced in the same commit as the
    # batch upsert, so it always trails committed data.
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    data_type = Column(String, primary_key=True)
    max_local_id = Column(BigInteger, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
