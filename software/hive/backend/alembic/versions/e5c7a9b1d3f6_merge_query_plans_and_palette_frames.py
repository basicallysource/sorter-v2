"""merge the query-plan indexes with the worker state and palette frames

Revision ID: e5c7a9b1d3f6
Revises: 5a7137bafb06, c2e8a4f6b0d3
Create Date: 2026-10-12

Joins the chain that adds the samples list's indexes and the counts the stats
worker keeps (d7e1a3c5b9f2 .. c2e8a4f6b0d3) with the worker state and piece
palette frames chain (3bce507e67fc, 5a7137bafb06); both fork off c548fb8d227c.
d7e1a3c5b9f2 keeps its parent, so a database that already has it, and the
branch it came from, stay valid. No schema change: it only makes
``alembic upgrade head`` unambiguous.
"""

from __future__ import annotations

from typing import Sequence, Union

revision: str = "e5c7a9b1d3f6"
down_revision: Union[str, Sequence[str], None] = ("5a7137bafb06", "c2e8a4f6b0d3")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
