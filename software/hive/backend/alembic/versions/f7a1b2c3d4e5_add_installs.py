"""add installs

Revision ID: f7a1b2c3d4e5
Revises: e5f6a7b8c9d0
Create Date: 2026-07-13 21:00:00.000000

The anonymous fleet table. One row per sorter install, keyed by a random
install_id the machine generates itself (status_ping.py) — deliberately NOT
joined to machines/owners, so it answers "who is out there and online" for
registered and unregistered machines alike, and can be wiped by install_id via
the public /forget endpoint without touching account-linked data.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "f7a1b2c3d4e5"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "installs",
        sa.Column("install_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ping_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reason", sa.String(), nullable=True),
        sa.Column("last_ip", sa.String(), nullable=True),
        sa.Column("country", sa.String(), nullable=True),
        sa.Column("region", sa.String(), nullable=True),
        sa.Column("software_version", sa.String(), nullable=True),
        sa.Column("channel", sa.String(), nullable=True),
        sa.Column("commit", sa.String(), nullable=True),
        sa.Column("os_name", sa.String(), nullable=True),
        sa.Column("sorter_os_version", sa.String(), nullable=True),
        sa.Column("hw_model", sa.String(), nullable=True),
        sa.Column("ram_bytes", sa.BigInteger(), nullable=True),
        sa.Column("cpu_temp_c", sa.Float(), nullable=True),
        sa.Column("disk_free_bytes", sa.BigInteger(), nullable=True),
        sa.Column("disk_total_bytes", sa.BigInteger(), nullable=True),
        sa.Column("machine_setup", sa.String(), nullable=True),
        sa.Column("feeder_mode", sa.String(), nullable=True),
        sa.Column("classification_channel_mode", sa.String(), nullable=True),
        sa.Column("pieces_seen", sa.BigInteger(), nullable=True),
        sa.Column("pieces_classified", sa.BigInteger(), nullable=True),
        sa.Column("pieces_distributed", sa.BigInteger(), nullable=True),
        sa.Column("seconds_powered", sa.Float(), nullable=True),
        sa.Column("seconds_sorted", sa.Float(), nullable=True),
        sa.Column("best_hour_ppm", sa.Float(), nullable=True),
        sa.Column("registered", sa.Boolean(), nullable=True),
        sa.Column("process_uptime_s", sa.Float(), nullable=True),
        sa.Column("system_uptime_s", sa.Float(), nullable=True),
        sa.Column("machine_id", sa.String(), nullable=True),
        sa.Column("accounts", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True),
        sa.Column("last_payload", sa.JSON().with_variant(JSONB, "postgresql"), nullable=True),
        sa.PrimaryKeyConstraint("install_id"),
    )
    op.create_index("ix_installs_last_seen_at", "installs", ["last_seen_at"])
    op.create_index("ix_installs_software_version", "installs", ["software_version"])
    op.create_index("ix_installs_country", "installs", ["country"])
    op.create_index("ix_installs_machine_id", "installs", ["machine_id"])


def downgrade() -> None:
    op.drop_index("ix_installs_machine_id", table_name="installs")
    op.drop_index("ix_installs_country", table_name="installs")
    op.drop_index("ix_installs_software_version", table_name="installs")
    op.drop_index("ix_installs_last_seen_at", table_name="installs")
    op.drop_table("installs")
