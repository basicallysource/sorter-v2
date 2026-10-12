"""The parts of the job queue that only Postgres has: ON CONFLICT against the
partial unique index, and FOR UPDATE SKIP LOCKED between two workers.

The suite runs on sqlite, so these run only when HIVE_TEST_POSTGRES_URL names
a throwaway Postgres database (its jobs table is created and dropped here).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app.models.job import Job
from app.services import job_queue

PG_URL = os.environ.get("HIVE_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not PG_URL, reason="set HIVE_TEST_POSTGRES_URL to a throwaway Postgres database")


@pytest.fixture()
def pg(monkeypatch):
    # A claim that blocks on another's lock fails after two seconds instead of hanging.
    engine = create_engine(PG_URL, connect_args={"options": "-c lock_timeout=2000"})
    Job.__table__.drop(engine, checkfirst=True)
    Job.__table__.create(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(job_queue, "_handlers", {})
    monkeypatch.setattr(job_queue, "_worker", job_queue.JobWorker())
    job_queue.register_handler("k", lambda job: None, max_attempts=2)
    yield Session
    Job.__table__.drop(engine, checkfirst=True)
    engine.dispose()


def test_enqueue_dedupes_against_the_partial_index(pg):
    db = pg()
    try:
        assert job_queue.enqueue_many(db, "k", ["a", "b", "a"]) == 2
        assert job_queue.enqueue(db, "k", "a") is False
        db.execute(text("UPDATE jobs SET status = 'done' WHERE subject = 'a'"))
        db.commit()
        assert job_queue.enqueue(db, "k", "a") is True
        assert db.execute(text("SELECT count(*) FROM jobs WHERE subject = 'a'")).scalar() == 2
    finally:
        db.close()


def test_two_workers_never_take_the_same_job_and_never_wait_on_each_other(pg):
    db = pg()
    job_queue.enqueue_many(db, "k", ["first", "second"])
    holder, other = pg(), pg()
    try:
        # A claim in progress: the first job's row is locked, not yet committed.
        locked = holder.execute(
            select(Job).where(Job.subject == "first").with_for_update()
        ).scalars().one()
        assert locked.status == "queued"
        got = job_queue.claim(other, "worker-b", kinds=["k"])
        assert got is not None and got.subject == "second"
        assert job_queue.claim(other, "worker-b", kinds=["k"]) is None
        holder.rollback()
        got = job_queue.claim(other, "worker-b", kinds=["k"])
        assert got is not None and got.subject == "first"
    finally:
        holder.close()
        other.close()
        db.close()


def test_leases_and_backoff_with_real_timestamps(pg):
    db = pg()
    try:
        job_queue.enqueue(db, "k", "s")
        job = job_queue.claim(db, "w", kinds=["k"])
        assert job_queue.fail(db, job.id, "w", "boom") == "queued"
        row = db.execute(select(Job).where(Job.id == job.id)).scalars().one()
        assert row.run_after > datetime.now(timezone.utc) + timedelta(seconds=20)

        db.execute(text("UPDATE jobs SET run_after = now() - interval '1 second'"))
        db.commit()
        job = job_queue.claim(db, "w", kinds=["k"])
        db.execute(text("UPDATE jobs SET locked_until = now() - interval '1 second'"))
        db.commit()
        assert job_queue.requeue_expired(db) == {"requeued": 0, "failed": 1}
        assert db.execute(select(Job.status).where(Job.id == job.id)).scalar() == "failed"
    finally:
        db.close()
