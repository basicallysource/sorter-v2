"""api key expiry and required scopes

Revision ID: f3b5d7a9c1e2
Revises: a4d6f8b0c2e5
Create Date: 2026-08-08 12:00:00.000000

API keys move to deny-by-default: a key grants exactly its stored scopes, so a
key with no scopes grants nothing. Existing scope-less keys are revoked here
(rather than left silently dead) so they show as revoked in the UI. Also adds
optional expiry.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3b5d7a9c1e2"
down_revision: Union[str, None] = "a4d6f8b0c2e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_api_keys",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE user_api_keys SET revoked_at = CURRENT_TIMESTAMP "
        "WHERE revoked_at IS NULL AND scopes IS NULL"
    )


def downgrade() -> None:
    op.drop_column("user_api_keys", "expires_at")
