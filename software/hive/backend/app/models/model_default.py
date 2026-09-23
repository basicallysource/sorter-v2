from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.models import Base


class ModelDefault(Base):
    """The model a fresh install downloads for one (purpose, runtime).

    A sorter that is not linked to an account has no credential, so it cannot
    browse the catalog. It asks by compatibility instead ("I run rknn: which
    detection model?") and an admin decides the answer here, so which model a
    new install gets is never baked into the install itself.

    Served anonymously, so only a public model can be one; a default whose
    model has since gone private is kept but not served. Rows cascade away
    with the model or variant they point at.
    """

    __tablename__ = "model_defaults"

    purpose = Column(String, primary_key=True)
    runtime = Column(String, primary_key=True)
    model_id = Column(
        UUID(as_uuid=True),
        ForeignKey("detection_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    variant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("detection_model_variants.id", ondelete="CASCADE"),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    updated_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    model = relationship("DetectionModel", back_populates="defaults")
    variant = relationship("DetectionModelVariant")
