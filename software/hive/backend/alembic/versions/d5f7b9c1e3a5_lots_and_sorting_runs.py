"""Machines' lots and sorting runs; an index for later colour answers

Revision ID: d5f7b9c1e3a5
Revises: c4e6a8b0d2f1
Create Date: 2026-10-15

- machine_lots and machine_sorting_runs: a machine's lots and sorting runs as it
  keeps them, synced whole (data type sorting_runs), so a reader can tell which
  of a machine's pieces make up a lot.
- ix_machine_piece_predictions_later_colors: each piece's top colour from a
  later run of a model (not the live classification), which the records API
  reads for a page of pieces at a time.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "d5f7b9c1e3a5"
down_revision = "c4e6a8b0d2f1"
branch_labels = None
depends_on = None

LATER_COLORS = "ix_machine_piece_predictions_later_colors"
LATER_COLORS_DEFINITION = "(machine_id, piece_uuid) WHERE source <> 'live' AND kind = 'color' AND rank = 0"


def _create_concurrently(table: str, name: str, definition: str) -> None:
    """CREATE INDEX CONCURRENTLY IF NOT EXISTS, after dropping an invalid one
    a failed build left behind. Call inside an autocommit block."""
    invalid = op.get_bind().execute(
        text(
            "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name"
        ),
        {"name": name},
    ).scalar()
    if invalid:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} {definition}")


def upgrade() -> None:
    op.create_table(
        "machine_lots",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("lot_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "machine_sorting_runs",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("lot_id", sa.String(), nullable=True),
        sa.Column("adds_to_lot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    with op.get_context().autocommit_block():
        _create_concurrently("machine_piece_predictions", LATER_COLORS, LATER_COLORS_DEFINITION)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {LATER_COLORS}")
    op.drop_table("machine_sorting_runs")
    op.drop_table("machine_lots")
