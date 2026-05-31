"""add codename to detection_models

Revision ID: b6c7d8e9f0a1
Revises: a5b6c7d8e9f0
Create Date: 2026-05-24

Human-friendly model identifier (Ubuntu-style: "Bronze", "Cherry", "Dune", …)
drawn from a curated LEGO-color word list. Indexed + unique so codenames stay
1:1 with model rows and queries can land on a model by codename alone.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b6c7d8e9f0a1"
down_revision: Union[str, None] = "a5b6c7d8e9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "detection_models",
        sa.Column("codename", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_detection_models_codename",
        "detection_models",
        ["codename"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_detection_models_codename", table_name="detection_models")
    op.drop_column("detection_models", "codename")
