"""add piece_link matcher model registry (and merge divergent heads)

Revision ID: a7b8c9d0e1f2
Revises: b7d1e2f3a4c5, c5d6e7f8a9b0
Create Date: 2026-07-14 18:30:00.000000

Registry of uploaded piece_link matcher models. Each model is a pair of ONNX
graphs (encoder + head) grouped by their baked ``hive.name``; rows are
reconciled from a dir scan of LINK_MODEL_DIR. At most one is active and scores
"same physical piece" upstream crops in the labeling view in place of the
time/angle heuristic.

This also merges the two Alembic heads that had accumulated on this branch
(b7d1e2f3a4c5 / c5d6e7f8a9b0) back into a single head.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = ("b7d1e2f3a4c5", "c5d6e7f8a9b0")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "link_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("encoder_filename", sa.String(), nullable=False),
        sa.Column("head_filename", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("input_size", sa.Integer(), nullable=False),
        sa.Column("embed_dim", sa.Integer(), nullable=False),
        sa.Column("meta_dim", sa.Integer(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_link_models_name"),
    )
    op.create_index("ix_link_models_is_active", "link_models", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_link_models_is_active", table_name="link_models")
    op.drop_table("link_models")
