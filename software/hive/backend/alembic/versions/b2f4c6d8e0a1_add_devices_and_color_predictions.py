"""add devices and color_predictions

Revision ID: b2f4c6d8e0a1
Revises: a8c1d2e3f4a5
Create Date: 2026-07-19 12:00:00.000000

The hosted-services layer: `devices` is a sorter's silent enrollment identity
(distinct from account-scoped `machines`; machine_id/install_id are nullable
future merge points), and `color_predictions` logs every served color
prediction with its uploaded crops so the color model can be retrained on real
in-the-wild input. color_predictions.color_model_id is SET NULL on delete
because color_model rows are reconciled from a dir scan and vanish when their
file does — the denormalized sha256/filename are the durable provenance.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b2f4c6d8e0a1"
down_revision: Union[str, Sequence[str], None] = "a8c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "devices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("device_key", sa.String(length=128), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("token_prefix", sa.String(length=8), nullable=False),
        sa.Column("hardware_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("last_seen_ip", sa.String(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=True),
        sa.Column("install_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_key", name="uq_devices_device_key"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_devices_machine_id", "devices", ["machine_id"], unique=False)

    op.create_table(
        "color_predictions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("device_id", sa.UUID(), nullable=False),
        sa.Column("color_model_id", sa.UUID(), nullable=True),
        sa.Column("color_model_name", sa.String(), nullable=True),
        sa.Column("color_model_filename", sa.String(), nullable=True),
        sa.Column("color_model_sha256", sa.String(length=64), nullable=True),
        sa.Column("multiview", sa.Boolean(), nullable=True),
        sa.Column("method", sa.String(), nullable=True),
        sa.Column("predicted_color_id", sa.Integer(), nullable=True),
        sa.Column("predicted_color_name", sa.String(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("top", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("image_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("channels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("scored_count", sa.Integer(), nullable=True),
        sa.Column("client_info", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("request_ip", sa.String(), nullable=True),
        sa.Column("inference_ms", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["device_id"], ["devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["color_model_id"], ["color_models.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_color_predictions_device_created", "color_predictions", ["device_id", "created_at"], unique=False)
    op.create_index("ix_color_predictions_created_at", "color_predictions", ["created_at"], unique=False)
    op.create_index("ix_color_predictions_model_sha", "color_predictions", ["color_model_sha256"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_color_predictions_model_sha", table_name="color_predictions")
    op.drop_index("ix_color_predictions_created_at", table_name="color_predictions")
    op.drop_index("ix_color_predictions_device_created", table_name="color_predictions")
    op.drop_table("color_predictions")
    op.drop_index("ix_devices_machine_id", table_name="devices")
    op.drop_table("devices")
