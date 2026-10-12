"""A small, general job queue: the ``jobs`` table and the worker that runs it.

Background work that follows from something arriving (a sample to analyse, a
file to index) goes here instead of growing another worker thread of its own.
A kind of work is a handler registered under a name:

    def handle(job: JobContext) -> dict | None: ...
    register_handler("my_kind", handle, max_attempts=3, lease_s=300)

    enqueue(db, "my_kind", subject=str(sample.id))   # False if already pending

How it behaves (``agent-docs/jobs.md`` has the longer version):

- **Dedupe.** At most one job per (kind, subject) is queued or running; a
  second enqueue is a no-op (a partial unique index, ``ON CONFLICT DO
  NOTHING``). Once it is done, the same subject can be queued again.
- **Claim.** ``SELECT … FOR UPDATE SKIP LOCKED`` on the oldest due row of the
  highest priority, so two workers never take the same job.
- **Lease.** A claimed job is ``running`` until its lease ends. A worker that
  dies (a crash, a restart, an OOM kill) never finishes it, so once the lease
  has run out it is queued again, or failed if it has used its attempts: a
  job that kills its worker cannot loop forever.
- **Retry.** A handler that raises is retried after a backoff that doubles
  each attempt; ``PermanentJobError`` (the subject is gone, say) fails it at
  once. Failures keep their error for the admin page.
- **Pruning.** Done jobs are deleted after ``JOB_KEEP_DONE_HOURS``, failed ones
  after ``JOB_KEEP_FAILED_DAYS``, in small batches.

The worker runs in the API process, so it is built never to take the API with
it: daemon threads, off unless ``JOB_WORKER_ENABLED``, one thread by default,
lowered priority, a rest after every job, no database session held while a
handler runs (handlers open their own short ones), and every exception caught.
A handler is responsible for its own weight: one subject at a time, nothing
kept between jobs but what it caches on purpose.
"""

from __future__ import annotations

import logging
import os
import random
import socket
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable
from uuid import UUID

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models.job import PENDING_SQL, Job

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_LEASE_S = 300.0
DEFAULT_BACKOFF_S = 30.0
MAX_BACKOFF_S = 3600.0
_ERROR_MAX_CHARS = 2000
_PRUNE_BATCH = 2000
_PRUNE_MAX_BATCHES = 50
_MAINTENANCE_INTERVAL_S = 60.0
_PRUNE_INTERVAL_S = 3600.0
_ENQUEUE_CHUNK = 1000


class PermanentJobError(Exception):
    """Raised by a handler when trying again cannot help: the job fails now."""


@dataclass(frozen=True)
class JobContext:
    """What a handler gets: a copy of the row, not the row (no session is open)."""

    id: UUID
    kind: str
    subject: str | None
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


@dataclass(frozen=True)
class JobHandler:
    kind: str
    fn: Callable[[JobContext], dict[str, Any] | None]
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    lease_s: float = DEFAULT_LEASE_S
    backoff_s: float = DEFAULT_BACKOFF_S


_handlers: dict[str, JobHandler] = {}


def register_handler(
    kind: str,
    fn: Callable[[JobContext], dict[str, Any] | None],
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    lease_s: float = DEFAULT_LEASE_S,
    backoff_s: float = DEFAULT_BACKOFF_S,
) -> None:
    """Make ``kind`` runnable. ``lease_s`` must comfortably cover one run: a job
    still running when it ends can be given to another worker."""
    _handlers[kind] = JobHandler(kind, fn, max(1, max_attempts), float(lease_s), float(backoff_s))


def registered_kinds() -> list[str]:
    return sorted(_handlers)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------- enqueue


def _insert_for(db: Session):
    return pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert


def enqueue_many(
    db: Session,
    kind: str,
    subjects: Iterable[str | None],
    payload: dict[str, Any] | None = None,
    *,
    priority: int = 0,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
    commit: bool = True,
) -> int:
    """Queue one job per subject; returns how many were new. A subject that
    already has a job of this kind queued or running is skipped."""
    handler = _handlers.get(kind)
    attempts = max_attempts or (handler.max_attempts if handler else DEFAULT_MAX_ATTEMPTS)
    now = _now()
    due = run_after or now
    insert = _insert_for(db)
    added = 0
    chunk: list[dict[str, Any]] = []

    def flush() -> int:
        if not chunk:
            return 0
        stmt = insert(Job).values(chunk).on_conflict_do_nothing(
            index_elements=["kind", "subject"],
            index_where=text(PENDING_SQL),
        )
        result = db.execute(stmt)
        chunk.clear()
        return max(0, result.rowcount or 0)

    for subject in subjects:
        chunk.append(
            {
                "id": uuid.uuid4(),
                "kind": kind,
                "subject": subject,
                "payload": payload or {},
                "status": "queued",
                "priority": priority,
                "attempts": 0,
                "max_attempts": attempts,
                "run_after": due,
                "created_at": now,
                "updated_at": now,
            }
        )
        if len(chunk) >= _ENQUEUE_CHUNK:
            added += flush()
    added += flush()
    if commit:
        db.commit()
    if added:
        get_job_worker().notify()
    return added


def enqueue(
    db: Session,
    kind: str,
    subject: str | None = None,
    payload: dict[str, Any] | None = None,
    *,
    priority: int = 0,
    run_after: datetime | None = None,
    max_attempts: int | None = None,
    commit: bool = True,
) -> bool:
    """Queue one job. False when the same (kind, subject) is already pending."""
    return (
        enqueue_many(
            db,
            kind,
            [subject],
            payload,
            priority=priority,
            run_after=run_after,
            max_attempts=max_attempts,
            commit=commit,
        )
        == 1
    )


# ---------------------------------------------------------------------- the worker's side


def claim(db: Session, worker_id: str, kinds: Iterable[str] | None = None) -> JobContext | None:
    """Take the next due job (of ``kinds``, if given) and lease it to ``worker_id``."""
    now = _now()
    query = select(Job).where(Job.status == "queued", Job.run_after <= now)
    if kinds is not None:
        kinds = list(kinds)
        if not kinds:
            return None
        query = query.where(Job.kind.in_(kinds))
    query = (
        query.order_by(Job.priority.desc(), Job.run_after.asc(), Job.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    job = db.execute(query).scalars().first()
    if job is None:
        db.rollback()
        return None
    handler = _handlers.get(job.kind)
    lease_s = handler.lease_s if handler else DEFAULT_LEASE_S
    job.status = "running"
    job.attempts = int(job.attempts or 0) + 1
    job.locked_by = worker_id
    job.locked_until = now + timedelta(seconds=lease_s)
    job.started_at = now
    job.updated_at = now
    context = JobContext(
        id=job.id,
        kind=job.kind,
        subject=job.subject,
        payload=dict(job.payload or {}),
        attempts=job.attempts,
        max_attempts=int(job.max_attempts or DEFAULT_MAX_ATTEMPTS),
    )
    db.commit()
    return context


def _owned(job_id: UUID, worker_id: str):
    return (Job.id == job_id) & (Job.status == "running") & (Job.locked_by == worker_id)


def complete(db: Session, job_id: UUID, worker_id: str, result: dict[str, Any] | None) -> bool:
    """Mark a job done. False when this worker no longer holds it (its lease ran
    out and the job went to another worker or back to the queue)."""
    now = _now()
    res = db.execute(
        update(Job)
        .where(_owned(job_id, worker_id))
        .values(
            status="done",
            result=result,
            error=None,
            finished_at=now,
            updated_at=now,
            locked_by=None,
            locked_until=None,
        )
    )
    db.commit()
    return (res.rowcount or 0) == 1


def backoff_seconds(base_s: float, attempts: int) -> float:
    """base, 2x base, 4x base … capped at an hour, with a little jitter so a
    batch that failed together does not come back together."""
    delay = min(MAX_BACKOFF_S, base_s * (2 ** max(0, attempts - 1)))
    return delay * random.uniform(0.9, 1.1)


def fail(db: Session, job_id: UUID, worker_id: str, error: str, *, permanent: bool = False) -> str | None:
    """Record a failed attempt: queue it again after a backoff, or fail it for
    good when it is out of attempts (or ``permanent``). Returns the new status,
    None when this worker no longer holds the job."""
    job = db.execute(select(Job).where(_owned(job_id, worker_id)).with_for_update()).scalars().first()
    if job is None:
        db.rollback()
        return None
    now = _now()
    job.error = (error or "")[:_ERROR_MAX_CHARS]
    job.locked_by = None
    job.locked_until = None
    job.updated_at = now
    if permanent or job.attempts >= job.max_attempts:
        job.status = "failed"
        job.finished_at = now
    else:
        handler = _handlers.get(job.kind)
        base = handler.backoff_s if handler else DEFAULT_BACKOFF_S
        job.status = "queued"
        job.run_after = now + timedelta(seconds=backoff_seconds(base, job.attempts))
    status = job.status
    db.commit()
    return status


def requeue_expired(db: Session) -> dict[str, int]:
    """Give back the jobs whose lease ran out: their worker died or hung. Out of
    attempts, they fail instead, so a job that kills its worker stops there."""
    now = _now()
    expired = (Job.status == "running") & (Job.locked_until < now)
    message = "The worker's lease ran out before the job finished (it stopped, or the job ran too long)."
    failed = db.execute(
        update(Job)
        .where(expired & (Job.attempts >= Job.max_attempts))
        .values(
            status="failed",
            error=message,
            finished_at=now,
            updated_at=now,
            locked_by=None,
            locked_until=None,
        )
    ).rowcount or 0
    requeued = db.execute(
        update(Job)
        .where(expired)
        .values(
            status="queued",
            error=message,
            run_after=now,
            updated_at=now,
            locked_by=None,
            locked_until=None,
        )
    ).rowcount or 0
    db.commit()
    if failed or requeued:
        logger.warning("job queue: %d expired jobs queued again, %d failed", requeued, failed)
    return {"requeued": requeued, "failed": failed}


def prune(db: Session) -> int:
    """Delete done and failed jobs past their keep time, a batch at a time."""
    now = _now()
    cutoffs = (
        ("done", now - timedelta(hours=max(0.0, settings.JOB_KEEP_DONE_HOURS))),
        ("failed", now - timedelta(days=max(0.0, settings.JOB_KEEP_FAILED_DAYS))),
    )
    deleted = 0
    for status, cutoff in cutoffs:
        for _ in range(_PRUNE_MAX_BATCHES):
            ids = select(Job.id).where(Job.status == status, Job.finished_at < cutoff).limit(_PRUNE_BATCH)
            n = db.execute(delete(Job).where(Job.id.in_(ids)).execution_options(synchronize_session=False)).rowcount or 0
            db.commit()
            deleted += n
            if n < _PRUNE_BATCH:
                break
    if deleted:
        logger.info("job queue: pruned %d finished jobs", deleted)
    return deleted


def retry(db: Session, job_id: UUID) -> Job | None:
    """Queue a failed job again with fresh attempts. None when it does not
    exist or is not failed; raises IntegrityError when the same subject is
    already pending again."""
    job = db.execute(select(Job).where(Job.id == job_id, Job.status == "failed")).scalars().first()
    if job is None:
        return None
    now = _now()
    job.status = "queued"
    job.attempts = 0
    job.run_after = now
    job.finished_at = None
    job.updated_at = now
    db.commit()
    get_job_worker().notify()
    return job


def summary(db: Session, *, failures: int = 20) -> dict[str, Any]:
    """Counts by kind and status, the oldest due job of each kind, and the
    latest failures: what the admin page shows."""
    kinds: dict[str, dict[str, Any]] = {}
    for kind, status, count in db.execute(select(Job.kind, Job.status, func.count()).group_by(Job.kind, Job.status)):
        row = kinds.setdefault(kind, {"kind": kind, "queued": 0, "running": 0, "done": 0, "failed": 0})
        row[status] = int(count)
    for kind, oldest in db.execute(
        select(Job.kind, func.min(Job.created_at)).where(Job.status == "queued").group_by(Job.kind)
    ):
        if kind in kinds:
            kinds[kind]["oldest_queued_at"] = oldest.isoformat() if oldest else None
    for kind in _handlers:
        kinds.setdefault(kind, {"kind": kind, "queued": 0, "running": 0, "done": 0, "failed": 0})
    recent = (
        db.execute(select(Job).where(Job.status == "failed").order_by(Job.finished_at.desc()).limit(failures))
        .scalars()
        .all()
    )
    return {
        "worker": get_job_worker().status(),
        "kinds": [
            {**row, "registered": row["kind"] in _handlers, "oldest_queued_at": row.get("oldest_queued_at")}
            for row in sorted(kinds.values(), key=lambda r: r["kind"])
        ],
        "recent_failures": [serialize(job) for job in recent],
    }


def serialize(job: Job) -> dict[str, Any]:
    def iso(value: datetime | None) -> str | None:
        return value.isoformat() if value else None

    return {
        "id": str(job.id),
        "kind": job.kind,
        "subject": job.subject,
        "status": job.status,
        "priority": job.priority,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "error": job.error,
        "result": job.result,
        "run_after": iso(job.run_after),
        "created_at": iso(job.created_at),
        "started_at": iso(job.started_at),
        "finished_at": iso(job.finished_at),
    }


# ---------------------------------------------------------------------- the worker


def _lower_thread_priority(nice: int) -> None:
    """Raise this thread's nice value. On Linux the nice value belongs to the
    thread, so the API's threads keep theirs. Anywhere else (where a thread id
    is not something setpriority takes), or without leave, it stays as it is."""
    if nice <= 0 or not sys.platform.startswith("linux"):
        return
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), nice)
    except OSError:
        logger.info("job queue: could not lower the worker thread's priority")


@dataclass
class _WorkerState:
    running: bool = False
    threads: int = 0
    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    last_job_at: str | None = None
    last_error: str | None = None
    current: dict[str, Any] = field(default_factory=dict)


class JobWorker:
    """Worker threads that claim and run jobs, and keep the table tidy."""

    def __init__(self) -> None:
        self._threads: list[threading.Thread] = []
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._start_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = _WorkerState()
        # Unique per process, so a restarted process never mistakes the jobs
        # its predecessor held for its own.
        self._process_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._last_maintenance = 0.0
        self._last_prune = 0.0

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if not settings.JOB_WORKER_ENABLED:
            logger.info("job queue: worker is off (JOB_WORKER_ENABLED)")
            return
        with self._start_lock:
            if any(t.is_alive() for t in self._threads):
                return
            self._stop_event.clear()
            count = max(1, int(settings.JOB_WORKER_CONCURRENCY))
            self._threads = [
                threading.Thread(target=self._loop, args=(i,), name=f"job-worker-{i}", daemon=True)
                for i in range(count)
            ]
            for thread in self._threads:
                thread.start()
        with self._state_lock:
            self._state.running = True
            self._state.threads = count
        logger.info("job queue: worker started (%d thread%s, kinds: %s)", count, "" if count == 1 else "s", ", ".join(registered_kinds()) or "none")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        self._wake_event.set()
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
        with self._state_lock:
            self._state.running = False

    def notify(self) -> None:
        self._wake_event.set()

    def status(self) -> dict[str, Any]:
        with self._state_lock:
            state = self._state
            return {
                "enabled": bool(settings.JOB_WORKER_ENABLED),
                "running": state.running and any(t.is_alive() for t in self._threads),
                "threads": state.threads,
                "processed": state.processed,
                "succeeded": state.succeeded,
                "failed": state.failed,
                "last_job_at": state.last_job_at,
                "last_error": state.last_error,
                "current": dict(state.current) or None,
                "kinds": registered_kinds(),
            }

    # ------------------------------------------------------------------ the loop

    def _loop(self, index: int) -> None:
        _lower_thread_priority(int(settings.JOB_WORKER_NICE))
        worker_id = f"{self._process_id}/{index}"
        errors = 0
        while not self._stop_event.is_set():
            try:
                if index == 0:
                    self._maintain()
                ran = self.run_once(worker_id)
                errors = 0
            except Exception as exc:  # the database is away, say: wait and try again
                errors += 1
                ran = False
                with self._state_lock:
                    self._state.last_error = str(exc)[:500]
                if errors == 1 or errors % 20 == 0:
                    logger.exception("job queue: worker pass failed (%d in a row)", errors)
            if ran:
                pause = max(0.0, float(settings.JOB_WORKER_PAUSE_S))
                if pause:
                    self._stop_event.wait(pause)
                continue
            wait = float(settings.JOB_WORKER_POLL_INTERVAL_S) * min(12, 2 ** min(errors, 4) if errors else 1)
            self._wake_event.wait(timeout=max(0.1, wait))
            self._wake_event.clear()
        logger.info("job queue: worker thread %d stopped", index)

    def _maintain(self) -> None:
        now = time.monotonic()
        if now - self._last_maintenance < _MAINTENANCE_INTERVAL_S:
            return
        self._last_maintenance = now
        db = SessionLocal()
        try:
            requeue_expired(db)
            if now - self._last_prune >= _PRUNE_INTERVAL_S:
                self._last_prune = now
                prune(db)
        finally:
            db.close()

    def run_once(self, worker_id: str | None = None) -> bool:
        """Claim and run one due job. True if there was one. Also how tests
        drive the queue without starting threads."""
        worker_id = worker_id or f"{self._process_id}/inline"
        db = SessionLocal()
        try:
            job = claim(db, worker_id, kinds=registered_kinds())
        finally:
            db.close()
        if job is None:
            return False
        handler = _handlers[job.kind]
        started = time.monotonic()
        with self._state_lock:
            self._state.current = {"id": str(job.id), "kind": job.kind, "subject": job.subject}
        outcome = "done"
        error: str | None = None
        permanent = False
        result: dict[str, Any] | None = None
        try:
            result = handler.fn(job)
        except PermanentJobError as exc:
            outcome, error, permanent = "failed", str(exc) or exc.__class__.__name__, True
        except Exception as exc:
            logger.exception("job queue: %s job %s (subject %s) failed", job.kind, job.id, job.subject)
            outcome, error, permanent = "retry", f"{exc.__class__.__name__}: {exc}", False
        db = SessionLocal()
        try:
            if error is None:
                if not complete(db, job.id, worker_id, result if isinstance(result, dict) else None):
                    logger.warning("job queue: %s job %s finished after its lease was taken", job.kind, job.id)
            else:
                outcome = fail(db, job.id, worker_id, error, permanent=permanent) or "lost"
        finally:
            db.close()
            with self._state_lock:
                self._state.current = {}
        elapsed = time.monotonic() - started
        with self._state_lock:
            self._state.processed += 1
            if outcome == "done":
                self._state.succeeded += 1
            elif outcome == "failed":
                self._state.failed += 1
            if error is not None:
                self._state.last_error = error[:500]
            self._state.last_job_at = _now().isoformat()
        logger.debug("job queue: %s job %s %s in %.2fs", job.kind, job.id, outcome, elapsed)
        return True


_worker = JobWorker()


def get_job_worker() -> JobWorker:
    return _worker
