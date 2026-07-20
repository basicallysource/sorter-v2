"""split a machine piece's mold and color confidence

Revision ID: d1f3b5c7e9a2
Revises: c3e5a7b9d1f4
Create Date: 2026-07-20 12:00:00.000000

machine_pieces.confidence has always been the MOLD score alone (Brickognize's
top item), even on pieces whose color came from the hosted color model. Scoring
a color provider against it therefore compared nothing. color_confidence carries
the applied color's own score — Brickognize's top-color score, or the hosted
model's softmax probability when that provider answered — so the two are
attributable to the providers that actually produced them. NULL on rows synced
before the split; existing confidence values keep their meaning and are not
backfilled or rewritten.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1f3b5c7e9a2"
down_revision: Union[str, Sequence[str], None] = "c3e5a7b9d1f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("machine_pieces", sa.Column("color_confidence", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("machine_pieces", "color_confidence")
