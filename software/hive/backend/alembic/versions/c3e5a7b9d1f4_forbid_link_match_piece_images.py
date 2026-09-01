"""forbid link_match piece images

Revision ID: c3e5a7b9d1f4
Revises: c2e4a6b8d0f3
Create Date: 2026-07-20

machine_piece_images is ground truth: the labeling galleries and training
exports treat every row as "these pixels ARE the piece". The sorter's
piece-link matcher briefly attached its GUESSES (upstream C2/C3 crops it
scored as the same piece) to the same recognition set, which synced them into
this table and put crops of entirely different pieces into labeling galleries.

The sync endpoint now refuses source='link_match' outright, and the sorter
stores guesses in their own table that never syncs here. This constraint makes
the invariant structural: such a row cannot exist, whatever future code does.

NOT VALID so the constraint only gates new writes; the poison rows that
already landed are removed (with their storage files) by
scripts/purge_link_match_piece_images.py, which then VALIDATEs it.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "c3e5a7b9d1f4"
down_revision: Union[str, None] = "c2e4a6b8d0f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE machine_piece_images "
        "ADD CONSTRAINT ck_machine_piece_images_no_link_match "
        "CHECK (source IS NULL OR source <> 'link_match') NOT VALID"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE machine_piece_images "
        "DROP CONSTRAINT ck_machine_piece_images_no_link_match"
    )
