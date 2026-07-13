import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models import Base


class MachineChannelCrop(Base):
    """An UNLABELED bbox crop of a piece seen on an upstream feeder channel
    (C2/C3). Unlike MachinePieceImage these are not tied to a classified piece —
    we don't yet know which piece each crop is. They carry the metadata a cheap
    time/angle heuristic uses to later guess "possibly the same piece": the
    channel, frame timestamp, the COM's signed distance to the exit zone in
    output degrees, its zone, and the advisory per-pass ByteTrack id.
    """

    __tablename__ = "machine_channel_crops"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    machine_id = Column(UUID(as_uuid=True), ForeignKey("machines.id", ondelete="CASCADE"), nullable=False)
    # The machine's sqlite autoincrement crop id — drives the per-target sync
    # watermark and is the natural key for a (machine, crop) row.
    local_id = Column(BigInteger, nullable=False)
    channel = Column(Integer, nullable=True)
    ts = Column(DateTime(timezone=True), nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    track_id = Column(BigInteger, nullable=True)
    com_forward_to_exit_deg = Column(Float, nullable=True)
    com_section = Column(Integer, nullable=True)
    zone_code = Column(Integer, nullable=True)
    sharpness = Column(Float, nullable=True)
    bbox_x1 = Column(Integer, nullable=True)
    bbox_y1 = Column(Integer, nullable=True)
    bbox_x2 = Column(Integer, nullable=True)
    bbox_y2 = Column(Integer, nullable=True)
    bytes = Column(Integer, nullable=True)
    # Object-storage key. NULL when the crop was evicted from the machine's local
    # 512 MB store before it could be synced — the row still rides up so counts
    # stay complete.
    image_key = Column(String, nullable=True)
    evicted_locally = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("machine_id", "local_id", name="uq_machine_channel_crops_machine_local"),
        Index("ix_machine_channel_crops_machine_local_id", "machine_id", "local_id"),
        Index("ix_machine_channel_crops_machine_channel_ts", "machine_id", "channel", "ts"),
    )
