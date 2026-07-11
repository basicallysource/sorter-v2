from sqlalchemy import BigInteger, Column, Date, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineDailyStats(Base):
    """Per-machine, per-day sorting metrics — the substrate for the analytics
    time-series (pieces/PPM/capacity over time) across any set of machines.

    One row per (machine, calendar day of seen_at). active_seconds is the summed
    gap between consecutive pieces on that day, ignoring idle gaps (same rule as
    machine_stats). PPM is derived (distributed * 60 / active_seconds). A
    background pass (app.services.analytics) upserts these hourly; rows are only
    ever added/updated since pieces aren't deleted.
    """

    __tablename__ = "machine_daily_stats"

    machine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("machines.id", ondelete="CASCADE"),
        primary_key=True,
    )
    day = Column(Date, primary_key=True)
    pieces_seen = Column(BigInteger, nullable=False, default=0)
    distributed = Column(BigInteger, nullable=False, default=0)
    active_seconds = Column(Float, nullable=False, default=0.0)
