"""add sample_payload to samples

Revision ID: d6f7a8b9c0d1
Revises: c3e1a2d4b5f6
Create Date: 2026-04-16 18:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d6f7a8b9c0d1"
down_revision: Union[str, None] = "698e3443e16a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("samples", sa.Column("sample_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("samples", "sample_payload")
