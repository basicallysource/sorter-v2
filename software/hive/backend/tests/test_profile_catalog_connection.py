"""The parts catalog's one connection is used by one thread at a time.

Requests run on a thread pool, and the web process reloads the catalog on a
thread of its own after a sync, while ProfileCatalogService keeps a single
sqlite3 connection to parts.db for all of them. A sqlite3 connection can be
handed to other threads but not used by two at once: two part searches at the
same moment (the profile builder searches as you type) raised
`sqlite3.InterfaceError: bad parameter or other API misuse`.

A race is a poor thing to wait for, so the connection here is a stand-in that
notes any moment two threads are inside it, and stays inside for a few
milliseconds so that two threads let in together overlap.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from app.config import settings
from app.services import profile_catalog
from app.services.profile_engine import db as profile_db

CATEGORIES = [{"id": 1, "name": "Bricks"}, {"id": 2, "name": "Plates"}]
PARTS = [
    {"part_num": "3001", "name": "Brick 2 x 4", "part_cat_id": 1},
    {"part_num": "3004", "name": "Brick 1 x 2", "part_cat_id": 1},
    {"part_num": "3020", "name": "Plate 2 x 4", "part_cat_id": 2},
]
# What someone types to find the 2 x 4 brick, a search at every keystroke.
TYPED = ["b", "br", "bri", "brick 2x4"]


class _ConnectionProbe:
    """Stands in for the service's sqlite3 connection and notes any moment two
    threads are inside it. Every call goes on to the real connection, after a
    few milliseconds spent inside."""

    def __init__(self, connection) -> None:
        self._connection = connection
        self._guard = threading.Lock()
        self._inside: list[str] = []
        self.overlaps: list[str] = []

    @contextmanager
    def _enter(self, what: str):
        with self._guard:
            if self._inside:
                self.overlaps.append(f"{what} while {self._inside[0]}")
            self._inside.append(what)
        try:
            time.sleep(0.003)
            yield
        finally:
            with self._guard:
                self._inside.remove(what)

    def execute(self, sql, parameters=()):
        with self._enter("execute " + " ".join(sql.split())[:70]):
            return self._connection.execute(sql, parameters)

    def executemany(self, sql, parameters):
        with self._enter("executemany " + " ".join(sql.split())[:70]):
            return self._connection.executemany(sql, parameters)

    def commit(self):
        with self._enter("commit"):
            return self._connection.commit()

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _run_together(tasks: dict[str, Callable[[], Any]], timeout: float = 30.0) -> tuple[dict[str, Any], dict[str, Exception]]:
    """Run each task on a thread of its own, all let go at the same moment.
    Returns what each returned and what each raised, by name. Fails rather than
    waits for ever on a task that never ends (a deadlock)."""
    barrier = threading.Barrier(len(tasks), timeout=timeout)
    results: dict[str, Any] = {}
    errors: dict[str, Exception] = {}

    def run(name: str, task: Callable[[], Any]) -> None:
        try:
            barrier.wait()
            results[name] = task()
        except Exception as exc:
            errors[name] = exc

    threads = [threading.Thread(target=run, args=(name, task), name=name, daemon=True) for name, task in tasks.items()]
    for thread in threads:
        thread.start()
    deadline = time.monotonic() + timeout
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))
    stuck = [thread.name for thread in threads if thread.is_alive()]
    assert not stuck, f"these never finished (a deadlock?): {stuck}"
    return results, errors


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    """The web process's catalog service over a small parts.db."""
    path = str(tmp_path / "parts.db")
    monkeypatch.setattr(settings, "SORTING_PROFILE_PARTS_DB_PATH", path)
    seed = profile_db.initDb(path)
    profile_db.upsertCategories(seed, CATEGORIES)
    profile_db.upsertParts(seed, PARTS)
    profile_db.rebuildPartSearch(seed)
    # One set, 123-1, with one part in it, as the sets sync imports it.
    seed.execute("INSERT INTO rebrickable_sets (set_num, name, year, theme_id, num_parts) VALUES ('123-1', 'Test Set', 2020, 1, 2)")
    seed.execute("INSERT INTO rebrickable_inventories (id, version, set_num) VALUES (1, 1, '123-1')")
    seed.execute(
        "INSERT INTO rebrickable_inventory_parts (inventory_id, part_num, color_id, quantity, is_spare) VALUES (1, '3001', 4, 2, 0)"
    )
    seed.commit()
    seed.close()
    service = profile_catalog.ProfileCatalogService(runs_syncs=False)
    yield service
    service._conn.close()


def test_the_catalog_connection_is_never_used_by_two_threads_at_once(catalog, monkeypatch):
    # The stand-in has to notice two threads inside it, or the rest proves
    # nothing. (Over a fake connection: this is the misuse the test is about.)
    control = _ConnectionProbe(SimpleNamespace(execute=lambda sql, parameters=(): None))

    def hammer() -> None:
        for _ in range(20):
            control.execute("SELECT 1")

    _run_together({"first": hammer, "second": hammer})
    assert control.overlaps, "the stand-in does not notice two threads at once"

    probe = _ConnectionProbe(catalog._conn)
    catalog._conn = probe

    # A sync finished in the worker process: a new part, and when it finished.
    worker = profile_db.initDb(catalog._config.db_path)
    profile_db.upsertParts(worker, [{"part_num": "99999", "name": "Wedge Plate 2 x 4", "part_cat_id": 2}])
    profile_db.setMeta(worker, profile_catalog._sync_meta_key("parts"), "2026-10-12T12:00:00+00:00")
    worker.close()
    catalog._followed_at -= profile_catalog.FOLLOW_SYNCS_INTERVAL_S

    def typing() -> list:
        return [catalog.search_parts(query) for query in TYPED]

    def a_set() -> tuple:
        found = catalog.get_set_inventory("123-1")
        return found["set"], found["inventory"], catalog.search_sets("test set")

    # Everything that reaches the connection from a request or the follow
    # thread, at once, with six people typing.
    tasks: dict[str, Callable[[], Any]] = {f"typing {n}": typing for n in range(6)}
    tasks.update(
        {
            "status": catalog.status,
            "overview": catalog.admin_overview,
            "list parts": lambda: catalog.admin_list_parts("brick"),
            "one part": lambda: catalog.admin_get_part("3001"),
            "categories": catalog.admin_list_categories,
            "last synced": catalog.get_last_synced_at_map,
            "bricklink categories": lambda: catalog.bricklink_category_names(["3001"]),
            "a set": a_set,
            "follow": catalog.follow_syncs,
        }
    )
    results, errors = _run_together(tasks)

    assert probe.overlaps == [], f"two threads were inside the catalog's connection at once: {probe.overlaps}"
    assert not errors, errors
    for name, found in results.items():
        if name.startswith("typing"):
            assert [part["part_num"] for part in found[-1]["results"]] == ["3001"]
    found, inventory, searched = results["a set"]
    assert found["name"] == "Test Set"
    assert [row["part_num"] for row in inventory] == ["3001"]
    assert [row["set_num"] for row in searched] == ["123-1"]

    # The reload the follow started read parts.db on a connection of its own.
    for thread in threading.enumerate():
        if thread.name == "catalog-follow":
            thread.join(10)
    assert "99999" in catalog.parts_data.parts
