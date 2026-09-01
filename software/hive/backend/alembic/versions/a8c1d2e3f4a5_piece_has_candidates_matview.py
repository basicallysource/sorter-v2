"""piece_has_candidates materialized view

Revision ID: a8c1d2e3f4a5
Revises: a7b8c9d0e1f2
Create Date: 2026-07-16 18:00:00.000000

The labeling grid's "has same-piece candidates" flag was a correlated EXISTS
over machine_channel_crops per piece. Postgres planned the WHERE-clause copy as
a hash semi join on machine_id alone (only ~a dozen distinct machines), leaving
the ts-window as a join filter — every piece scanned its machine's entire crop
set, blowing past 100s (and, with parallel workers, the container's /dev/shm).

Precompute the set instead: pieces are hidden from the grid until 15 minutes
old (_old_enough), so "does this piece have candidate crops" is effectively
static by the time anyone can see it. A materialized view holds the (machine,
piece) keys, refreshed every few minutes by CandidateMatviewWorker; the grid
LEFT JOINs it (a cheap hash join on the real composite key).

The window constants mirror channel_crop_lookup_params.DEFAULT_PARAMS
(lookback_window_s = 60, fwd_slop_s = 1.5) — the crop-side condition
  c.ts BETWEEN arrival - 60s AND arrival + 1.5s
is inverted here to drive the build from the crops side:
  arrival BETWEEN c.ts - 1.5s AND c.ts + 60s
which the expression index on (machine_id, coalesce(seen_at, recorded_at))
makes an index probe per crop instead of a scan per piece.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a8c1d2e3f4a5"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_machine_pieces_machine_arrival "
        "ON machine_pieces (machine_id, (coalesce(seen_at, recorded_at)))"
    )
    op.execute(
        """
        CREATE MATERIALIZED VIEW piece_has_candidates AS
        SELECT DISTINCT p.machine_id, p.piece_uuid
        FROM machine_channel_crops c
        JOIN machine_pieces p
          ON p.machine_id = c.machine_id
         AND coalesce(p.seen_at, p.recorded_at) >= c.ts - interval '1.5 seconds'
         AND coalesce(p.seen_at, p.recorded_at) <= c.ts + interval '60 seconds'
        WHERE c.ts IS NOT NULL
        """
    )
    # Unique index is required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
    op.execute(
        "CREATE UNIQUE INDEX uq_piece_has_candidates_machine_piece "
        "ON piece_has_candidates (machine_id, piece_uuid)"
    )


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS piece_has_candidates")
    op.drop_index("ix_machine_pieces_machine_arrival", table_name="machine_pieces")
