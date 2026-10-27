import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class SwatchModel(Base):
    """Registry of colour-reference palette finders: small ONNX networks that
    find each tile of a machine's colour palette in a raw classification-camera
    frame and read its colour (``app.services.swatch_finder``).

    Rows are reconciled from a dir scan of ``SWATCH_MODEL_DIR``, one per
    ``.onnx`` whose metadata says ``hive.kind`` = ``swatch_finder``, like the
    colour and link models: the DB holds the metadata, the bytes live on disk
    and are uploaded out of band. At most one row has ``is_active`` true; while
    one does, new classification-camera samples get a ``swatch_find`` job, and
    its readings are stored per sample (``sample_swatch_runs``).
    """

    __tablename__ = "swatch_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    kind = Column(String, nullable=False, default="swatch_finder")
    sha256 = Column(String(64), nullable=False)
    # Colours it can name (not counting "none").
    colour_count = Column(Integer, nullable=False, default=0)
    # The long side a frame is shrunk to for the network.
    net_long_side = Column(Integer, nullable=False, default=0)
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
