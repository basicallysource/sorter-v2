"""add phash to samples

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-05-25

8×8 perceptual hash stored as a signed 64-bit int. Used for "find similar"
on the sample detail page — Hamming distance between two pHashes ≤ ~12
usually means visually near-duplicate (same content, exposure / crop
variation only).

A regular b-tree index doesn't speed up Hamming-distance scans but does
let us cheaply skip rows where phash IS NULL and partition by machine
when needed. The distance computation itself runs in SQL via
bit_count(phash # :target).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("samples", sa.Column("phash", sa.BigInteger(), nullable=True))
    op.create_index(
        "ix_samples_phash",
        "samples",
        ["phash"],
        postgresql_where=sa.text("phash IS NOT NULL"),
        sqlite_where=sa.text("phash IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_samples_phash", table_name="samples")
    op.drop_column("samples", "phash")
