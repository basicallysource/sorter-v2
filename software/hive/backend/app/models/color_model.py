import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class ColorModel(Base):
    """Registry of color-classifier models available to serve piece-color
    predictions. Rows are reconciled from a dir scan of COLOR_MODEL_DIR — one row
    per ``.onnx`` file found there — so the DB holds the metadata (display name,
    class count, input size, sha) while the model bytes live on disk and are
    uploaded out of band. At most one row has ``is_active`` true; that model's
    prediction is shown alongside the pixel-average suggestion in the labeling
    view.

    ``sha256`` lets a scan notice a file was replaced in place (same name, new
    bytes) and refresh the cached session. ``meta`` keeps the full embedded
    metadata block for reference/debugging.
    """

    __tablename__ = "color_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    kind = Column(String, nullable=False, default="color_classifier")
    sha256 = Column(String(64), nullable=False)
    class_count = Column(Integer, nullable=False, default=0)
    input_size = Column(Integer, nullable=False, default=0)
    file_size = Column(BigInteger, nullable=False, default=0)
    meta = Column(JSON_VARIANT, nullable=True)
    is_active = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
