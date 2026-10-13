"""Every colour model's answer for a piece

Revision ID: a7c9e1b3d5f8
Revises: f6a8c0e2b4d7
Create Date: 2026-10-13

piece_model_colors: one row per (machine, piece, colour model sha256) with the
model's top colour, its confidence, its top three and the crops it read, kept
by the color_model_run job (services/color_model_runs.py). Two indexes make
"this model's answers by confidence" a walk of an index, for every machine
and for one: the piece grid's least_sure / surest sorts. A new table, so the
indexes are built with it.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7c9e1b3d5f8"
down_revision = "f6a8c0e2b4d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "piece_model_colors",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("piece_uuid", sa.String(), primary_key=True),
        sa.Column("model_sha256", sa.String(64), primary_key=True),
        sa.Column("model_name", sa.String(), nullable=False),
        sa.Column("color_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("top", postgresql.JSONB(), nullable=False),
        sa.Column("seqs", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["machine_id", "piece_uuid"],
            ["machine_pieces.machine_id", "machine_pieces.piece_uuid"],
            ondelete="CASCADE",
            name="fk_piece_model_colors_piece",
        ),
    )
    op.create_index(
        "ix_piece_model_colors_confidence",
        "piece_model_colors",
        ["model_sha256", "confidence", "machine_id", "piece_uuid"],
    )
    op.create_index(
        "ix_piece_model_colors_machine_confidence",
        "piece_model_colors",
        ["model_sha256", "machine_id", "confidence", "piece_uuid"],
    )


def downgrade() -> None:
    op.drop_index("ix_piece_model_colors_machine_confidence", table_name="piece_model_colors")
    op.drop_index("ix_piece_model_colors_confidence", table_name="piece_model_colors")
    op.drop_table("piece_model_colors")
