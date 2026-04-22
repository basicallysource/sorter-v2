"""add sorting profiles

Revision ID: c3e1a2d4b5f6
Revises: 4d7c5f1e2a9b
Create Date: 2026-04-03 16:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c3e1a2d4b5f6"
down_revision: Union[str, None] = "4d7c5f1e2a9b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("openrouter_api_key_encrypted", sa.String(), nullable=True))
    op.add_column("users", sa.Column("preferred_ai_model", sa.String(), nullable=True))

    op.create_table(
        "sorting_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("source_profile_id", sa.UUID(), nullable=True),
        sa.Column("source_version_number", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("visibility", sa.String(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latest_version_number", sa.Integer(), nullable=False),
        sa.Column("latest_published_version_number", sa.Integer(), nullable=True),
        sa.Column("library_count", sa.Integer(), nullable=False),
        sa.Column("fork_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "visibility IN ('private', 'unlisted', 'public')",
            name="ck_sorting_profiles_visibility",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_profile_id"], ["sorting_profiles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sorting_profiles_owner_id", "sorting_profiles", ["owner_id"], unique=False)
    op.create_index("ix_sorting_profiles_visibility", "sorting_profiles", ["visibility"], unique=False)

    op.create_table(
        "sorting_profile_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("default_category_id", sa.String(), nullable=False),
        sa.Column("rules_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fallback_mode_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compiled_artifact_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compiled_stats_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("compiled_hash", sa.String(), nullable=False),
        sa.Column("compiled_part_count", sa.Integer(), nullable=False),
        sa.Column("coverage_ratio", sa.Float(), nullable=True),
        sa.Column("is_published", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["profile_id"], ["sorting_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "profile_id",
            "version_number",
            name="uq_sorting_profile_versions_profile_version",
        ),
    )
    op.create_index("ix_sorting_profile_versions_profile_id", "sorting_profile_versions", ["profile_id"], unique=False)
    op.create_index("ix_sorting_profile_versions_created_at", "sorting_profile_versions", ["created_at"], unique=False)
    op.create_index(
        "ix_sorting_profile_versions_is_published",
        "sorting_profile_versions",
        ["is_published"],
        unique=False,
    )

    op.create_table(
        "sorting_profile_library_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["sorting_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "profile_id",
            name="uq_sorting_profile_library_entries_user_profile",
        ),
    )
    op.create_index(
        "ix_sorting_profile_library_entries_user_id",
        "sorting_profile_library_entries",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_sorting_profile_library_entries_profile_id",
        "sorting_profile_library_entries",
        ["profile_id"],
        unique=False,
    )

    op.create_table(
        "sorting_profile_ai_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=True),
        sa.Column("applied_version_id", sa.UUID(), nullable=True),
        sa.Column("selected_rule_id", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("usage_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("proposal_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')",
            name="ck_sorting_profile_ai_messages_role",
        ),
        sa.ForeignKeyConstraint(["applied_version_id"], ["sorting_profile_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["profile_id"], ["sorting_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["version_id"], ["sorting_profile_versions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sorting_profile_ai_messages_profile_id", "sorting_profile_ai_messages", ["profile_id"], unique=False)
    op.create_index("ix_sorting_profile_ai_messages_user_id", "sorting_profile_ai_messages", ["user_id"], unique=False)
    op.create_index(
        "ix_sorting_profile_ai_messages_created_at",
        "sorting_profile_ai_messages",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "machine_profile_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("desired_version_id", sa.UUID(), nullable=True),
        sa.Column("active_version_id", sa.UUID(), nullable=True),
        sa.Column("assigned_by_id", sa.UUID(), nullable=True),
        sa.Column("artifact_hash", sa.String(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["active_version_id"], ["sorting_profile_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["desired_version_id"], ["sorting_profile_versions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["profile_id"], ["sorting_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id"),
    )
    op.create_index("ix_machine_profile_assignments_machine_id", "machine_profile_assignments", ["machine_id"], unique=False)
    op.create_index("ix_machine_profile_assignments_profile_id", "machine_profile_assignments", ["profile_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_machine_profile_assignments_profile_id", table_name="machine_profile_assignments")
    op.drop_index("ix_machine_profile_assignments_machine_id", table_name="machine_profile_assignments")
    op.drop_table("machine_profile_assignments")

    op.drop_index("ix_sorting_profile_ai_messages_created_at", table_name="sorting_profile_ai_messages")
    op.drop_index("ix_sorting_profile_ai_messages_user_id", table_name="sorting_profile_ai_messages")
    op.drop_index("ix_sorting_profile_ai_messages_profile_id", table_name="sorting_profile_ai_messages")
    op.drop_table("sorting_profile_ai_messages")

    op.drop_index("ix_sorting_profile_library_entries_profile_id", table_name="sorting_profile_library_entries")
    op.drop_index("ix_sorting_profile_library_entries_user_id", table_name="sorting_profile_library_entries")
    op.drop_table("sorting_profile_library_entries")

    op.drop_index("ix_sorting_profile_versions_is_published", table_name="sorting_profile_versions")
    op.drop_index("ix_sorting_profile_versions_created_at", table_name="sorting_profile_versions")
    op.drop_index("ix_sorting_profile_versions_profile_id", table_name="sorting_profile_versions")
    op.drop_table("sorting_profile_versions")

    op.drop_index("ix_sorting_profiles_visibility", table_name="sorting_profiles")
    op.drop_index("ix_sorting_profiles_owner_id", table_name="sorting_profiles")
    op.drop_table("sorting_profiles")

    op.drop_column("users", "preferred_ai_model")
    op.drop_column("users", "openrouter_api_key_encrypted")
