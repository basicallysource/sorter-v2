"""Training runs from sorters, and their colour labels

Revision ID: f6a8c0e2b4d7
Revises: e5c7a9b1d3f6
Create Date: 2026-10-13

A sorter in training mode labels every piece it sees during a run with what
the run was for: in a colour run, one of the colours the operator fed.

  * machine_training_runs: one row per (machine, run), synced from the machine
    (data type training_runs), with its segments (the colours fed, changed
    without ending the run) and the piece, labelled and excluded counts Hive
    keeps on it (services/training_runs.py).
  * machine_pieces.training_run_uuid / training_segment_uuid / training_color_id /
    training_label_source / training_excluded / training_updated_at, synced
    with the piece's record. Added without rewriting the table (nullable, or a
    constant default), and ix_machine_pieces_training_run (a run's pieces, only
    the pieces in a run) built CONCURRENTLY.
  * labeling_queue.has_training_label, kept by the queue worker and the sync
    endpoints, and two partial indexes, the arrival walks over only those
    pieces, so the piece grid treats them as colour-labelled with an index walk.
  * labeling_queue_counts.training_labeled: per machine, the pieces its runs
    labelled, summed by the queue worker for the labeling page's stats.
  * piece_color_verdicts gets a third source, training_run: a training colour
    that counts (set, the piece not excluded, its run not excluded), with the
    run's uuid where a verdict's author goes. verdict_by becomes text, since
    a run's id is the machine's own string, not a Hive uuid.

Indexes on existing tables are built CONCURRENTLY: the previous release still
serves while this runs, and its workers keep writing to both tables.
"""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "f6a8c0e2b4d7"
down_revision = "e5c7a9b1d3f6"
branch_labels = None
depends_on = None


PIECE_COLOR_VERDICTS_SQL = """
CREATE VIEW piece_color_verdicts AS
SELECT 'machine' AS source,
       CAST(m.owner_id AS VARCHAR) AS verdict_by,
       p.machine_id AS machine_id,
       p.piece_uuid AS piece_uuid,
       p.color_corrected_id AS color_id,
       (1 = 0) AS cant_tell,
       p.correction_updated_at AS verdict_at,
       p.color_id AS machine_color_id,
       p.color_provider AS machine_color_provider,
       p.color_confidence AS machine_color_confidence
FROM machine_pieces p
JOIN machines m ON m.id = p.machine_id
WHERE p.color_corrected_id IS NOT NULL
UNION ALL
SELECT 'hive' AS source,
       CAST(l.labeler_id AS VARCHAR) AS verdict_by,
       l.machine_id AS machine_id,
       l.piece_uuid AS piece_uuid,
       CAST(l.color_id AS VARCHAR) AS color_id,
       l.cant_tell AS cant_tell,
       l.updated_at AS verdict_at,
       p.color_id AS machine_color_id,
       p.color_provider AS machine_color_provider,
       p.color_confidence AS machine_color_confidence
FROM piece_color_labels l
LEFT JOIN machine_pieces p ON p.machine_id = l.machine_id AND p.piece_uuid = l.piece_uuid
UNION ALL
SELECT 'training_run' AS source,
       p.training_run_uuid AS verdict_by,
       p.machine_id AS machine_id,
       p.piece_uuid AS piece_uuid,
       p.training_color_id AS color_id,
       (1 = 0) AS cant_tell,
       COALESCE(p.training_updated_at, p.seen_at, p.created_at) AS verdict_at,
       p.color_id AS machine_color_id,
       p.color_provider AS machine_color_provider,
       p.color_confidence AS machine_color_confidence
FROM machine_pieces p
LEFT JOIN machine_training_runs r ON r.machine_id = p.machine_id AND r.run_uuid = p.training_run_uuid
WHERE p.training_run_uuid IS NOT NULL
  AND p.training_color_id IS NOT NULL
  AND NOT p.training_excluded
  AND (r.excluded IS NULL OR NOT r.excluded)
"""

INDEXES = {
    "ix_machine_pieces_training_run": (
        "machine_pieces",
        "(machine_id, training_run_uuid) WHERE training_run_uuid IS NOT NULL",
    ),
    # Written as the queue's query writes it (has_training_label IS true), so
    # the planner can match the predicate.
    "ix_labeling_queue_training_arrival": (
        "labeling_queue",
        "(arrival_at, machine_id, piece_uuid) WHERE has_training_label IS true",
    ),
    "ix_labeling_queue_training_machine_arrival": (
        "labeling_queue",
        "(machine_id, arrival_at, piece_uuid) WHERE has_training_label IS true",
    ),
}


def _create_concurrently(table: str, name: str, definition: str) -> None:
    """CREATE INDEX CONCURRENTLY IF NOT EXISTS, after dropping an invalid one
    a failed build left behind. Call inside an autocommit block."""
    invalid = op.get_bind().execute(
        text(
            "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name"
        ),
        {"name": name},
    ).scalar()
    if invalid:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} {definition}")


def _previous_color_verdicts_sql() -> str:
    path = Path(__file__).with_name("8a9445c627d2_machine_predictions_and_verdicts.py")
    spec = importlib.util.spec_from_file_location("verdicts_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PIECE_COLOR_VERDICTS_SQL


def upgrade() -> None:
    op.create_table(
        "machine_training_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "machine_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("machines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("run_uuid", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("color_ids", postgresql.JSONB(), nullable=False),
        sa.Column("segments", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("piece_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("labeled_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("excluded_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("machine_id", "run_uuid", name="uq_machine_training_runs_machine_run"),
    )
    op.create_index(
        "ix_machine_training_runs_machine_started", "machine_training_runs", ["machine_id", "started_at", "id"]
    )
    op.add_column("machine_pieces", sa.Column("training_run_uuid", sa.String(), nullable=True))
    op.add_column("machine_pieces", sa.Column("training_segment_uuid", sa.String(), nullable=True))
    op.add_column("machine_pieces", sa.Column("training_color_id", sa.String(), nullable=True))
    op.add_column("machine_pieces", sa.Column("training_label_source", sa.String(), nullable=True))
    op.add_column(
        "machine_pieces", sa.Column("training_excluded", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("machine_pieces", sa.Column("training_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "labeling_queue", sa.Column("has_training_label", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "labeling_queue_counts", sa.Column("training_labeled", sa.BigInteger(), nullable=False, server_default="0")
    )
    # verdict_by changes type, so the view is made again rather than replaced.
    op.execute("DROP VIEW IF EXISTS piece_color_verdicts")
    op.execute(PIECE_COLOR_VERDICTS_SQL)

    with op.get_context().autocommit_block():
        for name, (table, definition) in INDEXES.items():
            _create_concurrently(table, name, definition)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name in INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.execute("DROP VIEW IF EXISTS piece_color_verdicts")
    op.execute(_previous_color_verdicts_sql())
    op.drop_column("labeling_queue_counts", "training_labeled")
    op.drop_column("labeling_queue", "has_training_label")
    op.drop_column("machine_pieces", "training_updated_at")
    op.drop_column("machine_pieces", "training_excluded")
    op.drop_column("machine_pieces", "training_label_source")
    op.drop_column("machine_pieces", "training_color_id")
    op.drop_column("machine_pieces", "training_segment_uuid")
    op.drop_column("machine_pieces", "training_run_uuid")
    op.drop_index("ix_machine_training_runs_machine_started", table_name="machine_training_runs")
    op.drop_table("machine_training_runs")
