from sqlalchemy import BigInteger, Column, Date, Float, ForeignKey
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineDailyStats(Base):
    """Per-machine, per-day sorting metrics — the substrate for the analytics
    time-series (pieces/PPM/capacity over time) across any set of machines.

    One row per (machine, UTC day of seen_at). active_seconds is the summed
    gap between consecutive pieces, ignoring idle gaps (same rule as
    machine_stats), each gap counted on the day of the later piece. PPM is
    derived (distributed * 60 / active_seconds). The stats worker writes the
    rows of the days whose pieces changed, from the machine-days it keeps
    (app.services.piece_days); a day left with no pieces loses its row.
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
