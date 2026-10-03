"""A machine updated from a release that ran the UI in its own Vite unit builds
the UI, removes that unit and restarts its backend service, whose supervisor
then serves the build."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import environment_sync


@pytest.fixture
def machine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    for unit in ("sorter-backend-dev.service", "sorter-ui-dev.service", "sorter-ui.service"):
        (systemd / unit).write_text("[Service]\n")
    services = tmp_path / "active-services"
    services.write_text("sorter-backend-dev.service\nsorter-ui-dev.service\n")
    state = SimpleNamespace(systemd=systemd, services=services, calls=[], failing_build=False)

    def run(command, **_kwargs):
        state.calls.append(list(command))
        if command[0] == "pnpm" and state.failing_build:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(environment_sync, "SYSTEMD_DIR", systemd)
    monkeypatch.setattr(environment_sync, "SORTEROS_SERVICES", services)
    monkeypatch.setattr(environment_sync, "_ownService", lambda: "sorter-backend-dev.service")
    monkeypatch.setattr(environment_sync.os, "geteuid", lambda: 0)
    monkeypatch.setattr(environment_sync.subprocess, "run", run)
    monkeypatch.setattr(environment_sync.time, "sleep", lambda _s: None)
    return state


def test_the_old_units_go_once_the_ui_is_built(machine) -> None:
    environment_sync.retireOldUiUnits()
    assert machine.calls == [
        ["pnpm", "install", "--frozen-lockfile"],
        ["pnpm", "build"],
        ["systemctl", "disable", "--now", "sorter-ui-dev.service", "sorter-ui.service"],
        ["systemctl", "daemon-reload"],
        ["systemctl", "--no-block", "restart", "sorter-backend-dev.service"],
    ]
    assert sorted(p.name for p in machine.systemd.iterdir()) == ["sorter-backend-dev.service"]
    assert machine.services.read_text() == "sorter-backend-dev.service\n"


def test_a_failed_build_keeps_the_old_units(machine) -> None:
    machine.failing_build = True
    environment_sync.retireOldUiUnits()
    assert machine.calls == [["pnpm", "install", "--frozen-lockfile"]]
    assert (machine.systemd / "sorter-ui-dev.service").exists()
    assert "sorter-ui-dev.service" in machine.services.read_text()


def test_nothing_happens_once_they_are_gone(machine) -> None:
    (machine.systemd / "sorter-ui-dev.service").unlink()
    (machine.systemd / "sorter-ui.service").unlink()
    environment_sync.retireOldUiUnits()
    assert machine.calls == []


def test_nothing_happens_outside_a_systemd_service(machine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment_sync, "_ownService", lambda: None)
    environment_sync.retireOldUiUnits()
    assert machine.calls == []
