from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineStatsCache(Base):
    """Pre-computed per-machine dashboard metrics.

    Recomputing piece/sample aggregates on every dashboard/overview request is
    expensive once a machine has synced hundreds of thousands of pieces. A
    background worker (app.services.machine_stats) refreshes one row per machine
    on an hourly cadence; the API serves these rows directly. One row per
    machine, upserted in place — no history.
    """

    __tablename__ = "machine_stats_cache"

    machine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("machines.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # Piece-derived (see machine_pieces).
    pieces_seen = Column(BigInteger, nullable=False, default=0)
    distributed = Column(BigInteger, nullable=False, default=0)
    classified = Column(BigInteger, nullable=False, default=0)
    unique_parts = Column(Integer, nullable=False, default=0)
    unique_colors = Column(Integer, nullable=False, default=0)
    first_seen = Column(DateTime(timezone=True), nullable=True)
    last_seen = Column(DateTime(timezone=True), nullable=True)
    active_seconds = Column(Float, nullable=False, default=0.0)
    overall_ppm = Column(Float, nullable=False, default=0.0)
    ontime_pct = Column(Float, nullable=False, default=0.0)

    # Sample-derived (see samples / upload_sessions / machine_set_progress).
    total_samples = Column(Integer, nullable=False, default=0)
    accepted_samples = Column(Integer, nullable=False, default=0)
    first_capture = Column(DateTime(timezone=True), nullable=True)
    last_capture = Column(DateTime(timezone=True), nullable=True)
    total_sessions = Column(Integer, nullable=False, default=0)
    parts_found = Column(Integer, nullable=False, default=0)
    parts_needed = Column(Integer, nullable=False, default=0)

    computed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
