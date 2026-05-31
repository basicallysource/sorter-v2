"""add exposure stats to samples

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-05-25

Per-sample histogram summary so the UI can filter / flag
over- and under-exposed images. Five floats; the only one we
actually index is luminance_mean since that's what the filter
buckets bucket on. The percentile + clipped-ratio columns are
read-only diagnostics for now.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("samples", sa.Column("luminance_mean", sa.Float(), nullable=True))
    op.add_column("samples", sa.Column("luminance_p05", sa.Float(), nullable=True))
    op.add_column("samples", sa.Column("luminance_p95", sa.Float(), nullable=True))
    op.add_column("samples", sa.Column("clipped_low_ratio", sa.Float(), nullable=True))
    op.add_column("samples", sa.Column("clipped_high_ratio", sa.Float(), nullable=True))
    op.create_index(
        "ix_samples_luminance_mean",
        "samples",
        ["luminance_mean"],
        postgresql_where=sa.text("luminance_mean IS NOT NULL"),
        sqlite_where=sa.text("luminance_mean IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_samples_luminance_mean", table_name="samples")
    op.drop_column("samples", "clipped_high_ratio")
    op.drop_column("samples", "clipped_low_ratio")
    op.drop_column("samples", "luminance_p95")
    op.drop_column("samples", "luminance_p05")
    op.drop_column("samples", "luminance_mean")
