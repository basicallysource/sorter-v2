"""The piece grid's walks of pieces with same-piece candidates

Revision ID: c2e8a4f6b0d3
Revises: b9d3f5a7c1e2
Create Date: 2026-10-12

The Piece samples grid shows only pieces with same-piece candidates unless
asked otherwise, and walks the labeling queue in arrival order. Pieces from
before channel crops were synced, or from a machine without C2/C3 cameras,
have none, so a walk through them (the "oldest" sort, or one such machine)
read every one of them to find the first page: 147k rows on a production-sized
queue. These indexes hold only the pieces with candidates, in the grid's two
walk orders (every machine, one machine).

Built CONCURRENTLY outside a transaction, so the queue worker keeps writing;
the predicate is written as the grid's query writes it.
"""

from alembic import op
from sqlalchemy import text

revision = "c2e8a4f6b0d3"
down_revision = "b9d3f5a7c1e2"
branch_labels = None
depends_on = None

INDEXES = {
    "ix_labeling_queue_candidates_arrival": "(arrival_at, machine_id, piece_uuid) WHERE has_candidates IS true",
    "ix_labeling_queue_machine_candidates_arrival": "(machine_id, arrival_at, piece_uuid) WHERE has_candidates IS true",
}


def create_concurrently(table: str, name: str, definition: str) -> None:
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
    with op.get_context().autocommit_block():
        for name, definition in INDEXES.items():
            create_concurrently("labeling_queue", name, definition)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
