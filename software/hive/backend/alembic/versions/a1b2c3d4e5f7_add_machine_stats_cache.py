"""add machine stats cache

Revision ID: a1b2c3d4e5f7
Revises: f1a2b3c4d5e6
Create Date: 2026-07-11 12:00:00.000000

Per-machine pre-computed dashboard metrics (pieces, PPM, on-time, sample
capture counts). A background worker refreshes one row per machine hourly so
the /machines/{id}/overview and /admin/machines/stats endpoints serve cached
rows instead of re-aggregating machine_pieces/samples on every request.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f7"
down_revision: Union[str, None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_stats_cache",
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("pieces_seen", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("distributed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("classified", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("unique_parts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_colors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overall_ppm", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ontime_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("accepted_samples", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_capture", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_capture", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_sessions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parts_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parts_needed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_id"),
    )


def downgrade() -> None:
    op.drop_table("machine_stats_cache")
