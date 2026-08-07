"""device ping telemetry columns

Revision ID: c3a5b7d9e1f2
Revises: b2f4c6d8e0a1
Create Date: 2026-07-19 14:00:00.000000

The anonymous installs system merges into the Device identity: the machine's
hourly status ping now lands on its device row (POST /api/devices/ping), so
devices grows the installs table's telemetry column block. The installs table
itself stays for machines running pre-merge software; a post-merge machine's
first ping absorbs (and deletes) its legacy row via install_id.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c3a5b7d9e1f2"
down_revision: Union[str, Sequence[str], None] = "b2f4c6d8e0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("devices", sa.Column("first_ping_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("ping_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("devices", sa.Column("last_ping_reason", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("reported_created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("devices", sa.Column("country", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("region", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("software_version", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("channel", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("commit", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("os_name", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("sorter_os_version", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("hw_model", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("ram_bytes", sa.BigInteger(), nullable=True))
    op.add_column("devices", sa.Column("cpu_temp_c", sa.Float(), nullable=True))
    op.add_column("devices", sa.Column("disk_free_bytes", sa.BigInteger(), nullable=True))
    op.add_column("devices", sa.Column("disk_total_bytes", sa.BigInteger(), nullable=True))
    op.add_column("devices", sa.Column("machine_setup", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("feeder_mode", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("classification_channel_mode", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("pieces_seen", sa.BigInteger(), nullable=True))
    op.add_column("devices", sa.Column("pieces_classified", sa.BigInteger(), nullable=True))
    op.add_column("devices", sa.Column("pieces_distributed", sa.BigInteger(), nullable=True))
    op.add_column("devices", sa.Column("seconds_powered", sa.Float(), nullable=True))
    op.add_column("devices", sa.Column("seconds_sorted", sa.Float(), nullable=True))
    op.add_column("devices", sa.Column("best_hour_ppm", sa.Float(), nullable=True))
    op.add_column("devices", sa.Column("registered", sa.Boolean(), nullable=True))
    op.add_column("devices", sa.Column("process_uptime_s", sa.Float(), nullable=True))
    op.add_column("devices", sa.Column("system_uptime_s", sa.Float(), nullable=True))
    op.add_column("devices", sa.Column("local_machine_id", sa.String(), nullable=True))
    op.add_column("devices", sa.Column("accounts", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("devices", sa.Column("last_ping_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_index("ix_devices_install_id", "devices", ["install_id"], unique=False)
    op.create_index("ix_devices_last_seen_at", "devices", ["last_seen_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_devices_last_seen_at", table_name="devices")
    op.drop_index("ix_devices_install_id", table_name="devices")
    for column in (
        "last_ping_payload",
        "accounts",
        "local_machine_id",
        "system_uptime_s",
        "process_uptime_s",
        "registered",
        "best_hour_ppm",
        "seconds_sorted",
        "seconds_powered",
        "pieces_distributed",
        "pieces_classified",
        "pieces_seen",
        "classification_channel_mode",
        "feeder_mode",
        "machine_setup",
        "disk_total_bytes",
        "disk_free_bytes",
        "cpu_temp_c",
        "ram_bytes",
        "hw_model",
        "sorter_os_version",
        "os_name",
        "commit",
        "channel",
        "software_version",
        "region",
        "country",
        "reported_created_at",
        "last_ping_reason",
        "ping_count",
        "first_ping_at",
    ):
        op.drop_column("devices", column)
