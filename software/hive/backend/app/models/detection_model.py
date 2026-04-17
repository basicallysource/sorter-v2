import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base, JSON_VARIANT


class DetectionModel(Base):
    __tablename__ = "detection_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    slug = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    model_family = Column(String, nullable=False)
    scopes = Column(JSON_VARIANT, nullable=True)
    training_metadata = Column(JSON_VARIANT, nullable=True)
    is_public = Column(Boolean, nullable=False, default=True)
    published_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    owner = relationship("User")
    variants = relationship(
        "DetectionModelVariant",
        back_populates="model",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("slug", "version", name="uq_detection_models_slug_version"),
        Index("ix_detection_models_slug", "slug"),
        Index("ix_detection_models_model_family", "model_family"),
        Index("ix_detection_models_is_public", "is_public"),
    )


class DetectionModelVariant(Base):
    __tablename__ = "detection_model_variants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("detection_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    runtime = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    file_size = Column(BigInteger, nullable=False)
    sha256 = Column(String(64), nullable=False)
    format_meta = Column(JSON_VARIANT, nullable=True)
    uploaded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    model = relationship("DetectionModel", back_populates="variants")

    __table_args__ = (
        CheckConstraint(
            "runtime IN ('onnx', 'ncnn', 'hailo', 'pytorch')",
            name="ck_detection_model_variants_runtime",
        ),
        UniqueConstraint("model_id", "runtime", name="uq_detection_model_variants_model_runtime"),
        Index("ix_detection_model_variants_model_id", "model_id"),
    )
