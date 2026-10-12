"""Which pieces had the colour reference palette in view, read by index

Revision ID: 5a7137bafb06
Revises: 3bce507e67fc

The piece labeling page shows, for each piece, whether a classification frame
of its machine near the piece's arrival had the colour reference palette in
view, filters on it, and shows that frame and its swatches (services/piece_palette.py).

  * sample_swatch_runs.machine_id / frame_at: the sample's machine and when its
    frame was taken (captured_at, else uploaded_at), filled in here for the
    runs there are; new runs carry them from the job. With
    ix_sample_swatch_runs_palette_frames (model, machine, frame time; palette
    calls only), "this machine's palette frames near this time" is one index
    range. Nullable, so the previous release can still store runs during the
    deploy; the labeling-queue worker fills in any it left without them.
  * ix_sample_swatch_runs_created_at: the runs stored since the worker's last pass.
  * labeling_queue.has_palette, kept by the worker, and two partial indexes
    (the arrival walks over only those pieces), so the grid's palette filter is
    an index walk. labeling_queue_state.palette_model_sha256: the swatch model
    has_palette follows; while it is null the worker's next pass re-evaluates
    every piece, which fills has_palette after this deploy.

Indexes on existing tables are built CONCURRENTLY: the previous release still
serves while this runs, and its workers keep writing to both tables.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "5a7137bafb06"
down_revision = "3bce507e67fc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sample_swatch_runs", sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("sample_swatch_runs", sa.Column("frame_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE sample_swatch_runs AS r "
        "SET machine_id = s.machine_id, frame_at = coalesce(s.captured_at, s.uploaded_at) "
        "FROM samples AS s WHERE s.id = r.sample_id AND r.frame_at IS NULL"
    )
    op.add_column(
        "labeling_queue", sa.Column("has_palette", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("labeling_queue_state", sa.Column("palette_model_sha256", sa.String(64), nullable=True))

    with op.get_context().autocommit_block():
        # Written as the queries write them (palette_present = true, has_palette
        # IS true), so the planner can match the predicates.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sample_swatch_runs_palette_frames "
            "ON sample_swatch_runs (model_sha256, machine_id, frame_at) WHERE palette_present = true"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sample_swatch_runs_created_at "
            "ON sample_swatch_runs (created_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_labeling_queue_palette_arrival "
            "ON labeling_queue (arrival_at, machine_id, piece_uuid) WHERE has_palette IS true"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_labeling_queue_palette_machine_arrival "
            "ON labeling_queue (machine_id, arrival_at, piece_uuid) WHERE has_palette IS true"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_labeling_queue_palette_machine_arrival")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_labeling_queue_palette_arrival")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_sample_swatch_runs_created_at")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_sample_swatch_runs_palette_frames")
    op.drop_column("labeling_queue_state", "palette_model_sha256")
    op.drop_column("labeling_queue", "has_palette")
    op.drop_column("sample_swatch_runs", "frame_at")
    op.drop_column("sample_swatch_runs", "machine_id")
