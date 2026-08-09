"""add model_dataset_samples

Revision ID: c9e1f3a5b7d9
Revises: b8d0f2a4c6e8
Create Date: 2026-08-09 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e1f3a5b7d9"
down_revision: Union[str, None] = "b8d0f2a4c6e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_dataset_samples",
        sa.Column("model_id", sa.UUID(), nullable=False),
        sa.Column("sample_id", sa.UUID(), nullable=False),
        sa.Column("split", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["detection_models.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["sample_id"], ["samples.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("model_id", "sample_id"),
        sa.CheckConstraint("split IN ('train', 'val')", name="ck_model_dataset_samples_split"),
    )
    op.create_index(
        "ix_model_dataset_samples_sample_id", "model_dataset_samples", ["sample_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_model_dataset_samples_sample_id", table_name="model_dataset_samples")
    op.drop_table("model_dataset_samples")
