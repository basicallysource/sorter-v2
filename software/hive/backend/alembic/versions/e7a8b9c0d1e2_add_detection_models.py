"""add detection models

Revision ID: e7a8b9c0d1e2
Revises: d6f7a8b9c0d1
Create Date: 2026-04-16 20:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e7a8b9c0d1e2"
down_revision: Union[str, None] = "d6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "detection_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("model_family", sa.String(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("training_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", "version", name="uq_detection_models_slug_version"),
    )
    op.create_index("ix_detection_models_slug", "detection_models", ["slug"], unique=False)
    op.create_index("ix_detection_models_model_family", "detection_models", ["model_family"], unique=False)
    op.create_index("ix_detection_models_is_public", "detection_models", ["is_public"], unique=False)

    op.create_table(
        "detection_model_variants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("model_id", sa.UUID(), nullable=False),
        sa.Column("runtime", sa.String(), nullable=False),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("file_name", sa.String(), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("format_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "runtime IN ('onnx', 'ncnn', 'hailo', 'pytorch')",
            name="ck_detection_model_variants_runtime",
        ),
        sa.ForeignKeyConstraint(["model_id"], ["detection_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "runtime", name="uq_detection_model_variants_model_runtime"),
    )
    op.create_index(
        "ix_detection_model_variants_model_id",
        "detection_model_variants",
        ["model_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_detection_model_variants_model_id", table_name="detection_model_variants")
    op.drop_table("detection_model_variants")
    op.drop_index("ix_detection_models_is_public", table_name="detection_models")
    op.drop_index("ix_detection_models_model_family", table_name="detection_models")
    op.drop_index("ix_detection_models_slug", table_name="detection_models")
    op.drop_table("detection_models")
