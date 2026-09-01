import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class LinkModel(Base):
    """Registry of piece_link matcher models available to score which upstream
    C2/C3 crops are the same physical piece as a classified piece — the learned
    replacement for the time/angle heuristic (``channel_crop_lookup_params``).

    Unlike a color model (one ``.onnx``), each link model is a PAIR of ONNX
    graphs — a shared ``CropEncoder`` and a ``LinkHead`` — exported side by side
    and grouped by their baked ``hive.name``. Rows are reconciled from a dir scan
    of ``LINK_MODEL_DIR``: one row per name whose two files both parse as a
    ``piece_link_matcher``. The DB holds the metadata (name, dims, input size,
    combined sha) while the bytes live on disk and are uploaded out of band.

    At most one row has ``is_active`` true; that model's per-candidate score
    supersedes the heuristic's pre-selection in the labeling view. ``sha256`` is
    over both files (sorted) so a scan notices either being replaced and refreshes
    the cached sessions. ``meta`` keeps the full embedded metadata block.
    """

    __tablename__ = "link_models"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=True)
    kind = Column(String, nullable=False, default="piece_link_matcher")
    encoder_filename = Column(String, nullable=False)
    head_filename = Column(String, nullable=False)
    sha256 = Column(String(64), nullable=False)
    input_size = Column(Integer, nullable=False, default=0)
    embed_dim = Column(Integer, nullable=False, default=0)
    meta_dim = Column(Integer, nullable=False, default=0)
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
