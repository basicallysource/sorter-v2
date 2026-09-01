"""add piece crop links

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-13 13:00:00.000000

Human "same physical piece across channels" labels — training data for a future
cross-channel tracking model. A labeler is shown a classified piece plus the
time/angle heuristic's ranked candidate C2/C3 crops (machine_channel_crops) and
marks which are the same piece. piece_crop_links is one such decision per
(machine, piece, labeler); piece_crop_link_members stores every presented crop
with the verdict (is_same) and whether the heuristic pre-selected it
(was_predicted), so positives, hard negatives, and heuristic accuracy are all
recoverable.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "piece_crop_links",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("labeler_id", sa.UUID(), nullable=False),
        sa.Column("arrival_ts", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["labeler_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "piece_uuid", "labeler_id", name="uq_piece_crop_links_piece_labeler"),
    )
    op.create_index("ix_piece_crop_links_machine_piece", "piece_crop_links", ["machine_id", "piece_uuid"], unique=False)
    op.create_index("ix_piece_crop_links_labeler_id", "piece_crop_links", ["labeler_id"], unique=False)

    op.create_table(
        "piece_crop_link_members",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("link_id", sa.UUID(), nullable=False),
        sa.Column("crop_local_id", sa.BigInteger(), nullable=False),
        sa.Column("is_same", sa.Boolean(), nullable=False),
        sa.Column("was_predicted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["link_id"], ["piece_crop_links.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("link_id", "crop_local_id", name="uq_piece_crop_link_members_link_crop"),
    )
    op.create_index("ix_piece_crop_link_members_link_id", "piece_crop_link_members", ["link_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_piece_crop_link_members_link_id", table_name="piece_crop_link_members")
    op.drop_table("piece_crop_link_members")
    op.drop_index("ix_piece_crop_links_labeler_id", table_name="piece_crop_links")
    op.drop_index("ix_piece_crop_links_machine_piece", table_name="piece_crop_links")
    op.drop_table("piece_crop_links")
