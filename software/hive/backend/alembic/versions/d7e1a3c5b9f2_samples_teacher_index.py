"""An index for the samples list's default view: teacher-checked samples, newest first

Revision ID: d7e1a3c5b9f2
Revises: c548fb8d227c
Create Date: 2026-10-12

GET /api/samples shows teacher-checked samples (extra_metadata.teacher_rerun set)
by default, newest first. Without this index Postgres walks every sample
backwards by upload time and reads each row to test the filter: when the newest
tens of thousands of samples have no teacher pass yet, one page read them all
and ran into the statement timeout. Built CONCURRENTLY, so machine uploads keep
writing samples while it builds. The predicate is written as the filter writes
it (sample_filters.apply_annotated_filter, visible_samples) so the planner
matches it.
"""

from alembic import op

revision = "d7e1a3c5b9f2"
down_revision = "c548fb8d227c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_samples_teacher_uploaded_at "
            "ON samples (uploaded_at DESC, id DESC) "
            "WHERE archived_at IS NULL AND (extra_metadata -> 'teacher_rerun') IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_samples_teacher_uploaded_at")
