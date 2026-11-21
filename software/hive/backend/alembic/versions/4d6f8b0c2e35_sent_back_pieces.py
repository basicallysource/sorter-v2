"""Pieces a machine sent back to be sorted again

Revision ID: 4d6f8b0c2e35
Revises: 3c5e7a9b1d24
Create Date: 2026-11-21

- machine_sent_back_pieces: the pieces a machine sent back (a bin's pieces
  went back in the hopper), synced from it (data type sent_back_pieces). Their
  records stay, but no run or lot counts them.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "4d6f8b0c2e35"
down_revision = "3c5e7a9b1d24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "machine_sent_back_pieces",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("piece_uuid", sa.String(), primary_key=True),
        sa.Column("local_id", sa.BigInteger(), nullable=False),
        sa.Column("lot_id", sa.String(), nullable=True),
        sa.Column("sent_back_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("machine_sent_back_pieces")
