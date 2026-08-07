"""add ai usage events

Revision ID: a4d6f8b0c2e5
Revises: a3c5e7b9d1f4
Create Date: 2026-07-29 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a4d6f8b0c2e5"
down_revision: Union[str, None] = "a3c5e7b9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("generation_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["sorting_profiles.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["sorting_profile_ai_messages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_usage_events_user_id", "ai_usage_events", ["user_id"], unique=False)
    op.create_index("ix_ai_usage_events_profile_id", "ai_usage_events", ["profile_id"], unique=False)
    op.create_index("ix_ai_usage_events_created_at", "ai_usage_events", ["created_at"], unique=False)
    op.create_index("ix_ai_usage_events_user_created", "ai_usage_events", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ai_usage_events_user_created", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_created_at", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_profile_id", table_name="ai_usage_events")
    op.drop_index("ix_ai_usage_events_user_id", table_name="ai_usage_events")
    op.drop_table("ai_usage_events")
