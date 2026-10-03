"""Kits, default profiles, and where each profile version came from

Revision ID: b7e4c2a9d1f0
Revises: cd68a2ba2d51

kits: a list of parts in colors with quantities that a profile's kit rule
collects into one bin (what a "set" rule held inline before).

sorting_profiles.system_key and default_rank: the profiles Hive keeps from
definitions in code and gives every machine.

sorting_profile_versions.created_via and created_via_key_id: whether a
version was saved in the editor, through an API key (and which), by the
editor's chat, or by Hive itself, so a page can say who changed a profile.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b7e4c2a9d1f0"
down_revision = "cd68a2ba2d51"
branch_labels = None
depends_on = None

JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "kits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="custom"),
        sa.Column("set_num", sa.String(), nullable=True),
        sa.Column("set_meta", JSON, nullable=True),
        sa.Column("include_spares", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("visibility", sa.String(), nullable=False, server_default="private"),
        sa.Column("parts", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("visibility IN ('private', 'unlisted', 'public')", name="ck_kits_visibility"),
        sa.CheckConstraint("source IN ('custom', 'set', 'bricklink')", name="ck_kits_source"),
    )
    op.create_index("ix_kits_owner_id", "kits", ["owner_id"])

    op.add_column("sorting_profiles", sa.Column("system_key", sa.String(), nullable=True))
    op.add_column("sorting_profiles", sa.Column("default_rank", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_sorting_profiles_system_key", "sorting_profiles", ["system_key"])

    op.add_column("sorting_profile_versions", sa.Column("created_via", sa.String(), nullable=True))
    op.add_column(
        "sorting_profile_versions",
        sa.Column(
            "created_via_key_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_api_keys.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sorting_profile_versions", "created_via_key_id")
    op.drop_column("sorting_profile_versions", "created_via")
    op.drop_constraint("uq_sorting_profiles_system_key", "sorting_profiles", type_="unique")
    op.drop_column("sorting_profiles", "default_rank")
    op.drop_column("sorting_profiles", "system_key")
    op.drop_index("ix_kits_owner_id", table_name="kits")
    op.drop_table("kits")
