"""add piece color labels

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-13 12:20:00.000000

Human ground-truth BrickLink color for a synced machine piece. Distinct from
sample_reviews: here a labeler corrects the machine's Brickognize color
prediction by picking the true color from the crop. One label per
(machine, piece, labeler).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "piece_color_labels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("labeler_id", sa.UUID(), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["labeler_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "piece_uuid", "labeler_id", name="uq_piece_color_labels_piece_labeler"),
    )
    op.create_index("ix_piece_color_labels_machine_piece", "piece_color_labels", ["machine_id", "piece_uuid"])
    op.create_index("ix_piece_color_labels_labeler_id", "piece_color_labels", ["labeler_id"])


def downgrade() -> None:
    op.drop_index("ix_piece_color_labels_labeler_id", table_name="piece_color_labels")
    op.drop_index("ix_piece_color_labels_machine_piece", table_name="piece_color_labels")
    op.drop_table("piece_color_labels")
