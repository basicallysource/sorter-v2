"""add purpose to detection_models

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
Create Date: 2026-07-19

The models table was built for object detectors, but a published model artifact
is the same shape whatever the model does: slug+version, an owner, per-runtime
files with checksums, and a download route machines can pull from. `purpose`
splits the table by what the model is FOR so link matchers (encoder+head pair
that scores which upstream C-channel crop is the piece we just classified) can
reuse all of it instead of growing a parallel registry.

server_default 'detection' backfills every existing row, so nothing that
queries this table without a purpose filter changes behaviour.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2d4f6a8c0e1"
down_revision: Union[str, None] = "a1c3e5f7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "detection_models",
        sa.Column(
            "purpose",
            sa.String(),
            nullable=False,
            server_default="detection",
        ),
    )
    op.create_index("ix_detection_models_purpose", "detection_models", ["purpose"])
    op.create_check_constraint(
        "ck_detection_models_purpose",
        "detection_models",
        "purpose IN ('detection', 'piece_link')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_detection_models_purpose", "detection_models", type_="check")
    op.drop_index("ix_detection_models_purpose", table_name="detection_models")
    op.drop_column("detection_models", "purpose")
