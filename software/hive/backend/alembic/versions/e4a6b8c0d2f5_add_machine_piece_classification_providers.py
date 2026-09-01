"""record which provider produced a machine piece's color / mold

Revision ID: e4a6b8c0d2f5
Revises: d3f5a7b9c1e4
Create Date: 2026-07-19 12:00:00.000000

The color and mold providers are selectable per machine, so a synced piece now
carries which service actually answered for it. These record what ANSWERED, not
what was configured — a hosted color provider that times out falls back to
Brickognize and is recorded as brickognize — which is what makes provider
accuracy scoreable against the correction columns. NULL on rows synced before
providers were selectable.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4a6b8c0d2f5"
down_revision: Union[str, Sequence[str], None] = "d3f5a7b9c1e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("machine_pieces", sa.Column("color_provider", sa.String(), nullable=True))
    op.add_column("machine_pieces", sa.Column("mold_provider", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("machine_pieces", "mold_provider")
    op.drop_column("machine_pieces", "color_provider")
