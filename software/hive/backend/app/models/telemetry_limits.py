from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Float, Integer, text

from app.models import Base


class TelemetryLimits(Base):
    """How much telemetry Hive lets a machine send, handed to every machine on
    its heartbeat. One global row (id = 1); while the row is missing the code
    defaults in ``services.telemetry_limits`` apply, so a fresh Hive works
    before an admin has set anything.

    The sample interval fields describe a ramp: a machine captures training
    samples at most every ``sample_burst_interval_s`` per camera, then slows
    toward ``sample_floor_interval_s`` over ``sample_ramp_hours``. The upload
    fields are a per-target budget the machine spends across every file it
    sends (samples, piece images, channel crops, control data).
    """

    __tablename__ = "telemetry_limits"

    id = Column(Integer, primary_key=True)
    sample_burst_interval_s = Column(Float, nullable=False, default=10.0, server_default=text("10.0"))
    sample_floor_interval_s = Column(Float, nullable=False, default=3600.0, server_default=text("3600.0"))
    sample_ramp_hours = Column(Float, nullable=False, default=72.0, server_default=text("72.0"))
    sample_store_max_bytes = Column(BigInteger, nullable=False, default=1073741824, server_default=text("1073741824"))
    upload_bytes_per_minute = Column(BigInteger, nullable=False, default=30000000, server_default=text("30000000"))
    upload_files_per_minute = Column(Integer, nullable=False, default=120, server_default=text("120"))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (CheckConstraint("id = 1", name="ck_telemetry_limits_single_row"),)
