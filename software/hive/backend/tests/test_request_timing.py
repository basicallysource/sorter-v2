"""The request-timing middleware and its rolling window: memory that stays
the same however many requests arrive, percentiles close to the exact ones,
database time counted against the request that spent it (failed queries
too), 5xx counted, and one log line for a slow request."""

from __future__ import annotations

import logging
import random
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text

from app.middleware import request_timing
from app.middleware.request_timing import NO_ROUTE, RequestStats, RequestTimingMiddleware


class Clock:
    def __init__(self, t: float = 1_760_000_040.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _app(stats: RequestStats) -> FastAPI:
    app = FastAPI()

    @app.get("/items/{item_id}")
    def item(item_id: int) -> dict:
        return {"id": item_id}

    app.add_middleware(RequestTimingMiddleware, stats=stats)
    return app


def test_memory_stays_the_same_however_many_requests_arrive():
    clock = Clock()
    stats = RequestStats(clock=clock)
    routes = [("GET", f"/api/r{i}") for i in range(5)]
    seen_minutes: set[int] = set()
    for i in range(100_000):
        clock.t += 0.15  # four hours of requests, about seven a second
        method, route = routes[i % len(routes)]
        stats.record(method, route, 200, float(i % 3000))
        seen_minutes.add(int(clock.t // 60))

    assert len(seen_minutes) > 4 * 60
    slots = [s for s in stats._slots if s is not None]
    assert len(stats._slots) == request_timing.WINDOW_MINUTES
    assert len(slots) == request_timing.WINDOW_MINUTES
    assert all(len(s.routes) <= len(routes) for s in slots)
    assert all(len(r.hist) == request_timing._BINS for s in slots for r in s.routes.values())

    # Only the last hour is counted.
    snapshot = stats.snapshot()
    assert snapshot["window_s"] <= 3600
    assert 23_000 <= snapshot["totals"]["count"] <= 24_100
    assert {(r["method"], r["route"]) for r in snapshot["routes"]} == set(routes)


def test_routes_are_keyed_by_template_whatever_the_path_or_method():
    stats = RequestStats()
    client = TestClient(_app(stats))
    for i in range(30):
        assert client.get(f"/items/{i}").status_code == 200
    for i in range(30):
        assert client.get(f"/no/such/path/{i}").status_code == 404
    client.request("BREW", "/items/1")

    keys = {(r["method"], r["route"]): r["count"] for r in stats.snapshot()["routes"]}
    assert keys == {("GET", "/items/{item_id}"): 30, ("GET", NO_ROUTE): 30, ("OTHER", "/items/{item_id}"): 1}


def test_percentiles_are_close_to_the_exact_ones():
    stats = RequestStats(clock=Clock())
    durations = list(range(1, 1001))
    random.Random(7).shuffle(durations)
    for ms in durations:
        stats.record("GET", "/x", 200, float(ms))

    [row] = stats.snapshot()["routes"]
    assert row["count"] == 1000
    assert row["max_ms"] == 1000
    for key, exact in (("p50_ms", 500), ("p90_ms", 900), ("p99_ms", 990)):
        assert abs(row[key] - exact) <= 0.1 * exact, (key, row[key])

    one = RequestStats(clock=Clock())
    one.record("GET", "/y", 200, 437.0)
    [only] = one.snapshot()["routes"]
    assert only["p50_ms"] == only["p99_ms"] == only["max_ms"] == 437.0


def test_minutes_older_than_the_window_are_forgotten():
    clock = Clock()
    stats = RequestStats(clock=clock)
    stats.record("GET", "/old", 200, 5.0)
    clock.t += 61 * 60
    stats.record("GET", "/new", 200, 5.0)
    assert [r["route"] for r in stats.snapshot()["routes"]] == ["/new"]


def test_requests_still_running_are_listed():
    stats = RequestStats()
    token = stats.begin("GET", "/api/long")
    running = stats.snapshot()["in_flight"]
    assert running["count"] == 1 and running["oldest"][0]["path"] == "/api/long"
    stats.end(token, "GET", "/api/long", 200, 5.0, 0.0)
    assert stats.snapshot()["in_flight"]["count"] == 0


def _sleepy_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'timing.db'}", connect_args={"check_same_thread": False})

    def pause(ms):
        time.sleep(ms / 1000)
        return 0

    def pause_then_fail(ms):
        time.sleep(ms / 1000)
        raise RuntimeError("boom")

    @event.listens_for(engine, "connect")
    def _functions(dbapi_connection, _record):
        dbapi_connection.create_function("pause", 1, pause)
        dbapi_connection.create_function("pause_then_fail", 1, pause_then_fail)

    return engine


def test_database_time_counts_against_the_request_that_spent_it(tmp_path):
    engine = _sleepy_engine(tmp_path)
    stats = RequestStats()
    app = FastAPI()

    # Plain def: it runs in the threadpool, which carries the request's timer.
    @app.get("/work")
    def work() -> dict:
        with engine.connect() as conn:
            conn.execute(text("SELECT pause(60)"))
            conn.execute(text("SELECT pause(30)"))
        return {}

    @app.get("/fails")
    def fails() -> dict:
        with engine.connect() as conn:
            conn.execute(text("SELECT pause_then_fail(50)"))
        return {}

    @app.get("/idle")
    def idle() -> dict:
        return {}

    app.add_middleware(RequestTimingMiddleware, stats=stats)
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/work").status_code == 200
    assert client.get("/fails").status_code == 500
    assert client.get("/idle").status_code == 200
    # A query outside any request carries no timer and changes nothing.
    with engine.connect() as conn:
        conn.execute(text("SELECT pause(1)"))

    routes = {r["route"]: r for r in stats.snapshot()["routes"]}
    assert routes["/work"]["db_s"] >= 0.09
    assert routes["/work"]["total_s"] >= routes["/work"]["db_s"]
    # A query that fails still spent its time, and the 500 is counted.
    assert routes["/fails"]["db_s"] >= 0.05
    assert routes["/fails"]["errors"] == 1
    assert routes["/idle"]["db_s"] == 0 and routes["/idle"]["errors"] == 0


def test_a_slow_request_writes_one_line(caplog):
    stats = RequestStats(slow_s=0.05)
    app = FastAPI()

    @app.get("/slow/{n}")
    def slow(n: int) -> dict:
        time.sleep(0.06)
        return {}

    @app.get("/fast")
    def fast() -> dict:
        return {}

    app.add_middleware(RequestTimingMiddleware, stats=stats)
    client = TestClient(app)
    with caplog.at_level(logging.WARNING, logger=request_timing.__name__):
        client.get("/slow/3")
        client.get("/fast")

    lines = [r.getMessage() for r in caplog.records if r.name == request_timing.__name__]
    assert len(lines) == 1
    assert lines[0].startswith("slow request: GET /slow/{n} answered 200 in ")
    assert lines[0].endswith("in 0 database queries")
    slow_row = next(r for r in stats.snapshot()["routes"] if r["route"] == "/slow/{n}")
    assert slow_row["slow"] == 1
