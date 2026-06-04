"""add machine_config_backups

Revision ID: b1c2d3e4f5a6
Revises: e9f0a1b2c3d4
Create Date: 2026-06-04

Versioned snapshots of a machine's settings (machine_params.toml + curated
local_state), pushed by the sorter. The sorter content-hashes before sending,
so a new row lands only when the config actually changed.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_config_backups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("trigger", sa.String(), nullable=False, server_default="config_change"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "version", name="uq_machine_config_backups_machine_version"),
    )
    op.create_index("ix_machine_config_backups_machine_id", "machine_config_backups", ["machine_id"])
    op.create_index("ix_machine_config_backups_created_at", "machine_config_backups", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_machine_config_backups_created_at", table_name="machine_config_backups")
    op.drop_index("ix_machine_config_backups_machine_id", table_name="machine_config_backups")
    op.drop_table("machine_config_backups")
