"""Telemetry limits Hive hands machines on heartbeat

Revision ID: c8f2a6d4e1b3
Revises: d5c8a1f3b7e2

telemetry_limits: one global row (id = 1) with how fast a machine may capture
training samples, how large its local sample store may grow, and its upload
budget per minute. No row is seeded: while it is missing the code defaults
apply, and the first admin change creates it.
"""

import sqlalchemy as sa
from alembic import op

revision = "c8f2a6d4e1b3"
down_revision = "d5c8a1f3b7e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telemetry_limits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("sample_burst_interval_s", sa.Float(), nullable=False, server_default=sa.text("10.0")),
        sa.Column("sample_floor_interval_s", sa.Float(), nullable=False, server_default=sa.text("3600.0")),
        sa.Column("sample_ramp_hours", sa.Float(), nullable=False, server_default=sa.text("72.0")),
        sa.Column("sample_store_max_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("1073741824")),
        sa.Column("upload_bytes_per_minute", sa.BigInteger(), nullable=False, server_default=sa.text("30000000")),
        sa.Column("upload_files_per_minute", sa.Integer(), nullable=False, server_default=sa.text("120")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_telemetry_limits_single_row"),
    )


def downgrade() -> None:
    op.drop_table("telemetry_limits")
