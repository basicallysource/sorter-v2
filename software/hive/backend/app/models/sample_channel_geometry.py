import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, FLOAT_ARRAY_VARIANT


class SampleChannelGeometry(Base):
    """The machine's channel-region geometry for ONE sample's full frame, stored
    per-sample on purpose: the region a user draws on their machine can change at
    any time, and carrying the geometry on each sample makes every frame
    self-describing — no versioning and no before/after reconciliation. It is the
    data Hive needs to crop a full frame down to where the channel actually is
    (mask outline + the annulus/arc model), reconstructed from the sorter's
    channel_polygons blob for this sample's source_role. Deliberately flat, typed
    columns + native float arrays — never a JSON blob.
    """

    __tablename__ = "sample_channel_geometry"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sample_id = Column(
        UUID(as_uuid=True),
        ForeignKey("samples.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # Which channel/camera this geometry describes (mirrors samples.source_role).
    source_role = Column(String, nullable=True)
    # Resolution the geometry was defined against; scale to the uploaded frame.
    frame_width = Column(Integer, nullable=True)
    frame_height = Column(Integer, nullable=True)
    # The mask outline — the essential crop data. fillPoly(polygon_x, polygon_y).
    polygon_x = Column(FLOAT_ARRAY_VARIANT, nullable=True)
    polygon_y = Column(FLOAT_ARRAY_VARIANT, nullable=True)
    # Annulus model (radial pivot + radii + section-zero reference angle).
    center_x = Column(Float, nullable=True)
    center_y = Column(Float, nullable=True)
    inner_radius = Column(Float, nullable=True)
    outer_radius = Column(Float, nullable=True)
    exit_outer_radius = Column(Float, nullable=True)
    section_zero_angle_deg = Column(Float, nullable=True)
    reverse = Column(Boolean, nullable=True)
    # Drop / exit / precise arc zones, flattened (each zone: outer + inner span).
    drop_start_outer_angle = Column(Float, nullable=True)
    drop_end_outer_angle = Column(Float, nullable=True)
    drop_start_inner_angle = Column(Float, nullable=True)
    drop_end_inner_angle = Column(Float, nullable=True)
    exit_start_outer_angle = Column(Float, nullable=True)
    exit_end_outer_angle = Column(Float, nullable=True)
    exit_start_inner_angle = Column(Float, nullable=True)
    exit_end_inner_angle = Column(Float, nullable=True)
    precise_start_outer_angle = Column(Float, nullable=True)
    precise_end_outer_angle = Column(Float, nullable=True)
    precise_start_inner_angle = Column(Float, nullable=True)
    precise_end_inner_angle = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    sample = relationship("Sample", back_populates="channel_geometry")
