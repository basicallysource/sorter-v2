"""add archived_at to samples

Revision ID: c7d8e9f0a1b2
Revises: b6c7d8e9f0a1
Create Date: 2026-05-25

Admin soft-delete for samples. Mirrors machines.archived_at: a non-null
timestamp hides the row from default listings, stats, training pulls and
review queues, while leaving the underlying row + files intact so an
admin can un-archive without data loss.

Partial index speeds up the common 'show me what's archived' admin view
without bloating the all-samples index on the hot path.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "samples",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial index — most rows are NOT archived, so a normal index would
    # be enormous and rarely used. The 'archived only' query (admin view)
    # is the hot path we actually care about.
    op.create_index(
        "ix_samples_archived_at",
        "samples",
        ["archived_at"],
        postgresql_where=sa.text("archived_at IS NOT NULL"),
        sqlite_where=sa.text("archived_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_samples_archived_at", table_name="samples")
    op.drop_column("samples", "archived_at")
