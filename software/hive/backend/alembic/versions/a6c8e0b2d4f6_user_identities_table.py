"""user identities table

Revision ID: a6c8e0b2d4f6
Revises: f3b5d7a9c1e2
Create Date: 2026-08-09 12:00:00.000000

Sign-in identities move off provider-specific columns on users and into
user_identities, so one account can link several providers (GitHub, Discord,
...). Backfills a github identity row for every user that had github_id set,
then drops users.github_id / users.github_login (github_login stays in API
responses via a compatibility property on the User model).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a6c8e0b2d4f6"
down_revision: Union[str, None] = "f3b5d7a9c1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("provider_user_id", sa.String(), nullable=False),
        sa.Column("provider_login", sa.String(), nullable=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_user_identities_provider_account"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identities_user_provider"),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])

    op.execute(
        """
        INSERT INTO user_identities (id, user_id, provider, provider_user_id, provider_login, avatar_url, created_at)
        SELECT gen_random_uuid(), id, 'github', github_id, github_login, avatar_url, CURRENT_TIMESTAMP
        FROM users
        WHERE github_id IS NOT NULL
        """
    )

    op.drop_column("users", "github_id")
    op.drop_column("users", "github_login")


def downgrade() -> None:
    op.add_column("users", sa.Column("github_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("github_login", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE users SET github_id = ui.provider_user_id, github_login = ui.provider_login
        FROM user_identities ui
        WHERE ui.user_id = users.id AND ui.provider = 'github'
        """
    )
    op.create_index("ix_users_github_id", "users", ["github_id"], unique=True)
    op.drop_index("ix_user_identities_user_id", table_name="user_identities")
    op.drop_table("user_identities")
