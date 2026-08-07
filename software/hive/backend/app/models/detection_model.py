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

PURPOSE_DETECTION = "detection"
PURPOSE_PIECE_LINK = "piece_link"
MODEL_PURPOSES = (PURPOSE_DETECTION, PURPOSE_PIECE_LINK)


class DetectionModel(Base):
    __tablename__ = "detection_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    slug = Column(String, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    # What the model is FOR, as opposed to model_family (how it's built). The
    # publish/store/download/install machinery is identical across purposes; only
    # the consumer on the machine differs, so they share one table.
    purpose = Column(String, nullable=False, default=PURPOSE_DETECTION, server_default=PURPOSE_DETECTION)
    model_family = Column(String, nullable=False)
    scopes = Column(JSON_VARIANT, nullable=True)
    training_metadata = Column(JSON_VARIANT, nullable=True)
    is_public = Column(Boolean, nullable=False, default=True)
    # Experimental models are first-class but hidden from the default Browse on
    # both Hive and the sorters, so operators don't install a test model by
    # accident. Opt back in with ?include_experimental=true.
    experimental = Column(Boolean, nullable=False, default=False, server_default="false")
    # Human-friendly handle drawn from a curated LEGO-color word list — like Ubuntu's
    # codenames. Picked by :func:`app.services.codenames.next_codename` alphabetically
    # at publish time; persistent so people can refer to "Bronze beats Aqua by 1.5 %"
    # instead of slug+version. Unique across all rows (incl. archived/private).
    codename = Column(String, nullable=True)
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
        Index("ix_detection_models_codename", "codename", unique=True),
        Index("ix_detection_models_model_family", "model_family"),
        Index("ix_detection_models_is_public", "is_public"),
        Index("ix_detection_models_experimental", "experimental"),
        Index("ix_detection_models_purpose", "purpose"),
        CheckConstraint(
            "purpose IN ('detection', 'piece_link')",
            name="ck_detection_models_purpose",
        ),
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
            "runtime IN ('onnx', 'ncnn', 'hailo', 'pytorch', 'rknn')",
            name="ck_detection_model_variants_runtime",
        ),
        UniqueConstraint("model_id", "runtime", name="uq_detection_model_variants_model_runtime"),
        Index("ix_detection_model_variants_model_id", "model_id"),
    )
