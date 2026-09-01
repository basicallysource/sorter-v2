import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base

CROP_KIND_PIECE_IMAGE = "piece_image"
CROP_KIND_CHANNEL_CROP = "channel_crop"
CROP_KINDS = (CROP_KIND_PIECE_IMAGE, CROP_KIND_CHANNEL_CROP)

# The one "good example" flag plus the "not good enough for classification"
# reasons. Kept as a tuple so the endpoint and the read-merges iterate the same
# column set instead of repeating the names.
IMAGE_QUALITY_REASON_FIELDS = (
    "low_resolution",
    "motion_blur",
    "not_contained",
    "no_piece_in_frame",
    "other_bad",
)
IMAGE_QUALITY_FLAG_FIELDS = ("high_quality",) + IMAGE_QUALITY_REASON_FIELDS


class ImageQualityLabel(Base):
    """A labeler's per-image quality judgement on a single crop — separate from the
    per-piece color / part / reject labels, because it's about whether THIS crop is
    usable, not what the piece is.

    Two independent things: a `high_quality` star (a clean, good example) and a set
    of "not good enough for classification" reason flags. They're plain boolean
    columns on purpose — the point is to later filter e.g. every motion-blurred
    crop to build training data for an image-quality model, which is a column
    query, not a scan over a JSON blob.

    Recorded per (image, labeler) so several people can judge the same crop. Covers
    TWO different crop entities via `crop_kind`, since they live in different tables
    with different natural keys (no FK to either, mirroring PieceCropLinkMember):
    - 'piece_image'  → machine_piece_images, keyed (machine_id, piece_uuid, seq)
    - 'channel_crop' → machine_channel_crops, keyed (machine_id, crop_local_id)
    The key columns for the other kind stay NULL; a partial unique index per kind
    enforces one row per (image, labeler).
    """

    __tablename__ = "image_quality_labels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    labeler_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    crop_kind = Column(String, nullable=False)
    # Set for crop_kind='piece_image'; NULL for channel_crop.
    piece_uuid = Column(String, nullable=True)
    seq = Column(Integer, nullable=True)
    # Set for crop_kind='channel_crop'; NULL for piece_image.
    crop_local_id = Column(BigInteger, nullable=True)
    high_quality = Column(Boolean, nullable=False, default=False)
    low_resolution = Column(Boolean, nullable=False, default=False)
    motion_blur = Column(Boolean, nullable=False, default=False)
    not_contained = Column(Boolean, nullable=False, default=False)
    no_piece_in_frame = Column(Boolean, nullable=False, default=False)
    other_bad = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        Index(
            "uq_image_quality_labels_piece_image",
            "machine_id",
            "piece_uuid",
            "seq",
            "labeler_id",
            unique=True,
            postgresql_where=text("crop_kind = 'piece_image'"),
            sqlite_where=text("crop_kind = 'piece_image'"),
        ),
        Index(
            "uq_image_quality_labels_channel_crop",
            "machine_id",
            "crop_local_id",
            "labeler_id",
            unique=True,
            postgresql_where=text("crop_kind = 'channel_crop'"),
            sqlite_where=text("crop_kind = 'channel_crop'"),
        ),
        Index("ix_image_quality_labels_machine_piece", "machine_id", "piece_uuid"),
        Index("ix_image_quality_labels_machine_crop", "machine_id", "crop_local_id"),
        Index("ix_image_quality_labels_labeler_id", "labeler_id"),
    )
