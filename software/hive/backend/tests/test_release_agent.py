"""The release agent deploys the services a release's compose file defines, and
stops one it does not: rolling back past the release that added the worker
must not leave the worker running beside a backend that runs every worker
itself. Docker is faked; this checks what the agent asks it to do, in order."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

AGENT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "hive_release_agent.py"


@pytest.fixture()
def agent(monkeypatch):
    name = "hive_release_agent_under_test"
    spec = importlib.util.spec_from_file_location(name, AGENT_PATH)
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses look their module up by name while the class is built.
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class FakeDocker:
    def __init__(self, services: list[str], existing: set[str]):
        self.services = services
        self.existing = existing
        self.calls: list[list[str]] = []

    def __call__(self, args, **_kwargs):
        args = list(args)
        self.calls.append(args)
        out, code = "", 0
        if args[:2] == ["docker", "compose"] and "config" in args:
            out = "\n".join(self.services) + "\n"
        elif args[:2] == ["docker", "inspect"]:
            name, fmt = args[2], args[-1]
            if fmt == "{{.Id}}":
                code = 0 if name in self.existing else 1
            elif fmt == "{{.State.StartedAt}}":
                out = (datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat()
            else:
                out = "healthy"
        return subprocess.CompletedProcess(args, code, out, "")

    def compose(self, verb: str) -> list[str]:
        call = next(c for c in self.calls if c[:2] == ["docker", "compose"] and verb in c)
        return call[call.index(verb):]

    def index(self, prefix: list[str]) -> int:
        return next(i for i, c in enumerate(self.calls) if c[: len(prefix)] == prefix)


def _apply(agent, monkeypatch, tmp_path, docker: FakeDocker) -> None:
    monkeypatch.setattr(agent.subprocess, "run", docker)
    monkeypatch.setattr(agent, "httpHealthy", lambda url: True)
    cfg = agent.AgentConfig(tmp_path, tmp_path, tmp_path, tmp_path / ".env.prod", tmp_path / "lock", tmp_path)
    manifest = {"images": {"backend": "b@sha256:1", "frontend": "f@sha256:2"}}
    agent.applyRelease(cfg, manifest, tmp_path / "docker-compose.prod.yml")


def test_a_release_with_a_worker_deploys_it(agent, monkeypatch, tmp_path):
    docker = FakeDocker(["postgres", "backend", "worker", "frontend"], existing={"hive-backend", "hive-frontend"})
    _apply(agent, monkeypatch, tmp_path, docker)
    assert docker.compose("pull") == ["pull", "backend", "worker", "frontend"]
    assert docker.compose("up")[-3:] == ["backend", "worker", "frontend"]
    assert not any(c[:2] == ["docker", "stop"] for c in docker.calls)
    # Health is waited for on the worker too.
    assert ["docker", "inspect", "hive-worker", "--format", "{{.State.Health.Status}}"] in docker.calls


def test_rolling_back_past_the_worker_stops_it_first(agent, monkeypatch, tmp_path):
    docker = FakeDocker(["postgres", "backend", "frontend"], existing={"hive-backend", "hive-worker", "hive-frontend"})
    _apply(agent, monkeypatch, tmp_path, docker)
    assert docker.compose("pull") == ["pull", "backend", "frontend"]
    assert docker.compose("up")[-2:] == ["backend", "frontend"] and "worker" not in docker.compose("up")
    stop = docker.index(["docker", "stop"])
    assert docker.calls[stop] == ["docker", "stop", "--time", "30", "hive-worker"]
    assert docker.calls[stop + 1] == ["docker", "rm", "hive-worker"]
    # Gone before the older backend, which runs every worker itself, comes up.
    assert stop < next(i for i, c in enumerate(docker.calls) if c[:2] == ["docker", "compose"] and "up" in c)
    # And migrated exactly once, with the backend service.
    migrations = [c for c in docker.calls if "alembic" in c]
    assert len(migrations) == 1 and migrations[0][-4:] == ["backend", "alembic", "upgrade", "head"]
