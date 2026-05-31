"""merge rknn + teacher heads

Revision ID: e3f4a5b6c7d8
Revises: a9c4d2b3e5f7, d2e3f4a5b6c7
Create Date: 2026-05-21

Joins the upstream "add rknn runtime" branch (a9c4d2b3e5f7) with the
teacher-backfill chain (d2e3f4a5b6c7) — both forked off f8b9c0d1e2f3
independently. No-op on both columns; just unifies the head pointer so
``alembic upgrade head`` is unambiguous.
"""

from __future__ import annotations

from typing import Sequence, Union


revision: str = "e3f4a5b6c7d8"
down_revision: Union[str, Sequence[str], None] = ("a9c4d2b3e5f7", "d2e3f4a5b6c7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
