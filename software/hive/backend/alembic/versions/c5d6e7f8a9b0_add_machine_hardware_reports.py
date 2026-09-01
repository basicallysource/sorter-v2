"""add machine_hardware_reports

Revision ID: c5d6e7f8a9b0
Revises: f2a3b4c5d6e7
Create Date: 2026-07-14

Append-only log of a machine's hardware/software specs over time. The sorter
attaches a specs snapshot to its heartbeat; a new row lands only when the
machine reboots or its specs change, so the log tracks the machine's hardware
across restarts.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "machine_hardware_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("boot_id", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("specs", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_machine_hardware_reports_machine_reported",
        "machine_hardware_reports",
        ["machine_id", "reported_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_machine_hardware_reports_machine_reported", table_name="machine_hardware_reports")
    op.drop_table("machine_hardware_reports")
