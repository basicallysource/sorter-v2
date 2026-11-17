import uuid
from datetime import datetime, timezone

from sqlalchemy import DDL, BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint, event
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
        # The unique constraint's index is the (machine_id, local_id) index.
        # Migrations also add (machine_id, ts) and a BRIN on created_at.
        UniqueConstraint("machine_id", "local_id", name="uq_machine_channel_crops_machine_local"),
    )


class MachineChannelCropDelta(Base):
    """How many channel crops a machine gained (or lost) in one statement.

    Counting a machine's crops (tens of millions of rows) on every stats pass
    ran past the worker's statement limit. Instead triggers on
    machine_channel_crops append one row per statement that inserts or deletes
    crops, and the stats worker adds the rows to the machine's count and
    deletes them (services/machine_stats.py). A re-sent crop updates its row
    and adds nothing. No foreign key: deleting a machine deletes its crops,
    whose trigger writes a row for the machine that is going away.
    """

    __tablename__ = "machine_channel_crop_deltas"

    id = Column(BigInteger().with_variant(Integer(), "sqlite"), primary_key=True, autoincrement=True)
    machine_id = Column(UUID(as_uuid=True), nullable=False)
    n = Column(BigInteger, nullable=False)


# The migration creates these on Postgres; these create them wherever
# Base.metadata.create_all builds the tables (the tests).
PG_CROP_DELTA_FUNCTION = """
CREATE OR REPLACE FUNCTION machine_channel_crops_delta() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO machine_channel_crop_deltas (machine_id, n)
        SELECT machine_id, count(*) FROM new_rows GROUP BY machine_id;
    ELSE
        INSERT INTO machine_channel_crop_deltas (machine_id, n)
        SELECT machine_id, -count(*) FROM old_rows GROUP BY machine_id;
    END IF;
    RETURN NULL;
END
$$
"""
PG_CROP_DELTA_TRIGGERS = (
    "CREATE OR REPLACE TRIGGER machine_channel_crops_delta_insert AFTER INSERT ON machine_channel_crops "
    "REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_channel_crops_delta()",
    "CREATE OR REPLACE TRIGGER machine_channel_crops_delta_delete AFTER DELETE ON machine_channel_crops "
    "REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_channel_crops_delta()",
)
SQLITE_CROP_DELTA_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS machine_channel_crops_delta_insert AFTER INSERT ON machine_channel_crops BEGIN "
    "INSERT INTO machine_channel_crop_deltas (machine_id, n) VALUES (NEW.machine_id, 1); END",
    "CREATE TRIGGER IF NOT EXISTS machine_channel_crops_delta_delete AFTER DELETE ON machine_channel_crops BEGIN "
    "INSERT INTO machine_channel_crop_deltas (machine_id, n) VALUES (OLD.machine_id, -1); END",
)
for _statement in (PG_CROP_DELTA_FUNCTION, *PG_CROP_DELTA_TRIGGERS):
    event.listen(Base.metadata, "after_create", DDL(_statement).execute_if(dialect="postgresql"))
for _statement in SQLITE_CROP_DELTA_TRIGGERS:
    event.listen(Base.metadata, "after_create", DDL(_statement).execute_if(dialect="sqlite"))
