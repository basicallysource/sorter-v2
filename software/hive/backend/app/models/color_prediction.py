import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


class ColorPrediction(Base):
    """One served color prediction, logged with the crops the machine sent.

    This is the training-data side of the hosted color service: sorters that
    select the Hive color provider send crops to the color-predict endpoint,
    and every call is recorded here with its images so the color model can be
    retrained on real in-the-wild input. It is deliberately separate from the
    sample-upload and piece-sync paths — those are the owner's data, surfaced in
    their UI. These rows are admin-only and are never exposed to the device's
    operator or to regular users.

    Keys on device_id (the hosted-services identity), not machine_id — a later
    merge with account data goes through devices.machine_id.

    Model provenance is denormalized on purpose: color_predictor.reconcile()
    deletes color_models rows whose files disappear from disk, so the FK is
    ondelete=SET NULL and the durable record of "which rev produced this" is
    color_model_sha256 (a file replaced in place keeps its id/filename but gets
    a new sha, so the sha is the real revision identity).
    """

    __tablename__ = "color_predictions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)

    color_model_id = Column(UUID(as_uuid=True), ForeignKey("color_models.id", ondelete="SET NULL"), nullable=True)
    color_model_name = Column(String, nullable=True)
    color_model_filename = Column(String, nullable=True)
    color_model_sha256 = Column(String(64), nullable=True)
    multiview = Column(Boolean, nullable=True)

    method = Column(String, nullable=True)
    predicted_color_id = Column(Integer, nullable=True)
    predicted_color_name = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    # Full top-3 list as returned to the machine, so close calls stay reviewable.
    top = Column(JSON_VARIANT, nullable=True)

    # Storage keys under devices/{device_id}/color_predict/{prediction_id}/, and
    # the camera channel (2/3/4) each image came from, same order.
    image_keys = Column(JSON_VARIANT, nullable=True)
    channels = Column(JSON_VARIANT, nullable=True)
    image_count = Column(Integer, nullable=False, default=0)
    # Images the model actually decoded and scored, which can be fewer than
    # image_count when a crop fails to decode.
    scored_count = Column(Integer, nullable=True)

    # Loose device-supplied context (sorter version, piece uuid, providers in
    # use). Free-form so the sorter can enrich it without a migration.
    client_info = Column(JSON_VARIANT, nullable=True)
    request_ip = Column(String, nullable=True)
    inference_ms = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_color_predictions_device_created", "device_id", "created_at"),
        Index("ix_color_predictions_created_at", "created_at"),
        Index("ix_color_predictions_model_sha", "color_model_sha256"),
    )

