"""fix piece_has_candidates: isolate c.ts so the index is usable

Revision ID: d4f6a8b0c2e1
Revises: c9e1f3a5b7d9
Create Date: 2026-08-12 17:10:00.000000

The a8c1d2e3f4a5 matview was created to kill a correlated EXISTS that Postgres
planned as a machine_id-only semi join, scanning each machine's entire crop set
per piece. The matview's own defining query then reproduced that exact plan,
because the crop-side condition was written with `c.ts` buried under interval
arithmetic:

    coalesce(p.seen_at, p.recorded_at) >= c.ts - interval '1.5 seconds'
    coalesce(p.seen_at, p.recorded_at) <= c.ts + interval '60 seconds'

An index on machine_channel_crops(machine_id, ts) cannot serve that. `c.ts` is
not a bare column on one side of the operator, so the planner can only use the
`machine_id` equality as an index condition and applies the time window as a
Filter — scanning ~24,800 crop rows per piece and discarding almost all of them.

Measured on prod 2026-08-12: REFRESH MATERIALIZED VIEW CONCURRENTLY had been
running for 6h20m and had never completed. CandidateMatviewWorker reloops it
every 300s, so postgres ground this one query continuously; it was the whole of
the box's ~180% CPU and its sustained load average of 3.1 on 2 cores.

The fix moves the interval arithmetic to the piece side, which is algebraically
identical and isolates `c.ts`:

    c.ts <= coalesce(p.seen_at, p.recorded_at) + interval '1.5 seconds'
    c.ts >= coalesce(p.seen_at, p.recorded_at) - interval '60 seconds'

Now ix_machine_channel_crops_machine_ts serves the whole predicate as an Index
Cond and the probe is an Index Only Scan returning ~23 rows in 0.06ms. Measured
end to end with EXPLAIN (ANALYZE) on prod: 6h20m+ -> 17.0s, and the per-probe
inner cost drops 6,142 -> 621.

The view's semantics are unchanged, so this is a pure drop-and-recreate. It runs
in the migration's transaction, so readers keep seeing the old view until commit
rather than observing a missing relation; the tradeoff is that CREATE populates
the view before committing, so the deploy holds the lock for that ~17s.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d4f6a8b0c2e1"
down_revision: Union[str, None] = "c9e1f3a5b7d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The window constants still mirror channel_crop_lookup_params.DEFAULT_PARAMS
# (lookback_window_s = 60, fwd_slop_s = 1.5). Crop-side form, for reference:
#   c.ts BETWEEN arrival - 60s AND arrival + 1.5s
_FIXED = """
    CREATE MATERIALIZED VIEW piece_has_candidates AS
    SELECT DISTINCT p.machine_id, p.piece_uuid
    FROM machine_channel_crops c
    JOIN machine_pieces p
      ON p.machine_id = c.machine_id
     AND c.ts <= coalesce(p.seen_at, p.recorded_at) + interval '1.5 seconds'
     AND c.ts >= coalesce(p.seen_at, p.recorded_at) - interval '60 seconds'
    WHERE c.ts IS NOT NULL
"""

_ORIGINAL = """
    CREATE MATERIALIZED VIEW piece_has_candidates AS
    SELECT DISTINCT p.machine_id, p.piece_uuid
    FROM machine_channel_crops c
    JOIN machine_pieces p
      ON p.machine_id = c.machine_id
     AND coalesce(p.seen_at, p.recorded_at) >= c.ts - interval '1.5 seconds'
     AND coalesce(p.seen_at, p.recorded_at) <= c.ts + interval '60 seconds'
    WHERE c.ts IS NOT NULL
"""

# REFRESH ... CONCURRENTLY requires a unique index, so it is recreated with the
# view rather than left behind by the DROP.
_UNIQUE_INDEX = (
    "CREATE UNIQUE INDEX uq_piece_has_candidates_machine_piece "
    "ON piece_has_candidates (machine_id, piece_uuid)"
)


def upgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS piece_has_candidates")
    op.execute(_FIXED)
    op.execute(_UNIQUE_INDEX)


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS piece_has_candidates")
    op.execute(_ORIGINAL)
    op.execute(_UNIQUE_INDEX)
