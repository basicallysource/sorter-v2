"""add machine piece sync

Revision ID: f1a2b3c4d5e6
Revises: c4d5e6f7a8b9
Create Date: 2026-07-08 12:00:00.000000

Machine -> Hive sync of "known objects": the per-machine piece_records history
and their captured crop images, plus a server-held watermark table so a machine
can reconcile months of backlog without redundant re-uploads. Images that were
already evicted from the machine's 500 MB local store ride up as metadata-only
rows (image_key NULL, evicted_locally true).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_pieces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("local_id", sa.BigInteger(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classification_status", sa.String(), nullable=True),
        sa.Column("part_id", sa.String(), nullable=True),
        sa.Column("part_name", sa.String(), nullable=True),
        sa.Column("color_id", sa.String(), nullable=True),
        sa.Column("color_name", sa.String(), nullable=True),
        sa.Column("category_id", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("bin_x", sa.Integer(), nullable=True),
        sa.Column("bin_y", sa.Integer(), nullable=True),
        sa.Column("bin_z", sa.Integer(), nullable=True),
        sa.Column("dead", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("brickognize_preview_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "piece_uuid", name="uq_machine_pieces_machine_piece"),
    )
    op.create_index("ix_machine_pieces_machine_local_id", "machine_pieces", ["machine_id", "local_id"], unique=False)
    op.create_index("ix_machine_pieces_machine_seen_at", "machine_pieces", ["machine_id", "seen_at"], unique=False)

    op.create_table(
        "machine_piece_images",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("local_id", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("channel", sa.Integer(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sharpness", sa.Float(), nullable=True),
        sa.Column("bytes", sa.Integer(), nullable=True),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("excluded_from_result", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("image_key", sa.String(), nullable=True),
        sa.Column("evicted_locally", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "piece_uuid", "seq", name="uq_machine_piece_images_machine_piece_seq"),
    )
    op.create_index("ix_machine_piece_images_machine_local_id", "machine_piece_images", ["machine_id", "local_id"], unique=False)
    op.create_index("ix_machine_piece_images_machine_piece", "machine_piece_images", ["machine_id", "piece_uuid"], unique=False)

    op.create_table(
        "machine_sync_state",
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("data_type", sa.String(), nullable=False),
        sa.Column("max_local_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_id", "data_type"),
    )


def downgrade() -> None:
    op.drop_table("machine_sync_state")
    op.drop_index("ix_machine_piece_images_machine_piece", table_name="machine_piece_images")
    op.drop_index("ix_machine_piece_images_machine_local_id", table_name="machine_piece_images")
    op.drop_table("machine_piece_images")
    op.drop_index("ix_machine_pieces_machine_seen_at", table_name="machine_pieces")
    op.drop_index("ix_machine_pieces_machine_local_id", table_name="machine_pieces")
    op.drop_table("machine_pieces")
