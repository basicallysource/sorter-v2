from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Column, DateTime, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineStatsCache(Base):
    """Pre-computed per-machine metrics — the ONE cache every stats surface reads.

    Recomputing piece/sample aggregates on every dashboard/overview request is
    expensive once a machine has synced hundreds of thousands of pieces. A
    background worker (app.services.machine_stats) refreshes one row per machine
    on an hourly cadence; the API serves these rows directly. One row per
    machine, upserted in place — no history.

    Why per MACHINE and never per scope: every set a caller can ask about (one
    machine, one owner's fleet, your machines, the whole fleet) is some subset
    of these rows, so caching the machine lets any scope be folded in Python
    from rows already in memory. Caching the scope instead means a new cache
    entry for every question anyone thinks to ask, and two of them eventually
    disagreeing about how many pieces exist.

    That is why the distribution maps below are stored WHOLE rather than as a
    top-15: a top-15 per machine cannot be folded into a correct top-15 for the
    fleet, and the count of distinct parts across a set is the size of the union
    of these keys, which a truncated map cannot give.
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

    # Whole distribution maps for this machine, the input the analytics fold
    # sums over. Shape:
    #   {"status": {"<status>": count},
    #    "parts":  {"<part_id>":  [count, "<part_name>"]},
    #    "colors": {"<color_id>": [count, "<color_name>"]}}
    # Names ride along because a caller ranking parts wants to print one, and
    # re-joining a catalog per request is the cost this cache exists to avoid.
    distributions = Column(JSON, nullable=False, default=dict)

    computed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
