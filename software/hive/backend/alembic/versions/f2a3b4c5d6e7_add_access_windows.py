"""add per-role visibility windows for piece-bbox data

Revision ID: f2a3b4c5d6e7
Revises: d5e6f7a8b9c0
Create Date: 2026-07-14 12:00:00.000000

Bounds what a non-admin user can see/download of the accumulating piece +
channel-crop dataset. One row per (role, entity); absent rows fall back to code
defaults in services.access_window, so this table is empty on first deploy and
the feature still works. Admins have no rows and are unrestricted.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "access_windows",
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("entity", sa.String(), nullable=False),
        sa.Column("anchor", sa.String(), nullable=False),
        sa.Column("window_size", sa.Integer(), nullable=False),
        sa.Column("window_offset", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("role", "entity"),
        sa.CheckConstraint("anchor IN ('oldest', 'newest')", name="ck_access_windows_anchor"),
        sa.CheckConstraint("window_size >= 0", name="ck_access_windows_size"),
        sa.CheckConstraint("window_offset >= 0", name="ck_access_windows_offset"),
    )


def downgrade() -> None:
    op.drop_table("access_windows")
