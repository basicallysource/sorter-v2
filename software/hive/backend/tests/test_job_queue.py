"""The general job queue: dedupe, claim order, leases, retries, pruning, the
worker thread and the admin endpoints."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.config import settings
from app.models.job import Job
from app.models.user import User
from app.services import job_queue
from app.services.job_queue import JobContext, PermanentJobError
from tests.conftest import TestingSessionLocal, _auth_headers, _login_user, _register_user


@pytest.fixture(autouse=True)
def _queue(monkeypatch):
    """Point the queue at the test database and give each test its own handlers."""
    monkeypatch.setattr(job_queue, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(job_queue, "_handlers", {})
    monkeypatch.setattr(job_queue, "_worker", job_queue.JobWorker())
    yield


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job(db: Session, kind: str, subject: str) -> Job:
    db.expire_all()
    return db.query(Job).filter(Job.kind == kind, Job.subject == subject).order_by(Job.created_at.desc()).first()


def _make_due(db: Session, job: Job) -> None:
    job.run_after = _now() - timedelta(seconds=1)
    db.commit()


def test_enqueue_dedupes_while_pending_and_again_once_done(db):
    seen: list[str] = []
    job_queue.register_handler("echo", lambda job: seen.append(job.subject) or {"ok": True})

    assert job_queue.enqueue(db, "echo", "a") is True
    assert job_queue.enqueue(db, "echo", "a") is False
    assert job_queue.enqueue(db, "other", "a") is True  # dedupe is per kind
    assert job_queue.enqueue_many(db, "echo", ["a", "b", "c", "b"]) == 2
    assert db.query(Job).filter(Job.kind == "echo").count() == 3

    worker = job_queue.get_job_worker()
    while worker.run_once("w"):
        pass
    assert sorted(seen) == ["a", "b", "c"]
    done = _job(db, "echo", "a")
    assert done.status == "done" and done.result == {"ok": True} and done.attempts == 1
    assert done.locked_by is None and done.finished_at is not None

    # Done is no longer pending: the same subject can be queued again.
    assert job_queue.enqueue(db, "echo", "a") is True
    assert db.query(Job).filter(Job.kind == "echo", Job.subject == "a").count() == 2


def test_claim_takes_the_highest_priority_due_job_of_a_known_kind(db):
    job_queue.register_handler("k", lambda job: None)
    job_queue.enqueue(db, "k", "low", priority=-10)
    job_queue.enqueue(db, "k", "high", priority=5)
    job_queue.enqueue(db, "k", "later", priority=50, run_after=_now() + timedelta(hours=1))
    job_queue.enqueue(db, "unknown", "x", priority=100)

    session = TestingSessionLocal()
    try:
        first = job_queue.claim(session, "w1", kinds=job_queue.registered_kinds())
        second = job_queue.claim(session, "w1", kinds=job_queue.registered_kinds())
        third = job_queue.claim(session, "w1", kinds=job_queue.registered_kinds())
    finally:
        session.close()
    assert [first.subject, second.subject] == ["high", "low"]
    assert third is None  # "later" is not due, "unknown" has no handler

    claimed = _job(db, "k", "high")
    assert claimed.status == "running" and claimed.locked_by == "w1" and claimed.attempts == 1
    assert claimed.locked_until is not None
    assert _job(db, "unknown", "x").status == "queued"


def test_a_failing_job_is_retried_with_backoff_then_fails(db):
    calls: list[int] = []

    def flaky(job: JobContext):
        calls.append(job.attempts)
        raise RuntimeError("camera frame unreadable")

    job_queue.register_handler("flaky", flaky, max_attempts=3, backoff_s=10)
    job_queue.enqueue(db, "flaky", "s1")
    worker = job_queue.get_job_worker()

    assert worker.run_once("w") is True
    job = _job(db, "flaky", "s1")
    assert job.status == "queued" and job.attempts == 1
    assert "camera frame unreadable" in job.error
    wait = (job.run_after.replace(tzinfo=timezone.utc) - _now()).total_seconds()
    assert 7 < wait <= 11  # the first backoff, with its jitter
    assert worker.run_once("w") is False  # not due yet

    _make_due(db, job)
    assert worker.run_once("w") is True
    job = _job(db, "flaky", "s1")
    wait = (job.run_after.replace(tzinfo=timezone.utc) - _now()).total_seconds()
    assert job.status == "queued" and job.attempts == 2 and 16 < wait <= 22  # doubled

    _make_due(db, job)
    assert worker.run_once("w") is True
    job = _job(db, "flaky", "s1")
    assert job.status == "failed" and job.attempts == 3 and job.finished_at is not None
    assert calls == [1, 2, 3]
    assert worker.status()["failed"] == 1


def test_a_permanent_error_fails_at_once(db):
    def gone(job: JobContext):
        raise PermanentJobError("The sample no longer exists.")

    job_queue.register_handler("gone", gone, max_attempts=5)
    job_queue.enqueue(db, "gone", "s1")
    assert job_queue.get_job_worker().run_once("w") is True
    job = _job(db, "gone", "s1")
    assert job.status == "failed" and job.attempts == 1 and job.error == "The sample no longer exists."


def test_an_expired_lease_comes_back_and_a_job_that_keeps_dying_fails(db):
    job_queue.register_handler("k", lambda job: None, max_attempts=2, lease_s=60)
    job_queue.enqueue(db, "k", "s1")

    def claim_and_die(worker_id: str) -> None:
        session = TestingSessionLocal()
        try:
            assert job_queue.claim(session, worker_id, kinds=["k"]) is not None
        finally:
            session.close()
        job = _job(db, "k", "s1")
        job.locked_until = _now() - timedelta(seconds=1)  # the worker died; its lease ran out
        db.commit()

    claim_and_die("dead-1")
    session = TestingSessionLocal()
    try:
        assert job_queue.requeue_expired(session) == {"requeued": 1, "failed": 0}
    finally:
        session.close()
    job = _job(db, "k", "s1")
    assert job.status == "queued" and job.locked_by is None and "lease" in job.error

    # The first worker comes back late: the job is no longer its to finish.
    session = TestingSessionLocal()
    try:
        assert job_queue.complete(session, job.id, "dead-1", {"late": True}) is False
    finally:
        session.close()
    assert _job(db, "k", "s1").status == "queued"

    claim_and_die("dead-2")
    session = TestingSessionLocal()
    try:
        assert job_queue.requeue_expired(session) == {"requeued": 0, "failed": 1}
    finally:
        session.close()
    job = _job(db, "k", "s1")
    assert job.status == "failed" and job.attempts == 2


def test_a_running_job_within_its_lease_is_left_alone(db):
    job_queue.register_handler("k", lambda job: None, lease_s=600)
    job_queue.enqueue(db, "k", "s1")
    session = TestingSessionLocal()
    try:
        job_queue.claim(session, "alive", kinds=["k"])
        assert job_queue.requeue_expired(session) == {"requeued": 0, "failed": 0}
    finally:
        session.close()
    assert _job(db, "k", "s1").status == "running"
    assert job_queue.enqueue(db, "k", "s1") is False  # running still counts as pending


def test_prune_deletes_only_old_finished_jobs(db, monkeypatch):
    monkeypatch.setattr(settings, "JOB_KEEP_DONE_HOURS", 24.0)
    monkeypatch.setattr(settings, "JOB_KEEP_FAILED_DAYS", 7.0)
    now = _now()
    rows = {
        "old-done": ("done", now - timedelta(hours=30)),
        "new-done": ("done", now - timedelta(hours=2)),
        "old-failed": ("failed", now - timedelta(days=8)),
        "new-failed": ("failed", now - timedelta(days=2)),
        "queued": ("queued", None),
    }
    for subject, (status, finished) in rows.items():
        db.add(Job(kind="k", subject=subject, status=status, finished_at=finished, run_after=now))
    db.commit()

    session = TestingSessionLocal()
    try:
        assert job_queue.prune(session) == 2
    finally:
        session.close()
    db.expire_all()
    assert sorted(j.subject for j in db.query(Job).all()) == ["new-done", "new-failed", "queued"]


def test_the_worker_thread_runs_jobs_and_outlives_a_crashing_handler(db, monkeypatch):
    monkeypatch.setattr(settings, "JOB_WORKER_ENABLED", True)
    monkeypatch.setattr(settings, "JOB_WORKER_POLL_INTERVAL_S", 0.05)
    monkeypatch.setattr(settings, "JOB_WORKER_PAUSE_S", 0.0)
    monkeypatch.setattr(settings, "JOB_WORKER_NICE", 0)
    done = threading.Event()
    ran: list[str] = []

    def handler(job: JobContext):
        ran.append(job.subject)
        if job.subject == "boom":
            raise ValueError("bad frame")
        if job.subject == "last":
            done.set()
        return {"subject": job.subject}

    job_queue.register_handler("k", handler, max_attempts=1)
    worker = job_queue.get_job_worker()
    worker.start()
    try:
        job_queue.enqueue(db, "k", "boom", priority=2)
        job_queue.enqueue(db, "k", "fine", priority=1)
        job_queue.enqueue(db, "k", "last", priority=0)
        assert done.wait(10), "the worker did not get to the last job"
        deadline = time.monotonic() + 5
        while worker.status()["processed"] < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        worker.stop()
    assert ran == ["boom", "fine", "last"]
    status = worker.status()
    assert status["processed"] == 3 and status["succeeded"] == 2 and status["failed"] == 1
    assert _job(db, "k", "boom").status == "failed"
    assert _job(db, "k", "last").status == "done"


def test_the_worker_stays_off_unless_enabled(monkeypatch):
    monkeypatch.setattr(settings, "JOB_WORKER_ENABLED", False)
    worker = job_queue.get_job_worker()
    worker.start()
    assert worker.status()["running"] is False


@pytest.fixture()
def admin_headers(client, db) -> dict[str, str]:
    _register_user(client, "admin@test.com", "Password123!", "Admin")
    user = db.query(User).filter(User.email == "admin@test.com").first()
    user.role = "admin"
    db.commit()
    _login_user(client, "admin@test.com", "Password123!")
    return _auth_headers(client)


def test_admin_summary_and_retry(client, db, admin_headers):
    def gone(job: JobContext):
        raise PermanentJobError("nope")

    job_queue.register_handler("gone", gone)
    job_queue.register_handler("idle", lambda job: None)
    job_queue.enqueue(db, "gone", "s1")
    job_queue.enqueue(db, "gone", "s2")
    job_queue.get_job_worker().run_once("w")

    r = client.get("/api/admin/jobs")
    assert r.status_code == 200, r.text
    body = r.json()
    kinds = {k["kind"]: k for k in body["kinds"]}
    assert kinds["gone"]["failed"] == 1 and kinds["gone"]["queued"] == 1
    assert kinds["idle"]["queued"] == 0 and kinds["idle"]["registered"] is True
    assert body["worker"]["enabled"] is False
    [failure] = body["recent_failures"]
    assert failure["error"] == "nope"

    r = client.post(f"/api/admin/jobs/{failure['id']}/retry", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["job"]["status"] == "queued"
    job = _job(db, "gone", failure["subject"])
    assert job.status == "queued" and job.attempts == 0

    # Not failed any more: nothing to retry.
    r = client.post(f"/api/admin/jobs/{failure['id']}/retry", headers=admin_headers)
    assert r.status_code == 404


def test_admin_jobs_is_admin_only(client, test_user):
    assert client.get("/api/admin/jobs").status_code == 403
