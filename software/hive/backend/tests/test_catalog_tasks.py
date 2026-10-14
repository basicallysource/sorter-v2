"""The worker process never holds the parts catalog: it looks parts up in
parts.db without loading it, and runs the work that needs the whole catalog
(a sync, the default profiles) in a child process, one at a time, with a time
limit. See app/services/catalog_tasks.py and agent-docs/process-roles.md."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.config import settings
from app.services import profile_catalog
from app.services.catalog_tasks import CatalogTaskRunner
from app.services.profile_engine import db as profile_db

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture()
def parts_db(monkeypatch, tmp_path):
    """A small parts.db of our own, built the way the web process builds it."""
    path = tmp_path / "parts.db"
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", str(path))
    monkeypatch.setattr(profile_catalog, "_catalog_service", None)
    monkeypatch.setattr(profile_catalog, "_catalog_lookup", None)
    monkeypatch.setattr(profile_catalog, "_loads_catalog_in_worker", False)
    service = profile_catalog.ProfileCatalogService(runs_syncs=True)
    conn = service._conn
    conn.execute("INSERT INTO categories (id, name, part_count) VALUES (11, 'Bricks', 1)")
    conn.execute("INSERT INTO parts (part_num, name, part_cat_id) VALUES ('3001', 'Brick 2 x 4', 11)")
    conn.execute(
        "INSERT INTO colors (id, name, rgb, is_trans, extra) VALUES (4, 'Red', 'C91A09', 0, ?)",
        ('{"external_ids": {"BrickLink": {"ext_ids": [5], "ext_descrs": [["Red"]]}}}',),
    )
    conn.commit()
    profile_db.reloadPartsData(conn, service.parts_data)
    return path, service


def test_the_worker_process_never_loads_the_catalog(monkeypatch, parts_db):
    _path, _service = parts_db
    monkeypatch.setattr(profile_catalog, "_catalog_service", None)
    monkeypatch.setattr(settings, "HIVE_ROLE", "worker")
    with pytest.raises(RuntimeError, match="never loads the parts catalog"):
        profile_catalog.get_profile_catalog_service()

    lookup = profile_catalog.catalog_lookup()
    assert isinstance(lookup, profile_catalog.CatalogLookup)
    assert lookup.piece_metadata("3001")["name"] == "Brick 2 x 4"
    assert lookup.batch_part_weights(["3001"]) == {}
    assert [(c["id"], c["name"]) for c in lookup.list_bricklink_colors()] == [(5, "Red")]
    assert lookup.counts()["parts"] == 1
    assert profile_catalog._catalog_service is None, "nothing loaded the catalog"


def test_the_lookup_reports_the_status_the_service_reports(parts_db):
    path, service = parts_db
    lookup = profile_catalog.CatalogLookup(str(path))
    auto = {k: v for k, v in service.status().items() if k.startswith("auto_sync_")}
    assert set(lookup.status(running_task=None, auto_sync=auto)) == set(service.status())

    # A sync running in a child: its progress is the row it keeps in parts.db.
    profile_db.upsertCatalogSyncState(service._conn, "parts", status="running", progress_current=40, progress_total=80)
    status = lookup.status(running_task=["sync", "parts"], auto_sync=auto)
    assert status["running"] is True and status["sync_type"] == "parts"
    assert (status["progress_current"], status["progress_total"]) == (40, 80)
    assert status["types"]["parts"]["status"] == "running"
    # Not running anywhere, the same row is a sync that was cut short.
    assert lookup.status(running_task=None, auto_sync=auto)["types"]["parts"]["status"] == "interrupted"


def test_a_reload_that_lets_go_first_ends_with_the_same_catalog(parts_db):
    """What a catalog task does at the end of each sync, so that it never holds
    two copies of the catalog at once."""
    _path, service = parts_db
    service.parts_data.release_before_reload = True
    profile_db.reloadPartsData(service._conn, service.parts_data)
    assert service.parts_data.parts["3001"]["name"] == "Brick 2 x 4"
    assert 4 in service.parts_data.colors


def test_a_reload_lets_go_of_the_index_built_from_the_old_catalog(parts_db):
    """The compiler's shared index holds the catalog it was built from; kept
    past a reload, it keeps the old copy alive beside the new one."""
    from app.services.profile_engine import compiler

    _path, service = parts_db
    old = service.index()
    profile_db.reloadPartsData(service._conn, service.parts_data, rebuild_search=False)
    assert compiler._index is None
    assert service.index() is not old


# --------------------------------------------------------------------------- the runner

# A stand-in for `python -m app.catalog_task`: notes when it starts and ends,
# sleeps if told to, fails if told to.
STAND_IN = [
    sys.executable,
    "-c",
    "import os, sys, time\n"
    "words = ' '.join(sys.argv[1:])\n"
    "log = open(os.environ['STAND_IN_LOG'], 'a')\n"
    "log.write(f'start {words} {time.time()}\\n'); log.flush()\n"
    "if 'sleep' in words: time.sleep(30)\n"
    "log.write(f'end {words} {time.time()}\\n'); log.flush()\n"
    "sys.exit(1 if 'fail' in words else 0)\n",
]


@pytest.fixture()
def runner(monkeypatch, tmp_path):
    monkeypatch.setenv("STAND_IN_LOG", str(tmp_path / "children.log"))
    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_ENABLED", False)
    task_runner = CatalogTaskRunner(command=STAND_IN)
    yield task_runner
    task_runner.stop()


def _wait_for_last(task_runner: CatalogTaskRunner, task: list[str], seconds: float = 20) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        last = task_runner.status()["last"]
        if last and last["task"] == task:
            return last
        time.sleep(0.05)
    raise AssertionError(f"{task} did not finish: {task_runner.status()}")


def test_tasks_run_one_at_a_time_and_a_failure_is_kept(runner, tmp_path):
    runner.start()
    runner.request("sync", "colors")
    runner.request("sync", "colors")  # asked twice before it ran: once
    runner.request("sync", "fail")
    last = _wait_for_last(runner, ["sync", "fail"])
    assert last["outcome"] == "failed" and last["exit"] == 1
    lines = (tmp_path / "children.log").read_text().split("\n")
    events = [line.split() for line in lines if line]
    assert [(e[0], e[2]) for e in events] == [("start", "colors"), ("end", "colors"), ("start", "fail"), ("end", "fail")]


def test_a_child_past_its_time_is_stopped(runner, monkeypatch):
    monkeypatch.setattr(settings, "CATALOG_TASK_TIMEOUT_MINUTES", 0.02)
    runner.start()
    started = time.monotonic()
    runner.request("sync", "sleep")
    last = _wait_for_last(runner, ["sync", "sleep"])
    assert last["outcome"].startswith("timed out") and last["exit"] == -signal.SIGTERM
    assert time.monotonic() - started < 10


def test_stop_ends_the_running_sync(runner):
    runner.start()
    runner.request("sync", "sleep")
    deadline = time.monotonic() + 10
    while not (runner.status()["current"] or {}).get("pid") and time.monotonic() < deadline:
        time.sleep(0.05)
    runner.request_stop()
    assert _wait_for_last(runner, ["sync", "sleep"])["outcome"] == "stopped, as asked"


def test_a_stale_catalog_is_synced_in_a_child(runner, monkeypatch, tmp_path):
    """No parts.db at all is as stale as it gets: the check counts nothing and
    loads nothing, and the sync runs in a child."""
    monkeypatch.setattr(settings, "HIVE_ROLE", "worker")
    monkeypatch.setattr(settings, "PROFILE_CATALOG_AUTO_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setattr(profile_catalog, "_catalog_service", None)
    monkeypatch.setattr(profile_catalog, "_catalog_lookup", None)
    runner.start()
    _wait_for_last(runner, ["auto-sync"])
    assert runner.status()["auto_sync_plan"] == ["sets", "categories", "colors", "parts"]
    assert profile_catalog._catalog_service is None
    assert not (tmp_path / "missing.db").exists(), "looking must not create a catalog"


# --------------------------------------------------------------------------- the child


class _Syncs:
    """A sync manager whose syncs finish the moment they start."""

    def getStatus(self, parts_data) -> dict:
        return {"running": False, "error": None, "sync_type": None}

    def requestStop(self) -> None:
        pass

    def startColorsSync(self, gc, conn, parts_data, on_complete=None, on_error=None) -> bool:
        on_complete()
        return True


def test_the_child_loads_the_catalog_runs_the_sync_and_marks_it(parts_db, monkeypatch):
    from app import catalog_task
    from app.services.profile_engine import parts_cache

    monkeypatch.setattr(settings, "HIVE_ROLE", "worker")
    monkeypatch.setattr(profile_catalog, "_catalog_service", None)
    monkeypatch.setattr(parts_cache, "SyncManager", _Syncs)
    previous = signal.getsignal(signal.SIGTERM)
    try:
        assert catalog_task.run(["sync", "colors"]) == 0
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert profile_catalog._catalog_service is not None, "a catalog task may load it"
    assert profile_catalog._catalog_service.get_last_synced_at("colors")


def test_the_child_is_a_process_of_its_own():
    result = subprocess.run(
        [sys.executable, "-m", "app.catalog_task", "nonsense"],
        cwd=BACKEND,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 2, result.stderr
    assert "not a task" in result.stderr
