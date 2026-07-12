"""add experimental flag to detection_models

Revision ID: c4d5e6f7a8b9
Revises: b1c2d3e4f5a6
Create Date: 2026-06-08

First-class flag so a model can be marked experimental. Experimental models are
hidden from the default Browse on both Hive and the sorters (opt back in with
?include_experimental=true) so operators don't install a test model by accident.
server_default false backfills existing rows.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "detection_models",
        sa.Column(
            "experimental",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_detection_models_experimental",
        "detection_models",
        ["experimental"],
    )


def downgrade() -> None:
    op.drop_index("ix_detection_models_experimental", table_name="detection_models")
    op.drop_column("detection_models", "experimental")
