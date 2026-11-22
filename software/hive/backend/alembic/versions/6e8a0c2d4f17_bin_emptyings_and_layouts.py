"""Bin emptyings and the layouts a machine ran, and pieces by bin

Revision ID: 6e8a0c2d4f17
Revises: 4d6f8b0c2e35
Create Date: 2026-11-21

- machine_bin_emptyings: each emptying of each bin of a machine (a clear found
  the bin holding pieces), synced from it (data type bin_emptyings).
- machine_bin_layouts: every layout a machine ran (its bins, what each was
  assigned and what the profile called it), synced from it (data type
  bin_layouts), indexed by when each changed (the layout running at a moment).
- ix_machine_pieces_bin_recorded_at: a bin's pieces in the order they went in,
  so what went into a bin between two of its emptyings is one range of an
  index (the inventory API). Built CONCURRENTLY outside a transaction, so
  machines keep syncing records while it builds; a build that failed half way
  leaves an invalid index, which is dropped and built again.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "6e8a0c2d4f17"
down_revision = "4d6f8b0c2e35"
branch_labels = None
depends_on = None

_UUID = postgresql.UUID(as_uuid=True)
_BIN_INDEX = "ix_machine_pieces_bin_recorded_at"
_BIN_INDEX_DEFINITION = "(machine_id, bin_x, bin_y, bin_z, recorded_at) WHERE bin_x IS NOT NULL"


def upgrade() -> None:
    op.create_table(
        "machine_bin_emptyings",
        sa.Column("machine_id", _UUID, sa.ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("local_id", sa.BigInteger(), primary_key=True),
        sa.Column("snapshot_id", sa.String(), nullable=True),
        sa.Column("layer", sa.Integer(), nullable=False),
        sa.Column("section", sa.Integer(), nullable=False),
        sa.Column("bin", sa.Integer(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=True),
        sa.Column("emptied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("piece_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category_ids", postgresql.JSONB(), nullable=True),
        sa.Column("scope", sa.String(), nullable=True),
        sa.Column("profile_id", sa.String(), nullable=True),
        sa.Column("profile_name", sa.String(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_machine_bin_emptyings_bin",
        "machine_bin_emptyings",
        ["machine_id", "layer", "section", "bin", "emptied_at"],
    )
    op.create_table(
        "machine_bin_layouts",
        sa.Column("machine_id", _UUID, sa.ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("local_id", sa.BigInteger(), primary_key=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("layout", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_machine_bin_layouts_changed_at", "machine_bin_layouts", ["machine_id", "changed_at"])
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        invalid = bind.execute(
            text(
                "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = :name"
            ),
            {"name": _BIN_INDEX},
        ).scalar()
        if invalid:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_BIN_INDEX}")
        op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_BIN_INDEX} ON machine_pieces {_BIN_INDEX_DEFINITION}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_BIN_INDEX}")
    op.drop_index("ix_machine_bin_layouts_changed_at", table_name="machine_bin_layouts")
    op.drop_table("machine_bin_layouts")
    op.drop_index("ix_machine_bin_emptyings_bin", table_name="machine_bin_emptyings")
    op.drop_table("machine_bin_emptyings")
