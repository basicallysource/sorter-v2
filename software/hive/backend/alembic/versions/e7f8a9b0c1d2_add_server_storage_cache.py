"""add server storage cache

Revision ID: e7f8a9b0c1d2
Revises: b3c4d5e6f7a8
Create Date: 2026-07-21 12:00:00.000000

Single-row cache of object-store size accounting for the admin server-health
page. A background worker walks the store on a slow cadence and upserts row
id=1; the API serves it directly instead of walking the whole bucket inside the
request (which blew past Cloudflare's proxy timeout -> 524).

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "server_storage_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sample_images_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sample_images_files", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("piece_images_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("piece_images_files", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("model_files_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("model_files_files", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("total_files", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("server_storage_cache")
