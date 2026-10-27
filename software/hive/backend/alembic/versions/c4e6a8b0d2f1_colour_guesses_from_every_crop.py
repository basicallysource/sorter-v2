"""Colour guesses from every C4 crop

Revision ID: c4e6a8b0d2f1
Revises: b3d5f7a9c1e4
Create Date: 2026-10-14

A piece's colour guesses (piece_color_guesses) are now made from every crop the
classification camera took, not only the ones the machine used. The kept
guesses were made from the old choice, so they are dropped: the grid's
piece_warm jobs make them again for the pieces a page shows, before anyone
opens one. The table only keeps guesses, so a downgrade has nothing to restore.
"""

from alembic import op

revision = "c4e6a8b0d2f1"
down_revision = "b3d5f7a9c1e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM piece_color_guesses")


def downgrade() -> None:
    pass
