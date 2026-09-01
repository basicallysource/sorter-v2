"""allow "I can't tell" color labels

Revision ID: b7d1e2f3a4c5
Revises: f2a3b4c5d6e7
Create Date: 2026-07-14 16:00:00.000000

A labeler can now answer "I can't tell" for a piece's color — a real answer
(the color is genuinely indeterminate), distinct from not labeling. Stored in
the same piece_color_labels row: color_id becomes nullable and a cant_tell flag
marks the indeterminate answer. Existing rows are all real colors (cant_tell
false).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d1e2f3a4c5"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "piece_color_labels",
        sa.Column("cant_tell", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("piece_color_labels", "color_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Drop the indeterminate rows so color_id can go back to NOT NULL.
    op.execute("DELETE FROM piece_color_labels WHERE color_id IS NULL")
    op.alter_column("piece_color_labels", "color_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("piece_color_labels", "cant_tell")
