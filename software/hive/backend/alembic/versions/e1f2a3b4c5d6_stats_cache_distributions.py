"""machine_stats_cache: carry the whole distribution maps

The public /stats endpoint recomputed every aggregate over machine_pieces on
every request — about 18 sequential scans of a 240 MB table per call, at ten
calls a minute, which pinned prod's two vCPUs. The per-machine cache that the
admin fleet table already reads was most of the answer; it just did not carry
the distributions. With them, every analytics scope is a fold over cache rows
and nothing aggregates on the request path.

Backfilled empty. The stats worker fills it on its first pass, and the fold
treats a missing map as a machine with no pieces rather than as an error.

Revision ID: e1f2a3b4c5d6
Revises: d4f6a8b0c2e1
"""

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d4f6a8b0c2e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "machine_stats_cache",
        sa.Column("distributions", sa.JSON(), nullable=False, server_default="{}"),
    )
    # The index the live piece counter reads: rows this machine reported since
    # the cache was built. CONCURRENTLY because the box this lands on is the one
    # that was already saturated, and a plain CREATE INDEX takes a write lock on
    # the table every machine syncs into.
    if op.get_bind().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.create_index(
                "ix_machine_pieces_machine_created_at",
                "machine_pieces",
                ["machine_id", "created_at"],
                postgresql_concurrently=True,
                if_not_exists=True,
            )
    else:
        op.create_index(
            "ix_machine_pieces_machine_created_at", "machine_pieces", ["machine_id", "created_at"]
        )


def downgrade() -> None:
    op.drop_index("ix_machine_pieces_machine_created_at", table_name="machine_pieces")
    op.drop_column("machine_stats_cache", "distributions")
