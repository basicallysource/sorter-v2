"""add rejection_reasons to machine_pieces

Revision ID: a1c3e5f7b9d2
Revises: e4a6b8c0d2f5
Create Date: 2026-07-19 13:00:00.000000

Operator-flagged capture issues, synced from the machine's piece_corrections
stream alongside part_correct / color_corrected_id. A JSON list of reason
codes (no_piece / multiple_pieces / not_lego) — the same vocabulary as
piece_rejections.reasons, so a machine operator's verdict and a Hive labeler's
verdict mean the same thing.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1c3e5f7b9d2"
down_revision: Union[str, Sequence[str], None] = "e4a6b8c0d2f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "machine_pieces",
        sa.Column(
            "rejection_reasons",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("machine_pieces", "rejection_reasons")
