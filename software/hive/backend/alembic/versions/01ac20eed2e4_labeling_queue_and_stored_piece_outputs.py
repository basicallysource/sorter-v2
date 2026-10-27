"""Labeling queue, stored per-piece model outputs, cached sample review counts

Revision ID: 01ac20eed2e4
Revises: 8a9445c627d2

Every slow labeling request aggregated or sorted the fleet's whole history on
each call. This adds what lets them read a few rows instead:

  * labeling_queue: one narrow row per labelable piece, kept by the
    labeling-queue worker, with indexes the grid walks in its sort orders.
    labeling_queue_counts holds each machine's labelable count;
    labeling_queue_state the worker's progress. The tables start empty: the
    worker's first pass after deploy evaluates every piece in small batches and
    fills them (a couple of minutes; the grid shows what is done so far).
  * piece_link_scores and piece_color_guesses: the link model's scores and the
    colour guesses for a piece, kept per model sha256 so a piece is scored once.
  * machine_stats_cache gains the per-machine sample counts for each review
    state, so the dashboard sums rows instead of counting the samples table.
  * BRIN indexes on created_at for machine_piece_images and
    machine_channel_crops (append-only, so a BRIN index of a few hundred KB
    finds the rows of the last few minutes), read by the worker.
  * A partial index for the reviewer access window (the newest live pieces),
    which every reviewer request computed with a full sort of machine_pieces.
  * machine_pieces vacuums at 2% dead rows instead of 20%.

piece_has_candidates (the materialized view this replaces) is left in place,
unrefreshed, so a rollback to the previous release still finds it. Drop it, and
ix_machine_pieces_machine_arrival which only fed it, in a later migration.

Indexes on existing tables are built CONCURRENTLY: this runs while the previous
release still serves, and machines keep syncing into these tables.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "01ac20eed2e4"
down_revision = "8a9445c627d2"
branch_labels = None
depends_on = None

_SAMPLE_STATE_COLUMNS = ("unreviewed_samples", "in_review_samples", "rejected_samples", "conflict_samples")


def upgrade() -> None:
    op.create_table(
        "labeling_queue",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("piece_uuid", sa.String(), nullable=False),
        sa.Column("arrival_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("has_candidates", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("unidentified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("color_id", sa.String(), nullable=True),
        sa.Column("color_confidence", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("machine_id", "piece_uuid"),
        sa.ForeignKeyConstraint(
            ["machine_id", "piece_uuid"],
            ["machine_pieces.machine_id", "machine_pieces.piece_uuid"],
            ondelete="CASCADE",
            name="fk_labeling_queue_piece",
        ),
    )
    op.create_index("ix_labeling_queue_arrival", "labeling_queue", ["arrival_at", "machine_id", "piece_uuid"])
    op.create_index("ix_labeling_queue_machine_arrival", "labeling_queue", ["machine_id", "arrival_at", "piece_uuid"])
    op.execute(
        "CREATE INDEX ix_labeling_queue_color_confidence ON labeling_queue "
        "(color_confidence, arrival_at DESC, machine_id DESC, piece_uuid DESC) "
        "WHERE color_confidence IS NOT NULL"
    )

    op.create_table(
        "labeling_queue_counts",
        sa.Column("machine_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("machines.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("labelable", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "labeling_queue_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("last_pass_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
    )

    for name, extra in (
        (
            "piece_link_scores",
            [
                sa.Column("model_name", sa.String(), nullable=True),
                sa.Column("scores", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            ],
        ),
        (
            "piece_color_guesses",
            [
                sa.Column("seqs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
                sa.Column("pixel_guess", postgresql.JSONB(), nullable=True),
                sa.Column("model_prediction", postgresql.JSONB(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            ],
        ),
    ):
        op.create_table(
            name,
            sa.Column("machine_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("piece_uuid", sa.String(), nullable=False),
            sa.Column("model_sha256", sa.String(64), nullable=False),
            *extra,
            sa.PrimaryKeyConstraint("machine_id", "piece_uuid", "model_sha256"),
            sa.ForeignKeyConstraint(
                ["machine_id", "piece_uuid"],
                ["machine_pieces.machine_id", "machine_pieces.piece_uuid"],
                ondelete="CASCADE",
                name=f"fk_{name}_piece",
            ),
        )

    # server_default so the previous release, which does not know these
    # columns, can still insert cache rows during the deploy and on rollback.
    for column in _SAMPLE_STATE_COLUMNS:
        op.add_column(
            "machine_stats_cache",
            sa.Column(column, sa.Integer(), nullable=False, server_default=sa.text("0")),
        )

    op.execute("ALTER TABLE machine_pieces SET (autovacuum_vacuum_scale_factor = 0.02)")

    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_machine_piece_images_created_brin "
            "ON machine_piece_images USING brin (created_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_machine_channel_crops_created_brin "
            "ON machine_channel_crops USING brin (created_at)"
        )
        # Written as the access window's query writes it (dead IS false), so the
        # planner can match the predicate.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_machine_pieces_live_created "
            "ON machine_pieces (created_at, id) WHERE dead IS false"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_machine_pieces_live_created")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_machine_channel_crops_created_brin")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_machine_piece_images_created_brin")
    op.execute("ALTER TABLE machine_pieces RESET (autovacuum_vacuum_scale_factor)")
    for column in _SAMPLE_STATE_COLUMNS:
        op.drop_column("machine_stats_cache", column)
    op.drop_table("piece_color_guesses")
    op.drop_table("piece_link_scores")
    op.drop_table("labeling_queue_state")
    op.drop_table("labeling_queue_counts")
    op.drop_table("labeling_queue")
