import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class Sample(Base):
    __tablename__ = "samples"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    upload_session_id = Column(UUID(as_uuid=True), ForeignKey("upload_sessions.id", ondelete="CASCADE"), nullable=False)
    local_sample_id = Column(String, nullable=False)
    source_role = Column(String, nullable=True)
    capture_reason = Column(String, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    image_path = Column(String, nullable=False)
    full_frame_path = Column(String, nullable=True)
    overlay_path = Column(String, nullable=True)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    detection_algorithm = Column(String, nullable=True)
    detection_bboxes = Column(JSON_VARIANT, nullable=True)
    detection_count = Column(Integer, nullable=True)
    detection_score = Column(Float, nullable=True)
    sample_payload = Column(JSON_VARIANT, nullable=True)
    extra_metadata = Column(JSON_VARIANT, nullable=True)
    review_status = Column(String, nullable=False, default="unreviewed")
    review_count = Column(Integer, nullable=False, default=0)
    accepted_count = Column(Integer, nullable=False, default=0)
    rejected_count = Column(Integer, nullable=False, default=0)
    uploaded_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    # Admin soft-delete. Non-null means hidden from default listings + review
    # queue + training pulls. Files + sample_payload stay intact so an admin
    # can un-archive without data loss.
    archived_at = Column(DateTime(timezone=True), nullable=True)
    # 8×8 pHash for "find similar". Signed BIGINT — Hamming distance via
    # bit_count(phash # :target) in postgres. Null while waiting for the
    # backfill to run or for un-decodable images.
    phash = Column(BigInteger, nullable=True)
    # Histogram summary for exposure-quality filtering. Populated at upload
    # (and via the backfill script for older rows). luminance_mean is the
    # primary signal the filter buckets on; the rest are diagnostics +
    # heuristics for partial clipping.
    luminance_mean = Column(Float, nullable=True)
    luminance_p05 = Column(Float, nullable=True)
    luminance_p95 = Column(Float, nullable=True)
    clipped_low_ratio = Column(Float, nullable=True)
    clipped_high_ratio = Column(Float, nullable=True)

    machine = relationship("Machine", back_populates="samples")
    upload_session = relationship("UploadSession", back_populates="samples")
    reviews = relationship("SampleReview", back_populates="sample", cascade="all, delete-orphan")
    channel_geometry = relationship(
        "SampleChannelGeometry",
        back_populates="sample",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('unreviewed', 'in_review', 'accepted', 'rejected', 'conflict')",
            name="ck_samples_review_status",
        ),
        UniqueConstraint("upload_session_id", "local_sample_id", name="uq_samples_session_local"),
        Index("ix_samples_review_status", "review_status"),
        Index("ix_samples_machine_id", "machine_id"),
        Index("ix_samples_upload_session_id", "upload_session_id"),
        Index("ix_samples_source_role", "source_role"),
    )


# The samples list walks one of these newest first (review_queue.sample_page):
# all samples, the archived ones, the teacher-checked ones (the list's default
# view), and per filter that narrows the list, with a teacher-checked twin each.
# The predicates are written as the queries write them, so the planner matches
# them. Descending columns, so they are declared outside the class.
_ACTIVE = "archived_at IS NULL"
_TEACHER = "archived_at IS NULL AND (extra_metadata -> 'teacher_rerun') IS NOT NULL"
_NEWEST = (Sample.uploaded_at.desc(), Sample.id.desc())
Index("ix_samples_uploaded_at_id", *_NEWEST)
Index("ix_samples_archived_uploaded_at", *_NEWEST, postgresql_where=text("archived_at IS NOT NULL"))
Index("ix_samples_teacher_uploaded_at", *_NEWEST, postgresql_where=text(_TEACHER))
for _name, _column in (("machine", Sample.machine_id), ("role", Sample.source_role), ("reason", Sample.capture_reason)):
    Index(f"ix_samples_{_name}_uploaded_at", _column, *_NEWEST, postgresql_where=text(_ACTIVE))
    Index(f"ix_samples_{_name}_teacher_uploaded_at", _column, *_NEWEST, postgresql_where=text(_TEACHER))
# Similar samples compare one hash with every active sample's: from this index alone.
Index(
    "ix_samples_phash_active",
    Sample.phash,
    postgresql_include=["id", "machine_id"],
    postgresql_where=text("phash IS NOT NULL AND archived_at IS NULL"),
)
Index(
    "ix_samples_reviewed_uploaded_at",
    Sample.review_status,
    *_NEWEST,
    postgresql_where=text(f"{_ACTIVE} AND review_status <> 'unreviewed'"),
)
