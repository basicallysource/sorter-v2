"""Indexes the samples list walks: one per filter that narrows it, newest first

Revision ID: a6e1c3b5d7f9
Revises: d7e1a3c5b9f2
Create Date: 2026-10-12

GET /api/samples walks one index newest first and looks at no more than a
window of samples on it (review_queue.sample_page). For that window to hold the
rows a filter shows, the index has to lead with the filter: a walk of every
sample with a filter on its source, say, read everything newer than the first
match, which for a camera the newer machines no longer have was the whole
recent history. So there is one index per filter that narrows the list (the
machine, the source, the capture reason, a review state), each with a twin for
the default view, the teacher-checked samples, because the newest samples are
rarely checked yet; and one for archived samples. ix_samples_uploaded_at gives
way to the same walk on (uploaded_at, id), which pages without a sort.

Similar samples (GET /api/samples/{id}/similar) compare one hash with every
sample's; ix_samples_phash_active holds the hash, id and machine of each active
sample, so that comparison reads this index alone rather than the table, and
replaces ix_samples_phash.

Built CONCURRENTLY outside a transaction, so machines keep uploading samples
while they build; the predicates are written as the queries write them so the
planner matches them. A build that failed half way leaves an invalid index,
which is dropped and built again.
"""

from alembic import op
from sqlalchemy import text

revision = "a6e1c3b5d7f9"
down_revision = "d7e1a3c5b9f2"
branch_labels = None
depends_on = None

_ACTIVE = "archived_at IS NULL"
_TEACHER = "archived_at IS NULL AND (extra_metadata -> 'teacher_rerun') IS NOT NULL"
_NEWEST = "uploaded_at DESC, id DESC"

INDEXES = {
    "ix_samples_uploaded_at_id": f"({_NEWEST})",
    "ix_samples_archived_uploaded_at": f"({_NEWEST}) WHERE archived_at IS NOT NULL",
    "ix_samples_machine_uploaded_at": f"(machine_id, {_NEWEST}) WHERE {_ACTIVE}",
    "ix_samples_machine_teacher_uploaded_at": f"(machine_id, {_NEWEST}) WHERE {_TEACHER}",
    "ix_samples_role_uploaded_at": f"(source_role, {_NEWEST}) WHERE {_ACTIVE}",
    "ix_samples_role_teacher_uploaded_at": f"(source_role, {_NEWEST}) WHERE {_TEACHER}",
    "ix_samples_reason_uploaded_at": f"(capture_reason, {_NEWEST}) WHERE {_ACTIVE}",
    "ix_samples_reason_teacher_uploaded_at": f"(capture_reason, {_NEWEST}) WHERE {_TEACHER}",
    "ix_samples_reviewed_uploaded_at": f"(review_status, {_NEWEST}) WHERE {_ACTIVE} AND review_status <> 'unreviewed'",
    # Similar samples compare a hash against every active sample's: this holds
    # what that needs, so it reads the index alone, never the table.
    "ix_samples_phash_active": f"(phash) INCLUDE (id, machine_id) WHERE phash IS NOT NULL AND {_ACTIVE}",
}
# Replaced by the ones above: ix_samples_uploaded_at by ix_samples_uploaded_at_id,
# ix_samples_phash by ix_samples_phash_active.
REPLACED = {
    "ix_samples_uploaded_at": "(uploaded_at)",
    "ix_samples_phash": "(phash) WHERE phash IS NOT NULL",
}


def create_concurrently(table: str, name: str, definition: str) -> None:
    """CREATE INDEX CONCURRENTLY IF NOT EXISTS, after dropping an invalid one
    a failed build left behind. Call inside an autocommit block."""
    bind = op.get_bind()
    invalid = bind.execute(
        text(
            "SELECT NOT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
            "WHERE c.relname = :name"
        ),
        {"name": name},
    ).scalar()
    if invalid:
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {table} {definition}")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, definition in INDEXES.items():
            create_concurrently("samples", name, definition)
        for name in REPLACED:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, definition in REPLACED.items():
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON samples {definition}")
        for name in reversed(list(INDEXES)):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
