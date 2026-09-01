"""add color models registry (and merge divergent heads)

Revision ID: e7c1a2b3d4f5
Revises: a9c4d2b3e5f7, b8c9d0e1f2a3, d2e3f4a5b6c7
Create Date: 2026-07-13 22:30:00.000000

Registry of uploaded color-classifier models. Rows are reconciled from a dir
scan of COLOR_MODEL_DIR; one row per `.onnx`. At most one is active and serves
piece-color predictions.

This also merges the three Alembic heads that had accumulated from parallel PRs
(a9c4d2b3e5f7 / b8c9d0e1f2a3 / d2e3f4a5b6c7) back into a single head, so
`alembic upgrade head` is unambiguous again.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7c1a2b3d4f5"
down_revision: Union[str, Sequence[str], None] = ("a9c4d2b3e5f7", "b8c9d0e1f2a3", "d2e3f4a5b6c7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "color_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("class_count", sa.Integer(), nullable=False),
        sa.Column("input_size", sa.Integer(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("filename", name="uq_color_models_filename"),
    )
    op.create_index("ix_color_models_is_active", "color_models", ["is_active"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_color_models_is_active", table_name="color_models")
    op.drop_table("color_models")
