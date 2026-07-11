"""add machine daily stats

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f7
Create Date: 2026-07-11 22:30:00.000000

Per-machine per-day pieces/distributed/active-seconds, the substrate for the
analytics time-series (pieces / PPM / sorting-capacity over time) across any set
of machines. Refreshed hourly by the machine-stats worker.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_daily_stats",
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("pieces_seen", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("distributed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("active_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("machine_id", "day"),
    )


def downgrade() -> None:
    op.drop_table("machine_daily_stats")
