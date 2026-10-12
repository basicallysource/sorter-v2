"""The swatch finder's palette call: is the colour reference palette in view

Revision ID: c548fb8d227c
Revises: 01ac20eed2e4

sample_swatch_runs.palette_present / palette_swatches: the frame's call (a
chain of at least four neighbouring swatches in at least four colours) and how
many swatches make up the palette. sample_swatches.in_palette: whether a swatch
is one of them. All three are null on runs made before the finder made the
call; a backfill reads those samples again.

ix_sample_swatch_runs_model_palette (model, call, sample) is what the samples
filter reads; it replaces the index on the model alone, which it leads with.
"""

import sqlalchemy as sa
from alembic import op

revision = "c548fb8d227c"
down_revision = "01ac20eed2e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sample_swatch_runs", sa.Column("palette_present", sa.Boolean(), nullable=True))
    op.add_column("sample_swatch_runs", sa.Column("palette_swatches", sa.Integer(), nullable=True))
    op.add_column("sample_swatches", sa.Column("in_palette", sa.Boolean(), nullable=True))
    op.create_index(
        "ix_sample_swatch_runs_model_palette",
        "sample_swatch_runs",
        ["model_sha256", "palette_present", "sample_id"],
    )
    op.drop_index("ix_sample_swatch_runs_model_sha256", table_name="sample_swatch_runs")


def downgrade() -> None:
    op.create_index("ix_sample_swatch_runs_model_sha256", "sample_swatch_runs", ["model_sha256"])
    op.drop_index("ix_sample_swatch_runs_model_palette", table_name="sample_swatch_runs")
    op.drop_column("sample_swatches", "in_palette")
    op.drop_column("sample_swatch_runs", "palette_swatches")
    op.drop_column("sample_swatch_runs", "palette_present")
