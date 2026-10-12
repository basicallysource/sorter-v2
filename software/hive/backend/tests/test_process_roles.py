"""Hive as two processes: which background workers each role starts, how the
worker process reports and takes requests, how a web process shows and asks
the workers, and the statement timeout every request carries.

See agent-docs/process-roles.md.
"""

from __future__ import annotations

import dataclasses
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app import background, deps
from app.config import settings
from app.deps import get_db, request_statement_timeout_ms, statement_timeout
from app.errors import operational_error_handler
from app.main import app
from app.models.user import User
from app.models.worker_state import WorkerState
from app.services import worker_state
from app.services.machine_stats import get_machine_stats_worker
from tests.conftest import _auth_headers, _login_user, _register_user

# --------------------------------------------------------------------------- roles


@pytest.fixture()
def started(monkeypatch):
    """The real registry, with each start recorded instead of run: no threads."""
    names: list[str] = []
    real_workers, real_upkeep = background.workers, background._upkeep

    def recorded(workers):
        return [
            dataclasses.replace(w, start=lambda name=w.name: names.append(name), stop=lambda: None)
            for w in workers
        ]

    monkeypatch.setattr(background, "workers", lambda: recorded(real_workers()))
    monkeypatch.setattr(background, "_upkeep", lambda: recorded(real_upkeep()))
    yield names
    background.stop()


COMMON_WORKERS = {
    "teacher-worker",
    "condition-worker",
    "machine-stats-worker",
    "fleet-mass-worker",
    "fleet-records-worker",
    "storage-stats-worker",
    "labeling-queue-worker",
    "job-worker",
}
# The catalog's own work: in-process where the process holds the catalog
# anyway, child processes in the worker process, which never holds it.
WORKER_NAMES = {
    "all": COMMON_WORKERS | {"catalog-auto-sync", "default-profiles"},
    "worker": COMMON_WORKERS | {"catalog-tasks"},
}
EVERY_WORKER = WORKER_NAMES["all"] | WORKER_NAMES["worker"]


@pytest.mark.parametrize("role", ["worker", "all"])
def test_the_registry_is_every_background_worker(monkeypatch, role):
    monkeypatch.setattr(settings, "HIVE_ROLE", role)
    assert {w.name for w in background.workers()} == WORKER_NAMES[role]


def test_web_starts_no_background_worker(monkeypatch, started):
    monkeypatch.setattr(settings, "HIVE_ROLE", "web")
    assert background.start() == started == ["memory-log-worker", "catalog-warmup"]
    assert not EVERY_WORKER & set(started)


@pytest.mark.parametrize("role", ["worker", "all"])
def test_worker_and_all_start_every_background_worker(monkeypatch, started, role):
    monkeypatch.setattr(settings, "HIVE_ROLE", role)
    background.start()
    assert set(started) == WORKER_NAMES[role] | {"memory-log-worker"}


def test_the_web_app_starts_no_background_worker(monkeypatch, started):
    """The lifespan is where a serving process starts what its role runs."""
    monkeypatch.setattr(settings, "HIVE_ROLE", "web")
    with TestClient(app):
        pass
    assert not EVERY_WORKER & set(started)


def test_the_web_app_refuses_the_worker_role(monkeypatch, started):
    monkeypatch.setattr(settings, "HIVE_ROLE", "worker")
    with pytest.raises(RuntimeError, match="app.worker"):
        with TestClient(app):
            pass
    assert started == []


def test_job_worker_enabled_cannot_start_jobs_in_a_web_process(monkeypatch, started):
    monkeypatch.setattr(settings, "HIVE_ROLE", "web")
    monkeypatch.setattr(settings, "JOB_WORKER_ENABLED", True)
    background.start()
    assert "job-worker" not in started


# --------------------------------------------------------------------------- the worker process


def test_worker_process_reports_and_takes_requests(monkeypatch, started, tmp_path, db):
    from app import database, worker
    from tests.conftest import TestingSessionLocal

    monkeypatch.setattr(database, "SessionLocal", TestingSessionLocal)
    beat_file = tmp_path / "heartbeat"
    monkeypatch.setattr(settings, "HIVE_ROLE", "worker")
    monkeypatch.setattr(settings, "WORKER_HEARTBEAT_FILE", str(beat_file))
    monkeypatch.setattr(settings, "WORKER_POLL_INTERVAL_S", 0.05)
    woken = threading.Event()
    monkeypatch.setattr(get_machine_stats_worker(), "wake", woken.set)

    stop = threading.Event()
    thread = threading.Thread(target=worker.run, args=(stop,), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not beat_file.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert beat_file.exists(), "the healthcheck file is touched after the first report"
        assert set(started) == WORKER_NAMES["worker"] | {"memory-log-worker"}

        beat = worker_state.read_heartbeat(db)
        assert beat is not None and beat.fresh
        assert beat.payload["process"]["role"] == "worker"
        assert set(beat.payload["workers"]) == WORKER_NAMES["worker"]

        # What a web process leaves when an admin asks for a pass now.
        worker_state.ask(db, "wake:machine-stats-worker")
        assert woken.wait(10), "the worker process should take the request and wake the worker"
        db.expire_all()
        assert db.query(WorkerState).filter(WorkerState.name.startswith("request:")).count() == 0
    finally:
        stop.set()
        thread.join(10)
    assert not thread.is_alive()


def test_worker_entrypoint_refuses_another_role(monkeypatch):
    from app import worker

    monkeypatch.setattr(settings, "HIVE_ROLE", "all")
    assert worker.main() == 2


# --------------------------------------------------------------------------- a web process


@pytest.fixture()
def admin_headers(client, db):
    _register_user(client, "admin@test.com", "Password123!", "Admin")
    user = db.query(User).filter(User.email == "admin@test.com").first()
    user.role = "admin"
    db.commit()
    _login_user(client, "admin@test.com", "Password123!")
    return _auth_headers(client)


def _beat(db, workers, *, age_s: float = 0.0, catalog=None):
    worker_state.write_heartbeat(
        db, {"process": {"role": "worker"}, "workers": workers, "catalog": catalog}
    )
    if age_s:
        row = db.get(WorkerState, worker_state.HEARTBEAT)
        row.updated_at = datetime.now(timezone.utc) - timedelta(seconds=age_s)
        db.commit()


def test_web_shows_the_worker_process_state(monkeypatch, client, db, admin_headers):
    monkeypatch.setattr(settings, "HIVE_ROLE", "web")
    _beat(db, {"job-worker": {"enabled": True, "running": True, "processed": 5, "threads": 1}})

    body = client.get("/api/admin/jobs").json()
    assert body["worker"]["enabled"] is True and body["worker"]["running"] is True
    assert body["worker"]["processed"] == 5 and body["worker"]["reported_at"]

    # A report too old to believe is a worker that is not running.
    _beat(db, {"job-worker": {"enabled": True, "running": True, "processed": 5}}, age_s=3600)
    assert client.get("/api/admin/jobs").json()["worker"]["running"] is False


def test_web_asks_the_worker_process_for_a_pass(monkeypatch, client, db, admin_headers):
    monkeypatch.setattr(settings, "HIVE_ROLE", "web")
    woken = []
    monkeypatch.setattr(get_machine_stats_worker(), "wake", lambda: woken.append(True))

    r = client.post("/api/admin/machines/stats/refresh", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json()["requested"] is True
    assert woken == [], "the worker is not in this process"
    assert worker_state.take_requests(db) == [("wake:machine-stats-worker", {})]


def test_web_hands_catalog_syncs_to_the_worker_process(monkeypatch, client, db, admin_headers):
    monkeypatch.setattr(settings, "HIVE_ROLE", "web")
    r = client.post("/api/profile-catalog/sync/parts", headers=admin_headers)
    assert r.status_code == 200, r.text
    assert worker_state.take_requests(db) == [("catalog-sync:parts", {})]

    _beat(db, {}, catalog={"running": True, "sync_type": "parts"})
    assert client.get("/api/profile-catalog/status").json()["sync_type"] == "parts"
    r = client.post("/api/profile-catalog/sync/colors", headers=admin_headers)
    assert r.status_code == 409, "one sync at a time, wherever it runs"


def test_web_catalog_follows_the_worker_syncs(monkeypatch, tmp_path):
    """One parts.db, two processes: the worker's sync shows up in the web
    process's catalog, and the web process leaves the worker's sync state alone."""
    from app.services import profile_catalog
    from app.services.profile_engine import db as profile_db

    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", str(tmp_path / "parts.db"))
    worker_side = profile_catalog.ProfileCatalogService(runs_syncs=True)
    # The worker is mid-sync when the web process starts.
    profile_db.upsertCatalogSyncState(worker_side._conn, "parts", status="running")
    web_side = profile_catalog.ProfileCatalogService(runs_syncs=False)
    assert profile_db.getCatalogSyncState(web_side._conn, "parts")["status"] == "running"
    assert "3001" not in web_side.parts_data.parts

    # The worker's sync lands: a new part, and the time it finished.
    worker_side._conn.execute("INSERT INTO parts (part_num, name) VALUES ('3001', 'Brick 2 x 4')")
    worker_side._conn.commit()
    worker_side._mark_sync_completed("parts")

    web_side.follow_syncs()
    assert "3001" not in web_side.parts_data.parts, "looks at most once a minute"
    web_side._followed_at -= profile_catalog.FOLLOW_SYNCS_INTERVAL_S
    web_side.follow_syncs()
    deadline = time.monotonic() + 10
    while "3001" not in web_side.parts_data.parts and time.monotonic() < deadline:
        time.sleep(0.05)
    assert web_side.parts_data.parts["3001"]["name"] == "Brick 2 x 4"


def test_published_answers_outlive_the_process(db):
    """What a worker publishes is read back from the database, not from memory."""
    from app.services import fleet_mass

    assert fleet_mass.latest(db)["computed_at"] is None
    worker_state.publish(db, "fleet_mass", {"known_grams": 12.5, "computed_at": "2026-10-12T00:00:00+00:00"})
    assert fleet_mass.latest(db)["known_grams"] == 12.5


# --------------------------------------------------------------------------- statement timeouts


def _request(path: str, endpoint=None) -> Request:
    route = type("Route", (), {"endpoint": endpoint})() if endpoint else None
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b"", "route": route})


def test_each_request_gets_its_paths_statement_timeout(monkeypatch):
    monkeypatch.setattr(settings, "HIVE_ROLE", "web")
    assert request_statement_timeout_ms(_request("/api/samples")) == settings.REQUEST_STATEMENT_TIMEOUT_MS == 15_000
    assert request_statement_timeout_ms(_request("/api/machine/sync/channel-crop")) == 20_000
    assert request_statement_timeout_ms(_request("/api/devices/ping")) == 20_000
    # Not a machine path, just a name that starts the same way.
    assert request_statement_timeout_ms(_request("/api/machine-ip-lookup")) == 15_000

    @statement_timeout(seconds=60)
    def long_endpoint():  # pragma: no cover - never called
        ...

    assert request_statement_timeout_ms(_request("/api/samples/batch-archive", long_endpoint)) == 60_000

    monkeypatch.setattr(settings, "REQUEST_STATEMENT_TIMEOUT_MS", 0)
    assert request_statement_timeout_ms(_request("/api/samples")) is None


def test_a_process_that_serves_no_requests_sets_none(monkeypatch):
    monkeypatch.setattr(settings, "HIVE_ROLE", "worker")
    assert request_statement_timeout_ms(_request("/api/samples")) is None


PG_URL = os.environ.get("HIVE_TEST_POSTGRES_URL")


@pytest.fixture()
def pg_app(monkeypatch):
    """A small app on the real get_db and error handler, its sessions on Postgres."""
    if not PG_URL:
        pytest.skip("set HIVE_TEST_POSTGRES_URL to a throwaway Postgres database")
    monkeypatch.setattr(settings, "HIVE_ROLE", "web")
    engine = create_engine(PG_URL, pool_size=1, max_overflow=0)
    monkeypatch.setattr(deps, "SessionLocal", sessionmaker(bind=engine))

    probe = FastAPI()
    probe.add_exception_handler(OperationalError, operational_error_handler)

    def show(db: Session) -> str:
        return db.execute(text("SHOW statement_timeout")).scalar()

    @probe.get("/api/probe")
    def user_probe(db: Session = Depends(get_db)):
        first = show(db)
        db.commit()  # a second transaction must get the limit again
        return {"first": first, "second": show(db)}

    @probe.get("/api/machine/probe")
    def machine_probe(db: Session = Depends(get_db)):
        return {"first": show(db)}

    @probe.get("/api/long")
    @statement_timeout(seconds=60)
    def long_probe(db: Session = Depends(get_db)):
        return {"first": show(db)}

    @probe.get("/api/slow")
    def slow(db: Session = Depends(get_db)):
        db.execute(text("SELECT pg_sleep(2)"))
        return {"finished": True}

    yield TestClient(probe), engine
    engine.dispose()


def test_statement_timeout_is_set_per_request_and_per_transaction(pg_app):
    client, engine = pg_app
    assert client.get("/api/probe").json() == {"first": "15s", "second": "15s"}
    assert client.get("/api/machine/probe").json() == {"first": "20s"}
    assert client.get("/api/long").json() == {"first": "1min"}
    # SET LOCAL ends with the transaction: the pooled connection (pool of one,
    # so the same one) gives its next user the server's own setting back.
    with engine.connect() as conn:
        assert conn.execute(text("SHOW statement_timeout")).scalar() == "0"


def test_a_request_that_runs_out_of_time_is_a_503(pg_app, monkeypatch):
    client, _engine = pg_app
    monkeypatch.setattr(settings, "REQUEST_STATEMENT_TIMEOUT_MS", 200)
    started = time.monotonic()
    r = client.get("/api/slow")
    assert r.status_code == 503, r.text
    assert r.json()["code"] == "STATEMENT_TIMEOUT"
    assert time.monotonic() - started < 1.5, "cancelled at the limit, not at the end of the sleep"
