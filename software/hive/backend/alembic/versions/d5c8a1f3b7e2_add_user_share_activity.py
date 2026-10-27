"""users.share_activity: the owner's opt-in to a live activity listing

Revision ID: d5c8a1f3b7e2
Revises: b7e4c2a9d1f0
Create Date: 2026-10-10 12:00:00.000000

A user may let a public consumer holding a fleet:read key list their machines
in a live "what is sorting right now" view. The setting is per user and off by
default, so every existing row migrates to false and stays out of that view
until its owner turns it on.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5c8a1f3b7e2"
down_revision: Union[str, Sequence[str], None] = "b7e4c2a9d1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("share_activity", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "share_activity")
