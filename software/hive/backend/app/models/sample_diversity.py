from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class SampleDiversityWeek(Base):
    """One machine's active samples of one capture reason and source in one
    week (UTC, from Monday), by how many pieces each shows: what the samples
    diversity overview adds up. Kept by ``services.sample_diversity`` in the
    stats worker's pass; no request writes it."""

    __tablename__ = "sample_diversity_weekly"

    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True)
    week = Column(Date, primary_key=True)
    capture_reason = Column(String, primary_key=True)
    # "unknown" when the samples carry no source.
    source_role = Column(String, primary_key=True)
    # Samples per piece-count bucket, in sample_diversity.BUCKET_KEYS order,
    # then the samples with no piece count.
    buckets = Column(JSON_VARIANT, nullable=False)
    samples = Column(Integer, nullable=False)
    score_sum = Column(Float, nullable=False, default=0.0)
    scored = Column(Integer, nullable=False, default=0)
    first_at = Column(DateTime(timezone=True), nullable=False)
    last_at = Column(DateTime(timezone=True), nullable=False)
    computed_at = Column(DateTime(timezone=True), nullable=False)
