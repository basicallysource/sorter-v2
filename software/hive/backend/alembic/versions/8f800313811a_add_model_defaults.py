"""add model_defaults

One row per (purpose, runtime): the model variant a fresh install downloads
when it has no Hive account to browse the catalog with. Picked by an admin.

Revision ID: 8f800313811a
Revises: e1f2a3b4c5d6
"""

import sqlalchemy as sa
from alembic import op

revision = "8f800313811a"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_defaults",
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("runtime", sa.String(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=False),
        sa.Column("variant_id", sa.UUID(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["detection_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["variant_id"], ["detection_model_variants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("purpose", "runtime"),
    )


def downgrade() -> None:
    op.drop_table("model_defaults")
