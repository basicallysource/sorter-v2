"""add machine channel crops

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-13 12:00:00.000000

Machine -> Hive sync of UNLABELED upstream-channel (C2/C3) bbox crops. Each row
is one crop of a piece seen on a feeder channel, tagged with the metadata a
cheap time/angle "possibly the same piece" heuristic reads: channel, frame ts,
the COM's signed distance to the exit zone (output degrees), zone code, and the
advisory per-pass ByteTrack id. Synced via the same watermark table
(machine_sync_state, data_type "channel_crops"). Crops evicted from the
machine's 512 MB local store before syncing ride up metadata-only (image_key
NULL, evicted_locally true).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_channel_crops",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("local_id", sa.BigInteger(), nullable=False),
        sa.Column("channel", sa.Integer(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("track_id", sa.BigInteger(), nullable=True),
        sa.Column("com_forward_to_exit_deg", sa.Float(), nullable=True),
        sa.Column("com_section", sa.Integer(), nullable=True),
        sa.Column("zone_code", sa.Integer(), nullable=True),
        sa.Column("sharpness", sa.Float(), nullable=True),
        sa.Column("bbox_x1", sa.Integer(), nullable=True),
        sa.Column("bbox_y1", sa.Integer(), nullable=True),
        sa.Column("bbox_x2", sa.Integer(), nullable=True),
        sa.Column("bbox_y2", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("image_key", sa.String(), nullable=True),
        sa.Column("evicted_locally", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "local_id", name="uq_machine_channel_crops_machine_local"),
    )
    op.create_index("ix_machine_channel_crops_machine_local_id", "machine_channel_crops", ["machine_id", "local_id"], unique=False)
    op.create_index("ix_machine_channel_crops_machine_channel_ts", "machine_channel_crops", ["machine_id", "channel", "ts"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_machine_channel_crops_machine_channel_ts", table_name="machine_channel_crops")
    op.drop_index("ix_machine_channel_crops_machine_local_id", table_name="machine_channel_crops")
    op.drop_table("machine_channel_crops")
