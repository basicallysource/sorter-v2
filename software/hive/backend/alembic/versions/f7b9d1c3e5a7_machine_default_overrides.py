"""Defaults an admin sets for every sorter

Revision ID: f7b9d1c3e5a7
Revises: e6a8c0b2d4f6
Create Date: 2026-10-18

- machine_default_overrides: one default every sorter is served, set by an
  admin over the one in Hive's code (services/machine_defaults.py).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f7b9d1c3e5a7"
down_revision = "e6a8c0b2d4f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machine_default_overrides",
        sa.Column("path", sa.String(), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("machine_default_overrides")
