import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import JSON_VARIANT, Base


class SampleSwatchRun(Base):
    """One pass of a swatch finder over a sample's full frame: which model,
    how many palette tiles it found, what looked wrong with the palette as a
    whole, and how long it took. The tiles are ``SampleSwatch`` rows.

    A newer model adds a run beside the old ones, so readings from two models
    can be compared on the same frame. The same model file (by sha256) run
    again replaces its earlier run, which keeps a retried job from storing
    the same readings twice.
    """

    __tablename__ = "sample_swatch_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sample_id = Column(UUID(as_uuid=True), ForeignKey("samples.id", ondelete="CASCADE"), nullable=False)
    # Kept when the model's file is removed from the scan folder (and its
    # registry row with it): the name and sha below still say what ran.
    model_id = Column(UUID(as_uuid=True), ForeignKey("swatch_models.id", ondelete="SET NULL"), nullable=True)
    model_name = Column(String, nullable=False)
    model_sha256 = Column(String(64), nullable=False)
    frame_width = Column(Integer, nullable=False)
    frame_height = Column(Integer, nullable=False)
    swatch_count = Column(Integer, nullable=False, default=0)
    # About the palette as a whole: "neutrals_out_of_order", "repeated_colour".
    flags = Column(JSON_VARIANT, nullable=False, default=list)
    # Wall time of the pass: decoding the frame, the network, reading the tiles.
    seconds = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    swatches = relationship(
        "SampleSwatch",
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="SampleSwatch.position",
    )

    __table_args__ = (
        UniqueConstraint("sample_id", "model_sha256", name="uq_sample_swatch_runs_sample_model"),
        Index("ix_sample_swatch_runs_sample_id", "sample_id"),
        Index("ix_sample_swatch_runs_model_sha256", "model_sha256"),
    )


class SampleSwatch(Base):
    """One palette tile found in a frame, and its reading. Pixel positions are
    in the full-resolution frame; colours are sRGB 0..255 of the tile's flat
    top face, its edges left out. A reading is stored with what might make it
    untrustworthy (``flags``: "clipped", "uneven", "small", "unsure_colour"),
    never dropped."""

    __tablename__ = "sample_swatches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(UUID(as_uuid=True), ForeignKey("sample_swatch_runs.id", ondelete="CASCADE"), nullable=False)
    # Order along the palette's long direction (top to bottom, or left to
    # right), so the same tile has the same position frame to frame.
    position = Column(Integer, nullable=False)
    colour = Column(String, nullable=False)
    bricklink_color_id = Column(Integer, nullable=True)
    # The network's mean probability of that colour, and of top face, over the tile.
    colour_score = Column(Float, nullable=False)
    surface_score = Column(Float, nullable=False)
    pixels = Column(Integer, nullable=False)
    median_r = Column(Float, nullable=False)
    median_g = Column(Float, nullable=False)
    median_b = Column(Float, nullable=False)
    std_r = Column(Float, nullable=False)
    std_g = Column(Float, nullable=False)
    std_b = Column(Float, nullable=False)
    # Share of the pixels with a channel at the camera's ceiling.
    clipped = Column(Float, nullable=False)
    centre_x = Column(Float, nullable=False)
    centre_y = Column(Float, nullable=False)
    box_x0 = Column(Integer, nullable=False)
    box_y0 = Column(Integer, nullable=False)
    box_x1 = Column(Integer, nullable=False)
    box_y1 = Column(Integer, nullable=False)
    # Long and short sides of the top face (a 1x2 tile's length is about twice a 1x1's).
    length = Column(Float, nullable=False)
    width = Column(Float, nullable=False)
    flags = Column(JSON_VARIANT, nullable=False, default=list)

    run = relationship("SampleSwatchRun", back_populates="swatches")

    __table_args__ = (
        UniqueConstraint("run_id", "position", name="uq_sample_swatches_run_position"),
    )
