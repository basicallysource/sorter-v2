"""Stats the worker keeps current instead of rescanning the fleet

Revision ID: 3c5e7a9b1d24
Revises: f7b9d1c3e5a7
Create Date: 2026-11-17

The stats worker answered every piece number with grouped scans over all of
machine_pieces (2.1 million rows) and counted all of machine_channel_crops
(54 million) each pass; on 2026-11-16 those ran past the 60 s statement limit
on every pass and the stats froze. This keeps the answers instead:

  * machine_piece_days, machine_piece_day_keys, machine_piece_keys: partial
    answers per machine and UTC day, and per machine (services/piece_days.py).
  * machine_piece_day_marks and triggers on machine_pieces: the machine-days
    whose pieces changed, for the worker to rebuild.
  * machine_channel_crop_deltas and triggers on machine_channel_crops: crops
    added and removed per statement, for the worker to add to the count.
  * machine_stats_cache.incremental_since: when the worker counted a machine
    in full, which it does once per machine after this runs.
  * Narrow indexes on samples, so the per-machine sample counts and the
    weekly diversity rows read an index rather than the wide table.

And fixes what made the labeling queue worker read gigabytes a pass: its BRIN
indexes on created_at summarized new rows only when autovacuum vacuumed the
table, which an insert-only table of this size does about weekly, so a query
for the last few minutes read every row since. autosummarize summarizes each
range as it fills.

Drops what nothing reads: ix_machine_channel_crops_machine_local_id (the same
columns as the unique constraint's index, 4 GB), ix_machine_channel_crops_
machine_channel_ts (3 GB, unused), and the piece_has_candidates matview and
ix_machine_pieces_machine_arrival, which only fed it (left in place by
01ac20eed2e4 for a rollback that is long past).

Indexes on existing tables are built and dropped CONCURRENTLY: this runs while
the previous release still serves and machines keep syncing.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "3c5e7a9b1d24"
down_revision = "f7b9d1c3e5a7"
branch_labels = None
depends_on = None

# The same text as app/models/machine_piece_day.py and machine_channel_crop.py
# (tests/test_piece_days.py checks).
PIECE_MARK_FUNCTION = """
CREATE OR REPLACE FUNCTION machine_piece_days_mark() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO machine_piece_day_marks (machine_id, day)
        SELECT DISTINCT n.machine_id, COALESCE(((n.seen_at) AT TIME ZONE 'UTC')::date, DATE '0001-01-01') FROM new_rows n;
    ELSIF TG_OP = 'UPDATE' THEN
        INSERT INTO machine_piece_day_marks (machine_id, day)
        SELECT n.machine_id, COALESCE(((n.seen_at) AT TIME ZONE 'UTC')::date, DATE '0001-01-01')
          FROM new_rows n JOIN old_rows o ON o.id = n.id WHERE (n.machine_id, n.seen_at, n.classification_status, n.part_id, n.part_name, n.color_id, n.color_name, n.bin_x) IS DISTINCT FROM (o.machine_id, o.seen_at, o.classification_status, o.part_id, o.part_name, o.color_id, o.color_name, o.bin_x)
        UNION
        SELECT o.machine_id, COALESCE(((o.seen_at) AT TIME ZONE 'UTC')::date, DATE '0001-01-01')
          FROM new_rows n JOIN old_rows o ON o.id = n.id WHERE (n.machine_id, n.seen_at, n.classification_status, n.part_id, n.part_name, n.color_id, n.color_name, n.bin_x) IS DISTINCT FROM (o.machine_id, o.seen_at, o.classification_status, o.part_id, o.part_name, o.color_id, o.color_name, o.bin_x);
    ELSE
        INSERT INTO machine_piece_day_marks (machine_id, day)
        SELECT DISTINCT o.machine_id, COALESCE(((o.seen_at) AT TIME ZONE 'UTC')::date, DATE '0001-01-01') FROM old_rows o;
    END IF;
    RETURN NULL;
END
$$
"""
PIECE_MARK_TRIGGERS = (
    'CREATE OR REPLACE TRIGGER machine_pieces_mark_days_insert AFTER INSERT ON machine_pieces REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_piece_days_mark()',
    'CREATE OR REPLACE TRIGGER machine_pieces_mark_days_update AFTER UPDATE ON machine_pieces REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_piece_days_mark()',
    'CREATE OR REPLACE TRIGGER machine_pieces_mark_days_delete AFTER DELETE ON machine_pieces REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_piece_days_mark()',
)
CROP_DELTA_FUNCTION = """
CREATE OR REPLACE FUNCTION machine_channel_crops_delta() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO machine_channel_crop_deltas (machine_id, n)
        SELECT machine_id, count(*) FROM new_rows GROUP BY machine_id;
    ELSE
        INSERT INTO machine_channel_crop_deltas (machine_id, n)
        SELECT machine_id, -count(*) FROM old_rows GROUP BY machine_id;
    END IF;
    RETURN NULL;
END
$$
"""
CROP_DELTA_TRIGGERS = (
    'CREATE OR REPLACE TRIGGER machine_channel_crops_delta_insert AFTER INSERT ON machine_channel_crops REFERENCING NEW TABLE AS new_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_channel_crops_delta()',
    'CREATE OR REPLACE TRIGGER machine_channel_crops_delta_delete AFTER DELETE ON machine_channel_crops REFERENCING OLD TABLE AS old_rows FOR EACH STATEMENT EXECUTE FUNCTION machine_channel_crops_delta()',
)

_UUID = postgresql.UUID(as_uuid=True)


def _machine_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["machine_id"], ["machines.id"], ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "machine_piece_days",
        sa.Column("machine_id", _UUID, nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("pieces", sa.BigInteger(), nullable=False),
        sa.Column("distributed", sa.BigInteger(), nullable=False),
        sa.Column("classified", sa.BigInteger(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_within", sa.Numeric(), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("machine_id", "day"),
        _machine_fk(),
    )
    op.create_table(
        "machine_piece_day_keys",
        sa.Column("machine_id", _UUID, nullable=False),
        sa.Column("kind", sa.String(2), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("n", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("first_classified", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("machine_id", "kind", "key", "day"),
        _machine_fk(),
    )
    op.create_index("ix_machine_piece_day_keys_machine_day", "machine_piece_day_keys", ["machine_id", "day"])
    op.create_table(
        "machine_piece_keys",
        sa.Column("machine_id", _UUID, nullable=False),
        sa.Column("kind", sa.String(2), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("n", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("first_classified", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("machine_id", "kind", "key"),
        _machine_fk(),
    )
    op.create_index("ix_machine_piece_keys_kind_first", "machine_piece_keys", ["kind", "first_classified"])
    op.create_table(
        "machine_piece_day_marks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("machine_id", _UUID, nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_machine_piece_day_marks_machine", "machine_piece_day_marks", ["machine_id"])
    op.create_table(
        "machine_channel_crop_deltas",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("machine_id", _UUID, nullable=False),
        sa.Column("n", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.add_column("machine_stats_cache", sa.Column("incremental_since", sa.DateTime(timezone=True), nullable=True))

    op.execute("ALTER INDEX ix_machine_channel_crops_created_brin SET (autosummarize = on)")
    op.execute("ALTER INDEX ix_machine_piece_images_created_brin SET (autosummarize = on)")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS piece_has_candidates")

    # Last before the commit: creating a trigger holds off writes to its table
    # until the transaction ends, and machines write to both all the time.
    op.execute(PIECE_MARK_FUNCTION)
    for statement in PIECE_MARK_TRIGGERS:
        op.execute(statement)
    op.execute(CROP_DELTA_FUNCTION)
    for statement in CROP_DELTA_TRIGGERS:
        op.execute(statement)

    with op.get_context().autocommit_block():
        # What accumulated before autosummarize, summarized once.
        op.execute("SELECT brin_summarize_new_values('ix_machine_piece_images_created_brin')")
        op.execute("SELECT brin_summarize_new_values('ix_machine_channel_crops_created_brin')")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_machine_channel_crops_machine_local_id")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_machine_channel_crops_machine_channel_ts")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_machine_pieces_machine_arrival")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_samples_machine_review_captured "
            "ON samples (machine_id, review_status, captured_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_samples_machine_role_active "
            "ON samples (machine_id, source_role) WHERE archived_at IS NULL AND source_role IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_samples_machine_reason_active "
            "ON samples (machine_id, capture_reason) "
            "INCLUDE (source_role, uploaded_at, detection_count, detection_score) "
            "WHERE archived_at IS NULL AND capture_reason IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_samples_machine_reason_active")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_samples_machine_role_active")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_samples_machine_review_captured")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_machine_pieces_machine_arrival "
            "ON machine_pieces (machine_id, COALESCE(seen_at, recorded_at))"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_machine_channel_crops_machine_channel_ts "
            "ON machine_channel_crops (machine_id, channel, ts)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_machine_channel_crops_machine_local_id "
            "ON machine_channel_crops (machine_id, local_id)"
        )
    op.execute("ALTER INDEX ix_machine_piece_images_created_brin RESET (autosummarize)")
    op.execute("ALTER INDEX ix_machine_channel_crops_created_brin RESET (autosummarize)")
    op.execute("DROP TRIGGER IF EXISTS machine_channel_crops_delta_delete ON machine_channel_crops")
    op.execute("DROP TRIGGER IF EXISTS machine_channel_crops_delta_insert ON machine_channel_crops")
    op.execute("DROP FUNCTION IF EXISTS machine_channel_crops_delta()")
    op.execute("DROP TRIGGER IF EXISTS machine_pieces_mark_days_delete ON machine_pieces")
    op.execute("DROP TRIGGER IF EXISTS machine_pieces_mark_days_update ON machine_pieces")
    op.execute("DROP TRIGGER IF EXISTS machine_pieces_mark_days_insert ON machine_pieces")
    op.execute("DROP FUNCTION IF EXISTS machine_piece_days_mark()")
    op.drop_column("machine_stats_cache", "incremental_since")
    op.drop_table("machine_channel_crop_deltas")
    op.drop_table("machine_piece_day_marks")
    op.drop_table("machine_piece_keys")
    op.drop_table("machine_piece_day_keys")
    op.drop_table("machine_piece_days")
