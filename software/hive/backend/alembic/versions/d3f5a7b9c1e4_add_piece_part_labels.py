"""add piece part labels

Revision ID: d3f5a7b9c1e4
Revises: c3a5b7d9e1f2
Create Date: 2026-07-19 19:10:00.000000

Human ground-truth part (mold) for a synced machine piece — the part sibling of
piece_color_labels. machine_pieces.part_correct could only say the Brickognize
identification was wrong, never what the piece actually is, and an unidentified
piece (part_id NULL) had nowhere to record a fill-in at all. One label per
(machine, piece, labeler), so several people can correct the same piece
independently and be aggregated later.

part_num is a Rebrickable part_num from the parts.db catalog — the same
namespace as machine_pieces.part_id. No FK: parts.db is a separate sqlite file.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3f5a7b9c1e4"
down_revision: Union[str, None] = "c3a5b7d9e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "piece_part_labels",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("labeler_id", sa.UUID(), nullable=False),
        sa.Column("part_num", sa.String(), nullable=True),
        sa.Column("cant_tell", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("predicted_part_num", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["labeler_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "piece_uuid", "labeler_id", name="uq_piece_part_labels_piece_labeler"),
    )
    # New rows get the default from the app-side model, like cant_tell on
    # piece_color_labels (b7d1e2f3a4c5).
    op.alter_column("piece_part_labels", "cant_tell", server_default=None)
    op.create_index("ix_piece_part_labels_machine_piece", "piece_part_labels", ["machine_id", "piece_uuid"])
    op.create_index("ix_piece_part_labels_labeler_id", "piece_part_labels", ["labeler_id"])
    op.create_index("ix_piece_part_labels_part_num", "piece_part_labels", ["part_num"])


def downgrade() -> None:
    op.drop_index("ix_piece_part_labels_part_num", table_name="piece_part_labels")
    op.drop_index("ix_piece_part_labels_labeler_id", table_name="piece_part_labels")
    op.drop_index("ix_piece_part_labels_machine_piece", table_name="piece_part_labels")
    op.drop_table("piece_part_labels")
