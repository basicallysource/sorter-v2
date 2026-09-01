"""api key expiry and required scopes

Revision ID: f3b5d7a9c1e2
Revises: a4d6f8b0c2e5
Create Date: 2026-08-08 12:00:00.000000

API keys move to deny-by-default: a key grants exactly its stored scopes, so a
key with no scopes grants nothing. Existing ACTIVE scope-less keys are
grandfathered with the four data scopes (models/samples read+write — strictly
less than the full-account power they had before) so live consumers keep
working through the deploy; anything new they'd need must be granted
explicitly. Also adds optional expiry.

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
    # Legacy rows store empty scopes as EITHER SQL NULL or JSON null (SQLAlchemy
    # JSON columns persist Python None as JSON null by default) — prod has both
    # shapes. Catch both, or JSON-null keys would sit "Active" while deny-all.
    op.execute(
        "UPDATE user_api_keys SET scopes = "
        "'[\"models:read\", \"models:write\", \"samples:read\", \"samples:write\"]'::jsonb "
        "WHERE revoked_at IS NULL AND (scopes IS NULL OR scopes = 'null'::jsonb)"
    )


def downgrade() -> None:
    op.drop_column("user_api_keys", "expires_at")
