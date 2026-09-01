"""add piece crop ai predictions

Revision ID: d5e6f7a8b9c0
Revises: e7c1a2b3d4f5
Create Date: 2026-07-13 22:30:00.000000

A vision model's "which upstream C2/C3 crops are the same physical piece" guess
for a classified piece — the AI analog of the time/angle heuristic. Populated
out-of-band; the labeling page pre-selects the AI's picks instead of the
heuristic's when a row exists. One row per (machine, piece); a re-run overwrites.
Stored separately from piece_crop_links (human ground truth).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "e7c1a2b3d4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(JSONB, "postgresql")
    op.create_table(
        "piece_crop_ai_predictions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("machine_id", sa.UUID(), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("reasoning", sa.String(), nullable=True),
        sa.Column("candidate_local_ids", json_type, nullable=False),
        sa.Column("same_local_ids", json_type, nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("machine_id", "piece_uuid", name="uq_piece_crop_ai_predictions_machine_piece"),
    )
    op.create_index(
        "ix_piece_crop_ai_predictions_machine_piece",
        "piece_crop_ai_predictions",
        ["machine_id", "piece_uuid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_piece_crop_ai_predictions_machine_piece", table_name="piece_crop_ai_predictions")
    op.drop_table("piece_crop_ai_predictions")
