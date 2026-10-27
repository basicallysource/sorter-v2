import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from app.models import JSON_VARIANT, Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


JOB_STATUSES = ("queued", "running", "done", "failed")
# A job in one of these still has work ahead of it; at most one per
# (kind, subject) may be in them at a time.
PENDING_STATUSES = ("queued", "running")
PENDING_SQL = "status IN ('queued', 'running')"


class Job(Base):
    """One piece of background work: what to do (``kind``), what to do it to
    (``subject``, e.g. a sample id), and how it went. Run by
    ``app.services.job_queue``; see ``agent-docs/jobs.md``.

    A worker claims a due ``queued`` row with ``FOR UPDATE SKIP LOCKED``, marks
    it ``running`` with a lease (``locked_by``, ``locked_until``) and runs the
    handler registered for its kind. A worker that dies leaves its lease to
    run out, and the row is queued again (or failed, out of attempts). A
    failure is retried after ``run_after`` with a backoff until
    ``max_attempts``. ``done`` and ``failed`` rows are deleted after a while.
    """

    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(String(64), nullable=False)
    subject = Column(String(128), nullable=True)
    payload = Column(JSON_VARIANT, nullable=True)
    status = Column(String(16), nullable=False, default="queued")
    # Higher first. Work for something that just arrived beats a backfill.
    priority = Column(Integer, nullable=False, default=0)
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=3)
    # Not claimed before this: when it was queued, or when a retry is due.
    run_after = Column(DateTime(timezone=True), nullable=False, default=_now)
    locked_by = Column(String(128), nullable=True)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    result = Column(JSON_VARIANT, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_jobs_status",
        ),
        # Enqueue is deduplicated by this index: a second job for the same
        # subject is not inserted while the first is still queued or running.
        Index(
            "uq_jobs_pending_kind_subject",
            "kind",
            "subject",
            unique=True,
            postgresql_where=text(PENDING_SQL),
            sqlite_where=text(PENDING_SQL),
        ),
        # The claim: due queued rows, highest priority first.
        Index(
            "ix_jobs_queued_priority",
            priority.desc(),
            run_after,
            postgresql_where=text("status = 'queued'"),
            sqlite_where=text("status = 'queued'"),
        ),
        # Lease expiry, pruning and the admin counts.
        Index("ix_jobs_status_finished_at", "status", "finished_at"),
    )
