"""Machines' telemetry records

Revision ID: e6a8c0b2d4f6
Revises: d5f7b9c1e3a5
Create Date: 2026-10-18

- machine_telemetry: how each sorter is set up and how it runs (machine specs,
  stepper load, camera readings, stalls), synced by the machine's local id
  (data type telemetry). See agent-docs/telemetry.md.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e6a8c0b2d4f6"
down_revision = "d5f7b9c1e3a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machine_telemetry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("form", sa.String(length=16), nullable=False),
        sa.Column("schema", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("machine_id", "local_id", name="uq_machine_telemetry_machine_local"),
    )
    op.create_index(
        "ix_machine_telemetry_machine_kind_started", "machine_telemetry", ["machine_id", "kind", "started_at"]
    )
    op.create_index("ix_machine_telemetry_kind_started", "machine_telemetry", ["kind", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_machine_telemetry_kind_started", table_name="machine_telemetry")
    op.drop_index("ix_machine_telemetry_machine_kind_started", table_name="machine_telemetry")
    op.drop_table("machine_telemetry")
