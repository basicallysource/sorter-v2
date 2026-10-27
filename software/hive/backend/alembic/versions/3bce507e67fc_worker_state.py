"""worker_state: what the worker process and the web process tell each other

Revision ID: 3bce507e67fc
Revises: c548fb8d227c

Hive runs as a web process and a worker process (agent-docs/process-roles.md).
One row per name: a background worker's published answer
(published:fleet_mass, published:fleet_records), the worker process's
heartbeat with each worker's state, and requests from the web process to the
worker (request:...). A handful of rows; nothing reads it but by name.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "3bce507e67fc"
down_revision = "c548fb8d227c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "worker_state",
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("worker_state")
