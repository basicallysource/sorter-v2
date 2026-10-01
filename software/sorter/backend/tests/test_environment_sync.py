"""The backend syncs its virtualenv when uv.lock changed under it (an update)."""

import os
from pathlib import Path
from unittest import mock

import environment_sync


def _run(tmp_path: Path, calls: list) -> None:
    env = {"UV": "/usr/local/bin/uv", "VIRTUAL_ENV": str(tmp_path)}
    with mock.patch.dict(os.environ, env), mock.patch.object(
        environment_sync.subprocess, "run", side_effect=lambda *a, **k: calls.append(a[0])
    ):
        environment_sync.syncEnvironment()


def test_first_start_syncs_and_stamps(tmp_path: Path) -> None:
    calls: list = []
    _run(tmp_path, calls)
    assert calls == [["/usr/local/bin/uv", "sync", "--locked"]]
    assert (tmp_path / environment_sync.STAMP_NAME).exists()


def test_an_unchanged_lock_does_not_sync_again(tmp_path: Path) -> None:
    calls: list = []
    _run(tmp_path, calls)
    _run(tmp_path, calls)
    assert len(calls) == 1


def test_a_changed_lock_syncs(tmp_path: Path) -> None:
    calls: list = []
    (tmp_path / environment_sync.STAMP_NAME).write_text("a lock from an older release")
    _run(tmp_path, calls)
    assert len(calls) == 1


def test_an_interpreter_not_started_by_uv_is_left_alone(tmp_path: Path) -> None:
    with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
        environment_sync.subprocess, "run"
    ) as run:
        environment_sync.syncEnvironment()
    run.assert_not_called()
