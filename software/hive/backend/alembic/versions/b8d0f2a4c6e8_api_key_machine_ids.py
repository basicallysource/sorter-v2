"""api key machine ids

Revision ID: b8d0f2a4c6e8
Revises: a6c8e0b2d4f6
Create Date: 2026-08-09 12:30:00.000000

Optional machine whitelist on API keys: a key with machine_ids set can only
touch machine-owned data (samples, pieces, crops) of those machines. Null =
unconstrained, so existing keys keep their behavior.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b8d0f2a4c6e8"
down_revision: Union[str, None] = "a6c8e0b2d4f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_api_keys",
        sa.Column("machine_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_api_keys", "machine_ids")
