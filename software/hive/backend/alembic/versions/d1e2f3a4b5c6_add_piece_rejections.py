"""add piece rejections

Revision ID: d1e2f3a4b5c6
Revises: f0a1b2c3d4e5
Create Date: 2026-07-13 20:00:00.000000

A labeler can reject a piece's bbox sample as unusable, with one or more reason
codes (no_piece / multiple_pieces). One rejection per (machine, piece, labeler).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "piece_rejections",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("labeler_id", sa.UUID(), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["labeler_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "piece_uuid", "labeler_id", name="uq_piece_rejections_piece_labeler"),
    )
    op.create_index("ix_piece_rejections_machine_piece", "piece_rejections", ["machine_id", "piece_uuid"], unique=False)
    op.create_index("ix_piece_rejections_labeler_id", "piece_rejections", ["labeler_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_piece_rejections_labeler_id", table_name="piece_rejections")
    op.drop_index("ix_piece_rejections_machine_piece", table_name="piece_rejections")
    op.drop_table("piece_rejections")
