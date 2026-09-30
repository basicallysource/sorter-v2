import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class Kit(Base):
    """A list of parts in colors with quantities: a LEGO set's inventory, a
    customer's order, anything a sorter should collect into one bin. A profile
    uses a kit through a kit rule; once the bin has enough of a part, further
    pieces of it go on to the next rule.

    `parts` holds {part_num, part_source, color_id, quantity, part_name,
    color_name, img_url}. part_source is "rebrickable" (the catalog's part and
    color IDs) or "bricklink" (BrickLink IDs the catalog does not know).
    color_id -1 means any color."""

    __tablename__ = "kits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    image_url = Column(String, nullable=True)
    source = Column(String, nullable=False, default="custom")
    set_num = Column(String, nullable=True)
    set_meta = Column(JSON_VARIANT, nullable=True)
    include_spares = Column(Boolean, nullable=False, default=False)
    visibility = Column(String, nullable=False, default="private")
    parts = Column(JSON_VARIANT, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    owner = relationship("User")

    __table_args__ = (
        CheckConstraint("visibility IN ('private', 'unlisted', 'public')", name="ck_kits_visibility"),
        CheckConstraint("source IN ('custom', 'set', 'bricklink')", name="ck_kits_source"),
        Index("ix_kits_owner_id", "owner_id"),
    )
