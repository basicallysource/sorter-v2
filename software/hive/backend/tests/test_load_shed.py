"""Turning sorters' uploads away while Hive is overloaded: a 429 with a
Retry-After before the endpoint runs, only on the upload routes, an episode
that starts and ends once (with one alert each), and memory read from the
container's cgroup."""

from __future__ import annotations

import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware import load_shed
from app.middleware.load_shed import LoadShedder, LoadShedMiddleware


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _shedder(clock=None, memory=None, alerts=None, **overrides) -> LoadShedder:
    options = dict(
        max_uploads_in_flight=2,
        max_requests_in_flight=50,
        memory_fraction=0.8,
        hold_s=60.0,
        retry_after_s=60,
    )
    options.update(overrides)
    return LoadShedder(
        clock=clock or Clock(),
        wall_clock=lambda: 1_760_000_000.0,
        read_memory=(lambda: memory[0]) if memory is not None else (lambda: None),
        alert=(lambda **kw: alerts.append(kw)) if alerts is not None else (lambda **kw: None),
        **options,
    )


def _app(shedder: LoadShedder, calls: list[str]) -> FastAPI:
    app = FastAPI()

    @app.post("/api/machine/sync/channel-crop-batch")
    def crops() -> dict:
        calls.append("crops")
        return {"max_local_id": 7}

    @app.post("/api/machine/sync/piece-records")
    def records() -> dict:
        calls.append("records")
        return {"max_local_id": 3}

    app.add_middleware(LoadShedMiddleware, shedder=shedder)
    return app


def test_uploads_pass_while_hive_is_not_overloaded():
    calls: list[str] = []
    shedder = _shedder()
    client = TestClient(_app(shedder, calls))
    response = client.post("/api/machine/sync/channel-crop-batch", files={"file": ("b.bin", b"x" * 1000)})
    assert response.status_code == 200
    assert calls == ["crops"]
    assert shedder.uploads_in_flight == 0 and shedder.requests_in_flight == 0


def test_an_overloaded_hive_answers_429_before_the_endpoint_runs():
    calls: list[str] = []
    alerts: list[dict] = []
    memory = [(900, 1000)]  # 90% of the limit
    shedder = _shedder(memory=memory, alerts=alerts)
    client = TestClient(_app(shedder, calls))

    response = client.post("/api/machine/sync/channel-crop-batch", files={"file": ("b.bin", b"x" * 100_000)})

    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.json()["code"] == "HIVE_OVERLOADED"
    assert calls == []
    assert shedder.uploads_in_flight == 0
    assert [a["request_id"] for a in alerts] == ["hive-load-shed-1760000000-start"]
    assert alerts[0]["urgency"] == "time_sensitive"


def test_only_the_upload_routes_are_turned_away():
    calls: list[str] = []
    shedder = _shedder(memory=[(900, 1000)])
    client = TestClient(_app(shedder, calls))
    assert client.post("/api/machine/sync/piece-records", json=[]).status_code == 200
    assert calls == ["records"]


def test_too_many_uploads_in_flight_trips_it():
    shedder = _shedder()
    assert shedder.admit_upload() and shedder.admit_upload()
    assert not shedder.admit_upload()  # the third, with two in flight
    assert shedder.shedding


def test_an_episode_starts_once_holds_and_ends_once():
    clock = Clock()
    alerts: list[dict] = []
    memory = [(900, 1000)]
    shedder = _shedder(clock=clock, memory=memory, alerts=alerts)

    for _ in range(5):
        assert not shedder.admit_upload()
    memory[0] = (100, 1000)
    clock.t += 30  # inside the hold: still refusing
    clock.t += 1.1  # (past the memory cache)
    assert not shedder.admit_upload()
    clock.t += 61
    assert shedder.admit_upload()
    shedder.upload_finished()

    assert [a["request_id"].rsplit("-", 1)[1] for a in alerts] == ["start", "end"]
    assert "6 uploads were turned away" in alerts[1]["message"]
    assert alerts[1]["urgency"] == "normal"


def test_another_request_ends_an_episode_when_no_upload_comes():
    clock = Clock()
    alerts: list[dict] = []
    memory = [(900, 1000)]
    shedder = _shedder(clock=clock, memory=memory, alerts=alerts)
    calls: list[str] = []
    client = TestClient(_app(shedder, calls))
    assert not shedder.admit_upload()
    memory[0] = (100, 1000)
    clock.t += 120
    client.post("/api/machine/sync/piece-records", json=[])
    assert not shedder.shedding
    assert len(alerts) == 2


def test_memory_is_the_cgroups_anonymous_memory(tmp_path, monkeypatch):
    (tmp_path / "memory.max").write_text("1887436800\n")
    (tmp_path / "memory.stat").write_text("file 900000000\nanon 600000000\nshmem 0\n")
    monkeypatch.setattr(load_shed, "_CGROUP", tmp_path)
    assert load_shed._read_cgroup_memory() == (600000000, 1887436800)
    (tmp_path / "memory.max").write_text("max\n")
    assert load_shed._read_cgroup_memory() is None


def test_a_refused_upload_body_is_read_to_the_end():
    shedder = _shedder(memory=[(900, 1000)])
    chunks = [
        {"type": "http.request", "body": b"a" * 10, "more_body": True},
        {"type": "http.request", "body": b"b" * 10, "more_body": False},
    ]
    sent: list[dict] = []

    async def receive():
        return chunks.pop(0)

    async def send(message):
        sent.append(message)

    async def never(scope, receive, send):  # pragma: no cover - must not run
        raise AssertionError("the endpoint ran")

    scope = {"type": "http", "method": "POST", "path": "/api/machine/sync/piece-image"}
    asyncio.run(LoadShedMiddleware(never, shedder=shedder)(scope, receive, send))
    assert chunks == []
    assert sent[0]["status"] == 429
    assert json.loads(sent[1]["body"])["code"] == "HIVE_OVERLOADED"
