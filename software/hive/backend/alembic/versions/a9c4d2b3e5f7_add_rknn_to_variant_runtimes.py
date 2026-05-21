"""add rknn to variant runtime CHECK

Revision ID: a9c4d2b3e5f7
Revises: f8b9c0d1e2f3
Create Date: 2026-05-17

Adds 'rknn' to the allowed runtime values for detection_model_variants.runtime.
Postgres can't ALTER a CHECK constraint in place — drop and re-add.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "a9c4d2b3e5f7"
down_revision: Union[str, None] = "f8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CONSTRAINT_NAME = "ck_detection_model_variants_runtime"
TABLE_NAME = "detection_model_variants"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        "runtime IN ('onnx', 'ncnn', 'hailo', 'pytorch', 'rknn')",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="check")
    op.create_check_constraint(
        CONSTRAINT_NAME,
        TABLE_NAME,
        "runtime IN ('onnx', 'ncnn', 'hailo', 'pytorch')",
    )
