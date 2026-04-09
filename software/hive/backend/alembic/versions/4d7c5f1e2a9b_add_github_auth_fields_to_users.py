"""add github auth fields to users

Revision ID: 4d7c5f1e2a9b
Revises: 8d8fe12f5fb5
Create Date: 2026-04-01 16:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4d7c5f1e2a9b"
down_revision: Union[str, None] = "8d8fe12f5fb5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("github_id", sa.String(), nullable=True))
    op.add_column("users", sa.Column("github_login", sa.String(), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(), nullable=True))
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=True)
    op.create_index("ix_users_github_id", "users", ["github_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_github_id", table_name="users")
    op.alter_column("users", "password_hash", existing_type=sa.String(), nullable=False)
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "github_login")
    op.drop_column("users", "github_id")
