"""add brickognize corrections to machine_pieces

Revision ID: b8c9d0e1f2a3
Revises: d1e2f3a4b5c6
Create Date: 2026-07-13 21:00:00.000000

Adds Brickognize-correction columns to machine_pieces: the applied request's
provenance (listing id + result ranks + item type) so a correction can be
submitted to Brickognize's feedback API, plus the user's correction (part
correct/wrong, corrected color) and whether it was submitted. Synced from the
machine via the new piece_corrections stream and/or set here on Hive.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("machine_pieces", sa.Column("brickognize_listing_id", sa.String(), nullable=True))
    op.add_column("machine_pieces", sa.Column("brickognize_item_rank", sa.Integer(), nullable=True))
    op.add_column("machine_pieces", sa.Column("brickognize_item_type", sa.String(), nullable=True))
    op.add_column("machine_pieces", sa.Column("brickognize_color_rank", sa.Integer(), nullable=True))
    op.add_column("machine_pieces", sa.Column("part_correct", sa.Boolean(), nullable=True))
    op.add_column("machine_pieces", sa.Column("color_corrected_id", sa.String(), nullable=True))
    op.add_column(
        "machine_pieces",
        sa.Column("part_feedback_submitted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "machine_pieces",
        sa.Column("color_feedback_submitted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("machine_pieces", sa.Column("correction_updated_at", sa.DateTime(timezone=True), nullable=True))
    # Drop the server defaults now that existing rows are backfilled — new rows
    # get their default from the app-side model.
    op.alter_column("machine_pieces", "part_feedback_submitted", server_default=None)
    op.alter_column("machine_pieces", "color_feedback_submitted", server_default=None)


def downgrade() -> None:
    op.drop_column("machine_pieces", "correction_updated_at")
    op.drop_column("machine_pieces", "color_feedback_submitted")
    op.drop_column("machine_pieces", "part_feedback_submitted")
    op.drop_column("machine_pieces", "color_corrected_id")
    op.drop_column("machine_pieces", "part_correct")
    op.drop_column("machine_pieces", "brickognize_color_rank")
    op.drop_column("machine_pieces", "brickognize_item_type")
    op.drop_column("machine_pieces", "brickognize_item_rank")
    op.drop_column("machine_pieces", "brickognize_listing_id")
